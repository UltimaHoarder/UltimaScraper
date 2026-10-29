import type { FormEvent, RefObject } from 'react';

import type { ChatInfo, MediaItemInfo, MessageInfo } from '../../../api/types/chats';
import { sanitizeHtmlWithSafeLinks } from '../../../utils/sanitize';
import { MediaCarousel } from '../../../components/MediaCarousel';
import { LazyVideoPlayer } from '../../../components/LazyVideoPlayer';
import { formatMessageTime, proxyMediaUrls } from '../lib/chatUtils';
import { FavouriteButton } from '../../favourites/FavouriteButton';

interface ChatMessagePanelProps {
  selectedChat: ChatInfo | null;
  selectedSite: string;
  effectiveSelectedAuthId: number | null;
  isMessageSyncing: boolean;
  chatMenuOpen: boolean;
  onToggleChatMenu: () => void;
  onCloseChatMenu: () => void;
  onSyncMessages: () => void;
  onOpenProfile: () => void;
  chatMenuRef: RefObject<HTMLDivElement | null>;
  messageListRef: RefObject<HTMLDivElement | null>;
  topSentinelRef: RefObject<HTMLDivElement | null>;
  messagesEndRef: RefObject<HTMLDivElement | null>;
  messagesLoading: boolean;
  sortedMessages: MessageInfo[];
  isFetchingNextPage: boolean;
  likePending: boolean;
  onLikeMessage: (messageId: number) => void;
  onOpenLightbox: (media: MediaItemInfo) => void;
  onOpenBuyConfirmation: (messageId: number, price: number | null | undefined) => void;
  onOpenChatList: () => void;
  messageText: string;
  onMessageTextChange: (value: string) => void;
  onSendMessage: (event: FormEvent<HTMLFormElement>) => void;
  sendPending: boolean;
  sendError: string | null;
  buyError: string | null;
  lightboxMedia: MediaItemInfo | null;
  onCloseLightbox: () => void;
  pendingBuyMessageId: number | null;
  pendingBuyPrice: number | null;
  onCloseBuyConfirmation: () => void;
  onConfirmBuy: () => void;
  buyPending: boolean;
  isAuthBalanceLoading: boolean;
  selectedBalance: number | null | undefined;
}

