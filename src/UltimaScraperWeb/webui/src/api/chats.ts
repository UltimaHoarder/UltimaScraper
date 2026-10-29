import { createHttpClient } from './http';
import type {
  BuyMessageResponse,
  ChatListResponse,
  LikeMessageResponse,
  MessageListResponse,
  SendMessageRequest,
  SendMessageResponse,
} from './types/chats';

const http = createHttpClient();

export async function getChats(
  site: string,
  authId?: number,
  limit?: number,
  offset?: number,
): Promise<ChatListResponse> {
  const params: Record<string, string> = {};
  if (authId !== undefined) params.auth_id = authId.toString();
  if (limit) params.limit = limit.toString();
  if (offset) params.offset = offset.toString();
  const response = await http.get<ChatListResponse>(`/api/v1/chats/${site}`, { params });
  return response.data;
}

export async function getChatMessages(
  site: string,
  userId: number,
  authId?: number,
  limit?: number,
  offsetId?: number,
): Promise<MessageListResponse> {
  const params: Record<string, string> = {};
  if (authId !== undefined) params.auth_id = authId.toString();
  if (limit) params.limit = limit.toString();
  if (offsetId) params.offset_id = offsetId.toString();
  const response = await http.get<MessageListResponse>(
    `/api/v1/chats/${site}/${userId}/messages`,
    { params },
  );
  return response.data;
}

export async function sendChatMessage(
  site: string,
  userId: number,
  text: string,
  authId?: number,
  price?: number | null,
  lockedText?: boolean | null,
): Promise<SendMessageResponse> {
  const params: Record<string, string> = {};
  if (authId !== undefined) params.auth_id = authId.toString();
  const body: SendMessageRequest = { text };
  if (price !== undefined && price !== null) body.price = price;
  if (lockedText !== undefined && lockedText !== null) body.locked_text = lockedText;
  const response = await http.post<SendMessageResponse>(
    `/api/v1/chats/${site}/${userId}/messages`,
    body,
    { params },
  );
  return response.data;
}

export async function buyChatMessage(
  site: string,
  userId: number,
  messageId: number,
  authId?: number,
): Promise<BuyMessageResponse> {
  const params: Record<string, string> = {};
  if (authId !== undefined) params.auth_id = authId.toString();
  const response = await http.post<BuyMessageResponse>(
    `/api/v1/chats/${site}/${userId}/messages/${messageId}/buy`,
    {},
    { params },
  );
  return response.data;
}

export async function likeChatMessage(
  site: string,
  userId: number,
  messageId: number,
  authId?: number,
): Promise<LikeMessageResponse> {
  const params: Record<string, string> = {};
  if (authId !== undefined) params.auth_id = authId.toString();
  const response = await http.post<LikeMessageResponse>(
    `/api/v1/chats/${site}/${userId}/messages/${messageId}/like`,
    {},
    { params },
  );
  return response.data;
}
