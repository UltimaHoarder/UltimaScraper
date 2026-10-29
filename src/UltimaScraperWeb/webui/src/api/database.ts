import { createHttpClient } from './http';
import type { MediaBrowserResponse } from './types/database';

const http = createHttpClient();

export async function browseMedia(
  site?: string,
  userId?: number,
  mediaType?: string,
  downloadedOnly?: boolean,
  page?: number,
  pageSize?: number,
): Promise<MediaBrowserResponse> {
  const params: Record<string, string> = {};
  if (site) params.site = site;
  if (userId) params.user_id = userId.toString();
  if (mediaType) params.media_type = mediaType;
  if (downloadedOnly) params.downloaded_only = 'true';
  if (page) params.page = page.toString();
  if (pageSize) params.page_size = pageSize.toString();

  const response = await http.get<MediaBrowserResponse>('/api/v1/database/media', { params });
  return response.data;
}

export {
  analyzeDatabase,
  getDatabaseOverview,
  reindexDatabase,
  vacuumDatabase,
} from './system';

