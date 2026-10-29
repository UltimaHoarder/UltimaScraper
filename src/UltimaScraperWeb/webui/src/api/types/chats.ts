export interface ChatUserInfo {
  id: number;
  username: string;
  name: string | null;
  avatar_url: string | null;
}

export interface ChatInfo {
  id: number;
  user: ChatUserInfo;
  last_message_text: string | null;
  last_message_at: string | null;
  unread_count: number;
  has_purchased_feed: boolean;
  pinned_count: number;
}

export interface ChatListResponse {
  success: boolean;
  chats: ChatInfo[];
  total: number;
  source: 'db' | 'api';
  syncing: boolean;
  error: string | null;
}

export interface MediaItemInfo {
  id: number;
  media_type: 'image' | 'video' | 'audio' | 'gif' | 'photo';
  url: string | null;
  thumb_url: string | null;
  preview_url: string | null;
  local_url: string | null;
  width: number | null;
  height: number | null;
  duration: number | null;
  can_view: boolean;
  has_drm: boolean;
  is_ready: boolean;
  already_owned: boolean;
}

export interface MessageInfo {
  id: number;
  text: string;
  from_user_id: number;
  from_username: string;
  is_from_me: boolean;
  created_at: string;
  is_tip: boolean;
  is_free: boolean | null;
  price: number | null;
  media_count: number;
  media: MediaItemInfo[];
  is_opened: boolean | null;
  is_liked: boolean;
  has_rebundled_media: boolean;
}

export interface MessageListResponse {
  success: boolean;
  messages: MessageInfo[];
  has_more: boolean;
  source: 'db' | 'api';
  syncing: boolean;
  error: string | null;
}

export interface SendMessageRequest {
  text: string;
  price?: number | null;
  locked_text?: boolean | null;
}

export interface SendMessageResponse {
  success: boolean;
  message: MessageInfo | null;
  error: string | null;
}

export interface BuyMessageResponse {
  success: boolean;
  message: MessageInfo | null;
  error: string | null;
}

export interface LikeMessageResponse {
  success: boolean;
  is_liked: boolean;
  error: string | null;
}
