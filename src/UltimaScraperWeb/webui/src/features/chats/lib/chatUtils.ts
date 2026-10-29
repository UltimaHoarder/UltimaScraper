import { backendResourceUrl } from '../../../api/http';
import { getMediaProxyUrl } from '../../../api/media';
import type { MediaItemInfo } from '../../../api/types/chats';

export const MESSAGE_PAGE_SIZE = 100;

export function proxyMediaUrls(
  media: MediaItemInfo[],
  site: string,
  authId: number | null,
): MediaItemInfo[] {
  const proxy = (url: string | null | undefined): string | null => {
    if (!url) {
      return null;
    }
    if (url.startsWith('/')) {
      return backendResourceUrl(url);
    }
    return getMediaProxyUrl(url, site, authId);
  };

  return media.map((item) => ({
    ...item,
    url: proxy(item.url),
    thumb_url: proxy(item.thumb_url),
    preview_url: proxy(item.preview_url),
    local_url: proxy(item.local_url),
  }));
}

export function formatChatTime(dateStr: string) {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (days === 0) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  if (days === 1) {
    return 'Yesterday';
  }
  if (days < 7) {
    return date.toLocaleDateString([], { weekday: 'short' });
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export function formatMessageTime(dateStr: string) {
  const date = new Date(dateStr);
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
