import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getAuthBalance, getAuthList } from '../../../api/auths';
import {
  buyChatMessage,
  getChatMessages,
  getChats,
  likeChatMessage,
  sendChatMessage,
} from '../../../api/chats';
import { appUrl, getWebSocketBaseUrl } from '../../../api/http';
import type { AuthCredential } from '../../../api/types/auths';
import type { ChatInfo, MediaItemInfo } from '../../../api/types/chats';
import { useWebSocket, type WebSocketEvent } from '../../../hooks/useWebSocket';
import { MESSAGE_PAGE_SIZE } from '../lib/chatUtils';

export function useChatsPageController() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSite = searchParams.get('site');
  const urlUserId = searchParams.get('userId');
  const deepLinkTarget = useRef<{ site: string; userId: number } | null>(
    urlSite && urlUserId ? { site: urlSite, userId: Number(urlUserId) } : null,
  );

  const [selectedSite, setSelectedSite] = useState<string>(urlSite || 'onlyfans');
  const [selectedAuthId, setSelectedAuthId] = useState<number | null>(null);
  const [selectedChat, setSelectedChat] = useState<ChatInfo | null>(null);
  const [messageText, setMessageText] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [pendingBuyMessageId, setPendingBuyMessageId] = useState<number | null>(null);
  const [pendingBuyPrice, setPendingBuyPrice] = useState<number | null>(null);
  const [isChatListOpen, setIsChatListOpen] = useState(false);
  const [chatMenuOpen, setChatMenuOpen] = useState(false);
  const [lightboxMedia, setLightboxMedia] = useState<MediaItemInfo | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const prevPageCountRef = useRef(0);
  const chatMenuRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const openLightbox = useCallback((media: MediaItemInfo) => {
    setLightboxMedia(media);
  }, []);

  const closeLightbox = useCallback(() => {
    setLightboxMedia(null);
  }, []);

  useEffect(() => {
    if (!chatMenuOpen) return;
    const handler = (event: MouseEvent) => {
      if (chatMenuRef.current && !chatMenuRef.current.contains(event.target as Node)) {
        setChatMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [chatMenuOpen]);

  const { data: auths } = useQuery({
    queryKey: ['auths', 'chat-filter', selectedSite],
    queryFn: () => getAuthList(selectedSite, true),
  });
  const authOptions = useMemo(() => auths?.auths ?? [], [auths?.auths]);
  const effectiveSelectedAuthId =
    selectedAuthId !== null && authOptions.some((auth: AuthCredential) => auth.id === selectedAuthId)
      ? selectedAuthId
      : (authOptions[0]?.id ?? null);
  const authBalanceIds = useMemo(
    () => authOptions.map((auth: AuthCredential) => auth.id),
    [authOptions],
  );

  const {
    data: chatsData,
    isLoading: chatsLoading,
    error: chatsError,
  } = useQuery({
    queryKey: ['chats', selectedSite, effectiveSelectedAuthId],
    queryFn: () => getChats(selectedSite, effectiveSelectedAuthId ?? undefined),
    enabled: effectiveSelectedAuthId !== null,
  });

  useEffect(() => {
    const target = deepLinkTarget.current;
    if (!target || !chatsData?.chats) return;
    const match = chatsData.chats.find((chat) => chat.id === target.userId);
    if (match) {
      setSelectedChat(match);
      deepLinkTarget.current = null;
      setSearchParams({}, { replace: true });
    } else if (authOptions.length > 1) {
      const currentIndex = authOptions.findIndex((auth) => auth.id === effectiveSelectedAuthId);
      const nextAuth = authOptions[currentIndex + 1];
      if (nextAuth) {
        setSelectedAuthId(nextAuth.id);
      }
    }
  }, [authOptions, chatsData, effectiveSelectedAuthId, setSearchParams]);

  const {
    data: messagesData,
    isLoading: messagesLoading,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
  } = useInfiniteQuery({
    queryKey: ['chat-messages', selectedSite, selectedChat?.id, effectiveSelectedAuthId],
    queryFn: ({ pageParam }) =>
      getChatMessages(
        selectedSite,
        selectedChat!.id,
        effectiveSelectedAuthId ?? undefined,
        MESSAGE_PAGE_SIZE,
        typeof pageParam === 'number' ? pageParam : undefined,
      ),
    enabled: Boolean(selectedChat) && effectiveSelectedAuthId !== null,
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more || lastPage.messages.length === 0) {
        return undefined;
      }
      const oldestMessage = lastPage.messages.reduce((oldest, message) =>
        message.id < oldest.id ? message : oldest,
      );
      return oldestMessage.id;
    },
  });

  const {
    data: authBalances = {},
    isLoading: authBalancesLoading,
  } = useQuery({
    queryKey: ['chat-auth-balances', 'page', selectedSite, authBalanceIds],
    queryFn: async (): Promise<Record<number, number | null>> => {
      const entries = await Promise.all(
        authBalanceIds.map(async (authId) => {
          try {
            const response = await getAuthBalance(authId, selectedSite);
            if (response.success) {
              return [authId, response.balance ?? null] as const;
            }
          } catch {
            // Ignore per-auth balance errors.
          }
          return [authId, null] as const;
        }),
      );

      return Object.fromEntries(entries);
    },
    enabled: authBalanceIds.length > 0,
    staleTime: 30_000,
  });

  const handleWebSocketMessage = useCallback((wsEvent: WebSocketEvent) => {
    if (wsEvent.event === 'chats_synced') {
      const syncSite = (wsEvent as Record<string, unknown>).site as string | undefined;
      const syncAuthId = (wsEvent as Record<string, unknown>).auth_id as number | undefined;
      if (!syncSite || syncSite === selectedSite) {
        if (syncAuthId === undefined || syncAuthId === null || syncAuthId === effectiveSelectedAuthId) {
          queryClient.invalidateQueries({
            queryKey: ['chats', selectedSite, effectiveSelectedAuthId],
          });
        }
      }
      return;
    }

    if (wsEvent.event === 'messages_synced') {
      const syncSite = (wsEvent as Record<string, unknown>).site as string | undefined;
      const syncUserId = (wsEvent as Record<string, unknown>).chat_user_id as number | undefined;
      if ((!syncSite || syncSite === selectedSite) && syncUserId === selectedChat?.id) {
        queryClient.invalidateQueries({
          queryKey: ['chat-messages', selectedSite, selectedChat?.id, effectiveSelectedAuthId],
        });
      }
      return;
    }

    if (wsEvent.event === 'chat_message_like') {
      queryClient.invalidateQueries({
        queryKey: ['chat-messages', selectedSite, selectedChat?.id, effectiveSelectedAuthId],
      });
      return;
    }

    const chatMessage = wsEvent.api2_chat_message || wsEvent.new_message;
    if (!chatMessage) return;
    const fromUserId = chatMessage.fromUser?.id || chatMessage.user_id;
    if (!fromUserId) return;

    const isRelevant =
      selectedChat !== null &&
      (fromUserId === selectedChat.id || chatMessage.userId === selectedChat.id);

    if (isRelevant) {
      queryClient.invalidateQueries({
        queryKey: ['chat-messages', selectedSite, selectedChat?.id, effectiveSelectedAuthId],
      });
    }

    queryClient.invalidateQueries({
      queryKey: ['chats', selectedSite, effectiveSelectedAuthId],
    });
  }, [effectiveSelectedAuthId, queryClient, selectedChat, selectedSite]);

  useWebSocket({
    url: `${getWebSocketBaseUrl()}/ws/events`,
    topics: ['chats'],
    onMessage: handleWebSocketMessage,
    reconnect: true,
  });

  const sendMessageMutation = useMutation({
    mutationFn: (text: string) => {
      if (!selectedChat || effectiveSelectedAuthId === null) {
        return Promise.reject(new Error('No chat selected'));
      }
      return sendChatMessage(selectedSite, selectedChat.id, text, effectiveSelectedAuthId);
    },
    onSuccess: () => {
      setMessageText('');
      queryClient.invalidateQueries({
        queryKey: ['chat-messages', selectedSite, selectedChat?.id, effectiveSelectedAuthId],
      });
    },
  });

  const buyMessageMutation = useMutation({
    mutationFn: async (messageId: number) => {
      if (!selectedChat || effectiveSelectedAuthId === null) {
        return Promise.reject(new Error('No chat selected'));
      }
      const response = await buyChatMessage(
        selectedSite,
        selectedChat.id,
        messageId,
        effectiveSelectedAuthId,
      );
      if (!response.success) {
        throw new Error(response.error || 'Purchase failed');
      }
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['chat-messages', selectedSite, selectedChat?.id, effectiveSelectedAuthId],
      });
      queryClient.invalidateQueries({
        queryKey: ['chats', selectedSite, effectiveSelectedAuthId],
      });
      setPendingBuyMessageId(null);
      setPendingBuyPrice(null);
    },
  });

  const likeMessageMutation = useMutation({
    mutationFn: async (messageId: number) => {
      if (!selectedChat || effectiveSelectedAuthId === null) {
        return Promise.reject(new Error('No chat selected'));
      }
      const response = await likeChatMessage(
        selectedSite,
        selectedChat.id,
        messageId,
        effectiveSelectedAuthId,
      );
      if (!response.success) {
        throw new Error(response.error || 'Like toggle failed');
      }
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['chat-messages', selectedSite, selectedChat?.id, effectiveSelectedAuthId],
      });
    },
  });

  const openBuyConfirmation = (messageId: number, price: number | null | undefined) => {
    if (buyMessageMutation.isPending) return;
    setPendingBuyMessageId(messageId);
    setPendingBuyPrice(price ?? null);
  };

  const closeBuyConfirmation = () => {
    if (buyMessageMutation.isPending) return;
    setPendingBuyMessageId(null);
    setPendingBuyPrice(null);
  };

  const confirmBuy = () => {
    if (pendingBuyMessageId === null) return;
    buyMessageMutation.mutate(pendingBuyMessageId);
  };

  useEffect(() => {
    const pageCount = messagesData?.pages.length ?? 0;
    const container = messageListRef.current;

    if (pageCount <= 1) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    } else if (pageCount > prevPageCountRef.current && container) {
      const prevScrollHeight = container.scrollHeight;
      const prevScrollTop = container.scrollTop;
      requestAnimationFrame(() => {
        const newScrollHeight = container.scrollHeight;
        container.scrollTop = prevScrollTop + (newScrollHeight - prevScrollHeight);
      });
    }

    prevPageCountRef.current = pageCount;
  }, [messagesData]);

  useEffect(() => {
    const sentinel = topSentinelRef.current;
    const container = messageListRef.current;
    if (!sentinel || !container) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      {
        root: container,
        rootMargin: '200px 0px 0px 0px',
        threshold: 0,
      },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const filteredChats = useMemo(
    () =>
      chatsData?.chats.filter((chat) => {
        if (!searchTerm) return true;
        const term = searchTerm.toLowerCase();
        return (
          chat.user.username.toLowerCase().includes(term) ||
          chat.user.name?.toLowerCase().includes(term)
        );
      }) || [],
    [chatsData?.chats, searchTerm],
  );

  const sortedChats = useMemo(
    () =>
      filteredChats
        .map((chat, index) => {
          const parsed = chat.last_message_at ? Date.parse(chat.last_message_at) : Number.NaN;
          const timestamp = Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
          return { chat, index, timestamp };
        })
        .sort((a, b) => (b.timestamp - a.timestamp) || (a.index - b.index))
        .map(({ chat }) => chat),
    [filteredChats],
  );

  const handleSendMessage = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (messageText.trim()) {
      sendMessageMutation.mutate(messageText.trim());
    }
  };

  const allMessages = useMemo(
    () => messagesData?.pages.flatMap((page) => page.messages) ?? [],
    [messagesData?.pages],
  );
  const dedupedMessages = useMemo(
    () => Array.from(new Map(allMessages.map((message) => [message.id, message])).values()),
    [allMessages],
  );
  const sortedMessages = useMemo(
    () =>
      [...dedupedMessages].sort((a, b) => {
        const timeDiff = Date.parse(a.created_at) - Date.parse(b.created_at);
        if (!Number.isNaN(timeDiff) && timeDiff !== 0) {
          return timeDiff;
        }
        return a.id - b.id;
      }),
    [dedupedMessages],
  );

  const selectedBalance =
    effectiveSelectedAuthId !== null ? authBalances[effectiveSelectedAuthId] : undefined;
  const isAuthBalanceLoading = authOptions.length > 0 && authBalancesLoading;

  const handleSelectChat = (chat: ChatInfo) => {
    setSelectedChat(chat);
    setIsChatListOpen(false);
  };

  const handleSyncMessages = () => {
    setChatMenuOpen(false);
    queryClient.invalidateQueries({
      queryKey: ['chat-messages', selectedSite, selectedChat?.id, effectiveSelectedAuthId],
    });
  };

  const handleOpenProfile = () => {
    setChatMenuOpen(false);
    if (!selectedChat) return;
    window.open(appUrl(`/users/${selectedChat.id}?site=${encodeURIComponent(selectedSite)}`), '_blank');
  };

  return {
    authBalances,
    authOptions,
    buyMessageMutation,
    chatMenuOpen,
    chatMenuRef,
    chatsData,
    chatsError,
    chatsLoading,
    closeBuyConfirmation,
    closeLightbox,
    confirmBuy,
    effectiveSelectedAuthId,
    handleOpenProfile,
    handleSelectChat,
    handleSendMessage,
    handleSyncMessages,
    isAuthBalanceLoading,
    isChatListOpen,
    isFetchingNextPage,
    lightboxMedia,
    likeMessageMutation,
    messageListRef,
    messageText,
    messagesData,
    messagesEndRef,
    messagesLoading,
    onLikeMessage: likeMessageMutation.mutate,
    openBuyConfirmation,
    openLightbox,
    pendingBuyMessageId,
    pendingBuyPrice,
    searchTerm,
    selectedAuthId,
    selectedBalance,
    selectedChat,
    selectedSite,
    sendMessageMutation,
    setChatMenuOpen,
    setIsChatListOpen,
    setLightboxMedia,
    setMessageText,
    setSearchTerm,
    setSelectedAuthId,
    setSelectedChat,
    setSelectedSite,
    setSearchParams,
    sortedChats,
    sortedMessages,
    topSentinelRef,
  };
}
