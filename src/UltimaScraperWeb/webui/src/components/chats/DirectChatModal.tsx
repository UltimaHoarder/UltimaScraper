import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getAuthBalance } from '../../api/auths';
import { FavouriteButton } from '../../features/favourites/FavouriteButton';
import {
  buyChatMessage,
  getChatMessages,
  likeChatMessage,
  sendChatMessage,
} from '../../api/chats';
import { getWebSocketBaseUrl } from '../../api/http';
import type { MediaItemInfo, MessageInfo } from '../../api/types/chats';
import { getEligibleAuths } from '../../api/users';
import { proxyMediaUrls } from '../../features/chats/lib/chatUtils';
import { useWebSocket, type WebSocketEvent } from '../../hooks/useWebSocket';
import { MediaCarousel } from '../MediaCarousel';
import { LazyVideoPlayer } from '../LazyVideoPlayer';
import { sanitizeHtmlWithSafeLinks } from '../../utils/sanitize';
import './DirectChatModal.css';

const MESSAGE_PAGE_SIZE = 100;

interface DirectChatModalProps {
  isOpen: boolean;
  onClose: () => void;
  site: string;
  userId: number;
  username: string;
  displayName?: string | null;
  avatarUrl?: string | null;
}

export function DirectChatModal({
  isOpen,
  onClose,
  site,
  userId,
  username,
  displayName,
  avatarUrl,
}: DirectChatModalProps) {
  const queryClient = useQueryClient();
  const [selectedAuthId, setSelectedAuthId] = useState<number | null>(null);
  const [messageText, setMessageText] = useState('');
  const [pendingBuyMessageId, setPendingBuyMessageId] = useState<number | null>(null);
  const [pendingBuyPrice, setPendingBuyPrice] = useState<number | null>(null);
  const [lightboxMedia, setLightboxMedia] = useState<MediaItemInfo | null>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const prevPageCountRef = useRef(0);

  const resetTransientState = useCallback(() => {
    setMessageText('');
    setPendingBuyMessageId(null);
    setPendingBuyPrice(null);
    setLightboxMedia(null);
  }, []);

  const handleClose = useCallback(() => {
    resetTransientState();
    onClose();
  }, [onClose, resetTransientState]);

  useEffect(() => {
    if (!isOpen) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') handleClose();
    };
    document.addEventListener('keydown', onEscape);
    return () => document.removeEventListener('keydown', onEscape);
  }, [handleClose, isOpen]);

  const { data: eligibleAuthsData, isLoading: eligibleAuthsLoading } = useQuery({
    queryKey: ['eligible-chat-auths', site, userId],
    queryFn: () => getEligibleAuths(userId, site),
    enabled: isOpen,
  });

  const chatAuthOptions = useMemo(
    () =>
      (eligibleAuthsData?.auths ?? [])
        .filter((auth) => auth.is_active)
        .map((auth) => ({
          id: auth.auth_id,
          username: auth.auth_username || `User ${auth.auth_id}`,
        })),
    [eligibleAuthsData?.auths]
  );
  const activeAuthId =
    selectedAuthId !== null && chatAuthOptions.some((auth) => auth.id === selectedAuthId)
      ? selectedAuthId
      : (chatAuthOptions[0]?.id ?? null);
  const authBalanceIds = useMemo(
    () => chatAuthOptions.map((auth) => auth.id),
    [chatAuthOptions]
  );

  const {
    data: messagesData,
    isLoading: messagesLoading,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
  } = useInfiniteQuery({
    queryKey: ['chat-messages', site, userId, activeAuthId, 'modal'],
    queryFn: ({ pageParam }) =>
      getChatMessages(
        site,
        userId,
        activeAuthId ?? undefined,
        MESSAGE_PAGE_SIZE,
        typeof pageParam === 'number' ? pageParam : undefined
      ),
    enabled: isOpen && activeAuthId !== null,
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more || lastPage.messages.length === 0) return undefined;
      const oldestMessage = lastPage.messages.reduce((oldest, msg) =>
        msg.id < oldest.id ? msg : oldest
      );
      return oldestMessage.id;
    },
  });

  const {
    data: authBalances = {},
    isLoading: authBalancesLoading,
  } = useQuery({
    queryKey: ['chat-auth-balances', 'modal', site, userId, authBalanceIds],
    queryFn: async (): Promise<Record<number, number | null>> => {
      const entries = await Promise.all(
        authBalanceIds.map(async (authId) => {
          try {
            const response = await getAuthBalance(authId, site);
            if (response.success) {
              return [authId, response.balance ?? null] as const;
            }
          } catch {
            // Ignore per-auth balance failures.
          }
          return [authId, null] as const;
        })
      );

      return Object.fromEntries(entries);
    },
    enabled: isOpen && authBalanceIds.length > 0,
    staleTime: 30_000,
  });

  const sendMessageMutation = useMutation({
    mutationFn: async (text: string) => {
      if (activeAuthId === null) throw new Error('No auth selected');
      const response = await sendChatMessage(site, userId, text, activeAuthId);
      if (!response.success) throw new Error(response.error || 'Failed to send message');
      return response;
    },
    onSuccess: () => {
      setMessageText('');
      queryClient.invalidateQueries({ queryKey: ['chat-messages', site, userId, activeAuthId, 'modal'] });
      queryClient.invalidateQueries({ queryKey: ['chats', site, activeAuthId] });
    },
  });

  const buyMessageMutation = useMutation({
    mutationFn: async (messageId: number) => {
      if (activeAuthId === null) throw new Error('No auth selected');
      const response = await buyChatMessage(site, userId, messageId, activeAuthId);
      if (!response.success) throw new Error(response.error || 'Purchase failed');
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-messages', site, userId, activeAuthId, 'modal'] });
      setPendingBuyMessageId(null);
      setPendingBuyPrice(null);
    },
  });

  const likeMessageMutation = useMutation({
    mutationFn: async (messageId: number) => {
      if (activeAuthId === null) throw new Error('No auth selected');
      const response = await likeChatMessage(site, userId, messageId, activeAuthId);
      if (!response.success) throw new Error(response.error || 'Like toggle failed');
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-messages', site, userId, activeAuthId, 'modal'] });
    },
  });

  const handleWebSocketMessage = useCallback((wsEvent: WebSocketEvent) => {
    if (!isOpen) return;
    if (wsEvent.event === 'messages_synced') {
      const syncSite = (wsEvent as Record<string, unknown>).site as string | undefined;
      const syncUserId = (wsEvent as Record<string, unknown>).chat_user_id as number | undefined;
      if ((!syncSite || syncSite === site) && syncUserId === userId) {
        queryClient.invalidateQueries({ queryKey: ['chat-messages', site, userId, activeAuthId, 'modal'] });
      }
      return;
    }

    if (wsEvent.event === 'chat_message_like') {
      queryClient.invalidateQueries({ queryKey: ['chat-messages', site, userId, activeAuthId, 'modal'] });
      return;
    }

    const chatMessage = wsEvent.api2_chat_message || wsEvent.new_message;
    if (!chatMessage) return;
    const fromUserId = chatMessage.fromUser?.id || chatMessage.user_id;
    if (!fromUserId) return;

    const isRelevant = fromUserId === userId || chatMessage.userId === userId;
    if (isRelevant) {
      queryClient.invalidateQueries({ queryKey: ['chat-messages', site, userId, activeAuthId, 'modal'] });
      queryClient.invalidateQueries({ queryKey: ['chats', site, activeAuthId] });
    }
  }, [activeAuthId, isOpen, queryClient, site, userId]);

  useWebSocket({
    url: `${getWebSocketBaseUrl()}/ws/events`,
    topics: ['chats'],
    onMessage: handleWebSocketMessage,
    reconnect: true,
  });

  useEffect(() => {
    if (!isOpen) return;
    const pageCount = messagesData?.pages.length ?? 0;
    const container = messageListRef.current;

    if (pageCount <= 1) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
    } else if (pageCount > prevPageCountRef.current && container) {
      const prevScrollHeight = container.scrollHeight;
      const prevScrollTop = container.scrollTop;
      requestAnimationFrame(() => {
        const newScrollHeight = container.scrollHeight;
        container.scrollTop = prevScrollTop + (newScrollHeight - prevScrollHeight);
      });
    }

    prevPageCountRef.current = pageCount;
  }, [messagesData, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
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
      }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage, isOpen]);

  const allMessages = useMemo(() => messagesData?.pages.flatMap((page) => page.messages) ?? [], [messagesData]);
  const sortedMessages = useMemo(() => {
    const deduped = Array.from(new Map(allMessages.map((msg) => [msg.id, msg])).values());
    return deduped.sort((a, b) => {
      const timeDiff = Date.parse(a.created_at) - Date.parse(b.created_at);
      if (!Number.isNaN(timeDiff) && timeDiff !== 0) return timeDiff;
      return a.id - b.id;
    });
  }, [allMessages]);

  const formatMessageTime = (value: string) => {
    const date = new Date(value);
    return date.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const selectedBalance = activeAuthId !== null ? authBalances[activeAuthId] : undefined;
  const isBalanceLoading = isOpen && chatAuthOptions.length > 0 && authBalancesLoading;

  const handleSendMessage = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = messageText.trim();
    if (!trimmed || sendMessageMutation.isPending) return;
    sendMessageMutation.mutate(trimmed);
  };

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

  if (!isOpen) return null;

  return (
    <div className="modal-overlay direct-chat-overlay" onClick={handleClose}>
      <div className="modal direct-chat-modal" onClick={(event) => event.stopPropagation()}>
        <div className="direct-chat-header">
          <div className="direct-chat-user">
            {avatarUrl ? (
              <img src={avatarUrl} alt={username} className="direct-chat-avatar" />
            ) : (
              <div className="direct-chat-avatar direct-chat-avatar-placeholder">
                {(username?.charAt(0) || '?').toUpperCase()}
              </div>
            )}
            <div className="direct-chat-user-meta">
              <div className="direct-chat-username">@{username}</div>
              {displayName ? <div className="direct-chat-name">{displayName}</div> : null}
            </div>
          </div>
          <button className="modal-close" onClick={handleClose}>×</button>
        </div>

        <div className="direct-chat-toolbar">
          {chatAuthOptions.length > 1 ? (
            <select
              value={activeAuthId ?? ''}
              onChange={(event) => setSelectedAuthId(event.target.value ? Number(event.target.value) : null)}
              className="direct-chat-auth-select"
            >
              {chatAuthOptions.map((auth) => (
                <option key={auth.id} value={auth.id}>
                  @{auth.username}
                </option>
              ))}
            </select>
          ) : chatAuthOptions.length === 1 ? (
            <span className="direct-chat-auth-single">@{chatAuthOptions[0].username}</span>
          ) : null}
          <span className="direct-chat-balance">
            {isBalanceLoading
              ? 'Balance: Loading...'
              : selectedBalance !== undefined && selectedBalance !== null
                ? `Balance: $${selectedBalance.toFixed(2)}`
                : 'Balance: Unavailable'}
          </span>
        </div>

        <div className="direct-chat-messages" ref={messageListRef}>
          {eligibleAuthsLoading ? (
            <div className="direct-chat-placeholder">Checking accessible accounts...</div>
          ) : chatAuthOptions.length === 0 ? (
            <div className="direct-chat-placeholder">No auth accounts can chat with this user.</div>
          ) : messagesLoading ? (
            <div className="direct-chat-placeholder">Loading messages...</div>
          ) : sortedMessages.length === 0 ? (
            <div className="direct-chat-placeholder">No messages yet. Start the conversation.</div>
          ) : (
            <>
              <div ref={topSentinelRef} className="scroll-sentinel-top" />
              {isFetchingNextPage && <div className="loading-older-messages">Loading older messages...</div>}
              {sortedMessages.map((msg: MessageInfo) => (
                <div key={msg.id} className={`message ${msg.is_from_me ? 'sent' : 'received'}`}>
                  <div className="message-bubble">
                    {msg.text ? (
                      <div
                        className="message-text"
                        dangerouslySetInnerHTML={{ __html: sanitizeHtmlWithSafeLinks(msg.text) }}
                      />
                    ) : msg.media_count > 0 ? null : (
                      <div className="message-text message-text-empty">(Empty message)</div>
                    )}

                    {msg.media && msg.media.length > 0 && (
                      <MediaCarousel
                        media={proxyMediaUrls(msg.media, site, activeAuthId)}
                        price={msg.price}
                        isOpened={msg.is_opened}
                        hasRebundledMedia={msg.has_rebundled_media}
                        onMediaClick={(media) => setLightboxMedia(media)}
                        onBuyClick={() => openBuyConfirmation(msg.id, msg.price)}
                      />
                    )}
                  </div>
                  <div className="message-meta">
                    <FavouriteButton entity={{ site, entity_type: 'message', entity_id: msg.id }} />
                    <span className="message-time">{formatMessageTime(msg.created_at)}</span>
                    {!msg.is_from_me && (
                      <button
                        type="button"
                        className={`message-like-btn${msg.is_liked ? ' liked' : ''}`}
                        title={msg.is_liked ? 'Unlike message' : 'Like message'}
                        disabled={likeMessageMutation.isPending}
                        onClick={() => likeMessageMutation.mutate(msg.id)}
                      >
                        {msg.is_liked ? '❤️' : '🤍'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        <form className="direct-chat-input-area" onSubmit={handleSendMessage}>
          <input
            type="text"
            placeholder="Type a message..."
            value={messageText}
            onChange={(event) => setMessageText(event.target.value)}
            className="message-input"
            disabled={sendMessageMutation.isPending || activeAuthId === null}
          />
          <button
            type="submit"
            className="send-button"
            disabled={!messageText.trim() || sendMessageMutation.isPending || activeAuthId === null}
          >
            {sendMessageMutation.isPending ? '⏳' : '📤'}
          </button>
        </form>

        {(sendMessageMutation.isError || buyMessageMutation.isError) && (
          <div className="send-error">
            {sendMessageMutation.isError
              ? `Failed to send message: ${(sendMessageMutation.error as Error).message}`
              : `Failed to unlock message: ${(buyMessageMutation.error as Error).message}`}
          </div>
        )}
      </div>

      {lightboxMedia && (
        <div className="lightbox-overlay" onClick={(event) => {
          event.stopPropagation();
          setLightboxMedia(null);
        }}>
          <div className="lightbox-content" onClick={(event) => event.stopPropagation()}>
            <button className="lightbox-close" onClick={() => setLightboxMedia(null)}>×</button>
            {lightboxMedia.media_type === 'video' ? (
              <LazyVideoPlayer
                src={lightboxMedia.local_url || lightboxMedia.url || lightboxMedia.preview_url || ''}
                controls
                autoplay
                fluid={false}
                className="vjs-lightbox"
              />
            ) : (
              <img
                src={lightboxMedia.local_url || lightboxMedia.url || lightboxMedia.preview_url || lightboxMedia.thumb_url || ''}
                alt="Full size media"
                className="lightbox-image"
              />
            )}
          </div>
        </div>
      )}

      {pendingBuyMessageId !== null && (
        <div className="confirm-overlay" onClick={(event) => {
          event.stopPropagation();
          closeBuyConfirmation();
        }}>
          <div className="confirm-modal" onClick={(event) => event.stopPropagation()}>
            <div className="confirm-title">Unlock PPV</div>
            <div className="confirm-message">
              {pendingBuyPrice !== null
                ? `Unlock this message for $${pendingBuyPrice.toFixed(2)}?`
                : 'Unlock this message?'}
            </div>
            <div className="confirm-balance">
              {isBalanceLoading
                ? 'Balance: Loading...'
                : selectedBalance !== undefined && selectedBalance !== null
                  ? `Balance: $${selectedBalance.toFixed(2)}`
                  : 'Balance: Unavailable'}
            </div>
            <div className="confirm-actions">
              <button
                type="button"
                className="confirm-cancel"
                onClick={closeBuyConfirmation}
                disabled={buyMessageMutation.isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                className="confirm-buy"
                onClick={() => {
                  if (pendingBuyMessageId !== null) buyMessageMutation.mutate(pendingBuyMessageId);
                }}
                disabled={buyMessageMutation.isPending}
              >
                {buyMessageMutation.isPending ? 'Buying...' : 'Buy'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
