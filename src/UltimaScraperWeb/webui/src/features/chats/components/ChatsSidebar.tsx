import { stripHtml } from '../../../utils/sanitize';
import type { ChatInfo } from '../../../api/types/chats';
import { formatChatTime } from '../lib/chatUtils';

interface ChatsSidebarProps {
  searchTerm: string;
  onSearchChange: (value: string) => void;
  chatsLoading: boolean;
  chatsError: unknown;
  isSyncing: boolean;
  sortedChats: ChatInfo[];
  selectedChatId: number | null;
  onSelectChat: (chat: ChatInfo) => void;
}

export function ChatsSidebar({
  searchTerm,
  onSearchChange,
  chatsLoading,
  chatsError,
  isSyncing,
  sortedChats,
  selectedChatId,
  onSelectChat,
}: ChatsSidebarProps) {
  return (
    <div className="chat-list-panel">
      <div className="chat-list-header">
        <input
          type="text"
          placeholder="Search conversations..."
          value={searchTerm}
          onChange={(event) => onSearchChange(event.target.value)}
          className="chat-search"
        />
        {isSyncing && <span className="sync-indicator" title="Syncing chats from API...">⟳</span>}
      </div>

      <div className="chat-list">
        {chatsLoading ? (
          <div className="chat-list-loading">Loading chats...</div>
        ) : chatsError ? (
          <div className="chat-list-error">Failed to load chats</div>
        ) : sortedChats.length === 0 ? (
          <div className="chat-list-empty">
            {searchTerm ? 'No matching chats' : 'No chats found'}
          </div>
        ) : (
          sortedChats.map((chat) => (
            <div
              key={chat.id}
              className={`chat-item ${selectedChatId === chat.id ? 'selected' : ''}`}
              onClick={() => onSelectChat(chat)}
            >
              <div className="chat-avatar">
                {chat.user.avatar_url ? (
                  <img src={chat.user.avatar_url} alt={chat.user.username} />
                ) : (
                  <div className="avatar-placeholder">
                    {chat.user.username.charAt(0).toUpperCase()}
                  </div>
                )}
              </div>
              <div className="chat-info">
                <div className="chat-name">
                  <span className="username">@{chat.user.username}</span>
                  {chat.user.name && <span className="display-name">{chat.user.name}</span>}
                </div>
                <div className="chat-preview">
                  {chat.last_message_text ? stripHtml(chat.last_message_text) : 'No messages yet'}
                </div>
              </div>
              <div className="chat-meta">
                {chat.last_message_at && (
                  <span className="chat-time">{formatChatTime(chat.last_message_at)}</span>
                )}
                {chat.pinned_count > 0 && (
                  <span className="pinned-badge" title={`${chat.pinned_count} pinned`}>
                    📌
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
