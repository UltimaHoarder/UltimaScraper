import { backendUrl, getApiBaseUrl } from './http';

export function getMediaFileUrl(siteName: string, mediaId: number): string {
  const base = getApiBaseUrl();
  return backendUrl(
    `${base}/api/v1/media/stream/${encodeURIComponent(siteName)}/${mediaId}`,
  );
}

export function getJobTaskResultFileUrl(
  jobId: string,
  taskId: string,
  resultIndex: number,
): string {
  const base = getApiBaseUrl();
  return backendUrl(
    `${base}/api/v1/jobs/${encodeURIComponent(jobId)}/tasks/${encodeURIComponent(taskId)}/files/${resultIndex}`,
  );
}

export function getDrmManifestUrl(siteName: string, mediaId: number): string {
  const base = getApiBaseUrl();
  return backendUrl(
    `${base}/api/v1/media/drm/${encodeURIComponent(siteName)}/${mediaId}/manifest.mpd`,
  );
}

export function getDrmLicenseUrl(siteName: string, mediaId: number): string {
  const base = getApiBaseUrl();
  return backendUrl(
    `${base}/api/v1/media/drm/${encodeURIComponent(siteName)}/${mediaId}/license`,
  );
}

/** True when the current browser can play Widevine-protected DASH via EME. */
export function browserSupportsWidevine(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof navigator.requestMediaKeySystemAccess === 'function'
  );
}

export function getMediaProxyUrl(
  cdnUrl: string | null | undefined,
  site: string,
  authId?: number | null,
): string | null {
  if (!cdnUrl) return null;

  const params = new URLSearchParams({ url: cdnUrl, site });
  if (authId != null) {
    params.set('auth_id', authId.toString());
  }
  return backendUrl(`/api/v1/media/proxy?${params.toString()}`);
}
