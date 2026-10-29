import { useChatsPageController } from '../../../../features/chats/hooks/useChatsPageController';
import { ChatMessagePanel } from '../../../../features/chats/components/ChatMessagePanel';
import { ChatsSidebar } from '../../../../features/chats/components/ChatsSidebar';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import {
  TerminalSlab,
  WarningPlate,
} from '../../patterns/InvestigationKit';
import './ChatsPage.css';

export function ChatsPage() {
  const {
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
    onLikeMessage,
    openBuyConfirmation,
    openLightbox,
    pendingBuyMessageId,
    pendingBuyPrice,
    searchTerm,
    selectedBalance,
    selectedChat,
    selectedSite,
    sendMessageMutation,
    setChatMenuOpen,
    setIsChatListOpen,
    setMessageText,
    setSearchTerm,
    setSelectedAuthId,
    setSelectedSite,
    sortedChats,
    sortedMessages,
    topSentinelRef,
  } = useChatsPageController();

  const selectedChatId = selectedChat?.id ?? null;
  const chatsSyncing = chatsData?.syncing ?? false;
  const messageSyncing = messagesData?.pages[0]?.syncing ?? false;
  const sendError =
    sendMessageMutation.error instanceof Error ? sendMessageMutation.error.message : null;
  const buyError =
    buyMessageMutation.error instanceof Error ? buyMessageMutation.error.message : null;

  const statusTone = effectiveSelectedAuthId
    ? selectedChat
      ? 'live'
      : 'ok'
    : 'warn';
  const statusLabel = effectiveSelectedAuthId
    ? `${sortedChats.length} chats`
    : 'No account';

  return (
    <div className="chats-page ultimur-chats-v2">
      <WorkspacePageHeader
        eyebrow="People"
        title="Chats"
        subtitle="Conversations, account balances, and message history."
        icon="▤"
        meta={(
          <div className="ultimur-topbar__actions">
            <span className={`ultimur-topbar__status ultimur-topbar__status--${statusTone}`}>
              <span className="ultimur-topbar__dot" />
              {statusLabel}
            </span>
          <div className="ultimur-chats-v2__selectors">
            <select
              value={selectedSite}
              onChange={(event) => {
                setSelectedSite(event.target.value);
                setSelectedAuthId(null);
              }}
              className="site-select"
            >
              <option value="onlyfans">OnlyFans</option>
            </select>

            <select
              value={effectiveSelectedAuthId ?? ''}
              onChange={(event) => {
                setSelectedAuthId(event.target.value ? Number(event.target.value) : null);
              }}
              className="auth-select"
            >
              <option value="">Select Account</option>
              {authOptions.map((auth) => (
                <option key={auth.id} value={auth.id}>
                  @{auth.username || `User ${auth.id}`}
                  {isAuthBalanceLoading
                    ? ' (...)'
                    : authBalances[auth.id] !== undefined && authBalances[auth.id] !== null
                      ? ` ($${authBalances[auth.id]!.toFixed(2)})`
                      : ' ($--)'}
                </option>
              ))}
            </select>
            <span className="balance-badge">
              {isAuthBalanceLoading
                ? 'Balance: Loading\u2026'
                : selectedBalance !== undefined && selectedBalance !== null
                  ? `Balance: $${selectedBalance.toFixed(2)}`
                  : 'Balance: Unavailable'}
            </span>
          </div>
          </div>
        )}
      />

      {!effectiveSelectedAuthId ? (
        <WarningPlate tone="warning" title="Select an account to open chat history">
          Chats require an active auth selection before history and balances can be loaded.
        </WarningPlate>
      ) : null}

      {chatsSyncing || messageSyncing ? (
        <WarningPlate tone="info" title="Chat sync in progress">
          {messageSyncing
            ? 'Refreshing the current conversation history.'
            : 'Refreshing the account chat list and conversation metadata.'}
        </WarningPlate>
      ) : null}

      <TerminalSlab
        eyebrow="Transcript lane"
        title={selectedChat ? `Conversation / @${selectedChat.user.username}` : 'Conversation lane'}
      >
        <div className={`chats-container ${isChatListOpen ? 'sidebar-open' : ''}`}>
          <div
            className="chat-list-overlay"
            onClick={() => setIsChatListOpen(false)}
            role="presentation"
          />

          <ChatsSidebar
            searchTerm={searchTerm}
            onSearchChange={setSearchTerm}
            chatsLoading={chatsLoading}
            chatsError={chatsError}
            isSyncing={chatsSyncing}
            sortedChats={sortedChats}
            selectedChatId={selectedChatId}
            onSelectChat={handleSelectChat}
          />

          <ChatMessagePanel
            selectedChat={selectedChat}
            selectedSite={selectedSite}
            effectiveSelectedAuthId={effectiveSelectedAuthId}
            isMessageSyncing={messageSyncing}
            chatMenuOpen={chatMenuOpen}
            onToggleChatMenu={() => setChatMenuOpen((open) => !open)}
            onCloseChatMenu={() => setChatMenuOpen(false)}
            onSyncMessages={handleSyncMessages}
            onOpenProfile={handleOpenProfile}
            chatMenuRef={chatMenuRef}
            messageListRef={messageListRef}
            topSentinelRef={topSentinelRef}
            messagesEndRef={messagesEndRef}
            messagesLoading={messagesLoading}
            sortedMessages={sortedMessages}
            isFetchingNextPage={isFetchingNextPage}
            likePending={likeMessageMutation.isPending}
            onLikeMessage={onLikeMessage}
            onOpenLightbox={openLightbox}
            onOpenBuyConfirmation={openBuyConfirmation}
            onOpenChatList={() => setIsChatListOpen(true)}
            messageText={messageText}
            onMessageTextChange={setMessageText}
            onSendMessage={handleSendMessage}
            sendPending={sendMessageMutation.isPending}
            sendError={sendError}
            buyError={buyError}
            lightboxMedia={lightboxMedia}
            onCloseLightbox={closeLightbox}
            pendingBuyMessageId={pendingBuyMessageId}
            pendingBuyPrice={pendingBuyPrice}
            onCloseBuyConfirmation={closeBuyConfirmation}
            onConfirmBuy={confirmBuy}
            buyPending={buyMessageMutation.isPending}
            isAuthBalanceLoading={isAuthBalanceLoading}
            selectedBalance={selectedBalance}
          />
        </div>
      </TerminalSlab>
    </div>
  );
}
