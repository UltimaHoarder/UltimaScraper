import { createHttpClient } from './http';
import type {
  BrowseContentLibraryOptions,
  ContentLibraryResponse,
} from './types/content';

const http = createHttpClient();

export async function browseContentLibrary(
  options?: BrowseContentLibraryOptions,
): Promise<ContentLibraryResponse> {
  const params: Record<string, string> = {};
  if (options?.site) params.site = options.site;
  if (options?.contentType) params.content_type = options.contentType;
  if (options?.userId) params.user_id = options.userId.toString();
  if (options?.excludeUserIds?.length) params.exclude_user_ids = options.excludeUserIds.join(',');
  if (options?.search) params.search = options.search;
  if (options?.sortBy) params.sort_by = options.sortBy;
  if (options?.order) params.order = options.order;
  if (options?.includeFlags?.length) params.include_flags = options.includeFlags.join(',');
  if (options?.excludeFlags?.length) params.exclude_flags = options.excludeFlags.join(',');
  if (options?.page) params.page = options.page.toString();
  if (options?.pageSize) params.page_size = options.pageSize.toString();
  if (options?.includeTotal === false) params.include_total = 'false';

  const response = await http.get<ContentLibraryResponse>('/api/v1/database/content', {
    params,
    signal: options?.signal,
  });
  return response.data;
}