export function ChatMessagePanel({
  selectedChat,
  selectedSite,
  effectiveSelectedAuthId,
  isMessageSyncing,
  chatMenuOpen,
  onToggleChatMenu,
  onSyncMessages,
  onOpenProfile,
  chatMenuRef,
  messageListRef,
  topSentinelRef,
  messagesEndRef,
  messagesLoading,
  sortedMessages,
  isFetchingNextPage,
  likePending,
  onLikeMessage,
  onOpenLightbox,
  onOpenBuyConfirmation,
  onOpenChatList,
  messageText,
  onMessageTextChange,
  onSendMessage,
  sendPending,
  sendError,
  buyError,
  lightboxMedia,
  onCloseLightbox,
  pendingBuyMessageId,
  pendingBuyPrice,
  onCloseBuyConfirmation,
  onConfirmBuy,
  buyPending,
  isAuthBalanceLoading,
  selectedBalance,
}: ChatMessagePanelProps) {
  return (
    <div className="message-panel">
      {selectedChat ? (
        <>
          <div className="message-header">
            <div className="message-header-user">
              <button
                type="button"
                className="mobile-chat-toggle"
                onClick={onOpenChatList}
                aria-label="Open chat list"
              >
                ☰
              </button>
              <div className="header-avatar">
                {selectedChat.user.avatar_url ? (
                  <img src={selectedChat.user.avatar_url} alt={selectedChat.user.username} />
                ) : (
                  <div className="avatar-placeholder">
                    {selectedChat.user.username.charAt(0).toUpperCase()}
                  </div>
                )}
              </div>
              <div className="header-info">
                <span className="header-username">@{selectedChat.user.username}</span>
                {selectedChat.user.name && (
                  <span className="header-name">{selectedChat.user.name}</span>
                )}
              </div>
              {isMessageSyncing && (
                <span className="sync-indicator" title="Syncing messages from API...">
                  ⟳
                </span>
              )}
            </div>
            <div className="chat-header-actions" ref={chatMenuRef}>
              <button
                type="button"
                className="chat-menu-btn"
                onClick={onToggleChatMenu}
                title="More options"
              >
                ⋮
              </button>
              {chatMenuOpen && (
                <div className="chat-menu-dropdown">
                  <button type="button" onClick={onSyncMessages}>
                    🔄 Sync Messages
                  </button>
                  <button type="button" onClick={onOpenProfile}>
                    👤 View Profile
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="message-list" ref={messageListRef}>
            {messagesLoading ? (
              <div className="messages-loading">Loading messages...</div>
            ) : sortedMessages.length === 0 ? (
              <div className="messages-empty">No messages yet. Start the conversation!</div>
            ) : (
              <>
                <div ref={topSentinelRef} className="scroll-sentinel-top" />
                {isFetchingNextPage && (
                  <div className="loading-older-messages">Loading older messages...</div>
                )}

                {sortedMessages.map((message) => (
                  <div
                    key={message.id}
                    className={`message ${message.is_from_me ? 'sent' : 'received'}`}
                  >
                    <div className="message-bubble">
                      {message.text ? (
                        <div
                          className="message-text"
                          dangerouslySetInnerHTML={{
                            __html: sanitizeHtmlWithSafeLinks(message.text),
                          }}
                        />
                      ) : message.media_count > 0 ? null : (
                        <div className="message-text message-text-empty">(Empty message)</div>
                      )}

                      {message.media && message.media.length > 0 && (
                        <MediaCarousel
                          media={proxyMediaUrls(
                            message.media,
                            selectedSite,
                            effectiveSelectedAuthId,
                          )}
                          price={message.price}
                          isOpened={message.is_opened}
                          hasRebundledMedia={message.has_rebundled_media}
                          onMediaClick={onOpenLightbox}
                          onBuyClick={() => onOpenBuyConfirmation(message.id, message.price)}
                        />
                      )}

                      {message.is_tip && <div className="message-tip-badge">💵 Tip</div>}
                    </div>
                    <div className="message-meta">
                      <FavouriteButton entity={{ site: selectedSite, entity_type: 'message', entity_id: message.id }} />
                      <span className="message-time">
                        {formatMessageTime(message.created_at)}
                      </span>
                      {!message.is_from_me && (
                        <button
                          type="button"
                          className={`message-like-btn${message.is_liked ? ' liked' : ''}`}
                          title={message.is_liked ? 'Unlike message' : 'Like message'}
                          disabled={likePending}
                          onClick={(event) => {
                            event.stopPropagation();
                            onLikeMessage(message.id);
                          }}
                        >
                          {message.is_liked ? '❤️' : '🤍'}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form className="message-input-area" onSubmit={onSendMessage}>
            <input
              type="text"
              placeholder="Type a message..."
              value={messageText}
              onChange={(event) => onMessageTextChange(event.target.value)}
              className="message-input"
              disabled={sendPending}
            />
            <button
              type="submit"
              className="send-button"
              disabled={!messageText.trim() || sendPending}
            >
              {sendPending ? '⏳' : '📤'}
            </button>
          </form>

          {sendError && <div className="send-error">Failed to send message: {sendError}</div>}
          {buyError && <div className="send-error">Failed to unlock message: {buyError}</div>}
        </>
      ) : (
        <div className="no-chat-selected">
          <div className="no-chat-icon">💬</div>
          <h2>Select a conversation</h2>
          <p>Choose a chat from the left to view messages</p>
          <button
            type="button"
            className="open-chat-list"
            onClick={onOpenChatList}
          >
            Open chats
          </button>
        </div>
      )}

      {lightboxMedia && (
        <div className="lightbox-overlay" onClick={onCloseLightbox}>
          <div className="lightbox-content" onClick={(event) => event.stopPropagation()}>
            <button className="lightbox-close" onClick={onCloseLightbox}>
              ×
            </button>
            {lightboxMedia.media_type === 'video' ? (
              <LazyVideoPlayer
                src={
                  lightboxMedia.local_url ||
                  lightboxMedia.url ||
                  lightboxMedia.preview_url ||
                  ''
                }
                controls
                autoplay
                fluid={false}
                className="vjs-lightbox"
              />
            ) : (
              <img
                src={
                  lightboxMedia.local_url ||
                  lightboxMedia.url ||
                  lightboxMedia.preview_url ||
                  lightboxMedia.thumb_url ||
                  ''
                }
                alt="Full size media"
                className="lightbox-image"
              />
            )}
          </div>
        </div>
      )}

      {pendingBuyMessageId !== null && (
        <div className="confirm-overlay" onClick={onCloseBuyConfirmation}>
          <div className="confirm-modal" onClick={(event) => event.stopPropagation()}>
            <div className="confirm-title">Unlock PPV</div>
            <div className="confirm-message">
              {pendingBuyPrice !== null
                ? `Unlock this message for $${pendingBuyPrice.toFixed(2)}?`
                : 'Unlock this message?'}
            </div>
            <div className="confirm-balance">
              {isAuthBalanceLoading
                ? 'Balance: Loading...'
                : selectedBalance !== undefined && selectedBalance !== null
                  ? `Balance: $${selectedBalance.toFixed(2)}`
                  : 'Balance: Unavailable'}
            </div>
            <div className="confirm-actions">
              <button
                type="button"
                className="confirm-cancel"
                onClick={onCloseBuyConfirmation}
                disabled={buyPending}
              >
                Cancel
              </button>
              <button
                type="button"
                className="confirm-buy"
                onClick={onConfirmBuy}
                disabled={buyPending}
              >
                {buyPending ? 'Buying...' : 'Buy'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
