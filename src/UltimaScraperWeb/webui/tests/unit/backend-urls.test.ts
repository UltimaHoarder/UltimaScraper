import { afterEach, describe, expect, it } from 'vitest';

import { backendResourceUrl, backendUrl } from '../../src/api/http';
import { getMediaFileUrl, getMediaProxyUrl } from '../../src/api/media';

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('backend URLs', () => {
  it('sends media, socket and stream URLs to the open backend, with no token', () => {
    window.history.replaceState(null, '', '/b/nas/content');

    const mediaFileUrl = new URL(getMediaFileUrl('OnlyFans', 123), window.location.origin);
    const mediaProxyUrl = new URL(
      getMediaProxyUrl('https://cdn.example.test/video.mp4', 'onlyfans', 77) ?? '',
      window.location.origin,
    );

    expect(backendUrl('/ws/events')).toBe('/b/nas/ws/events');
    expect(mediaFileUrl.pathname).toBe('/b/nas/api/v1/media/stream/OnlyFans/123');
    expect(mediaProxyUrl.pathname).toBe('/b/nas/api/v1/media/proxy');
    expect(mediaProxyUrl.searchParams.get('site')).toBe('onlyfans');
    expect(mediaProxyUrl.searchParams.get('auth_id')).toBe('77');
    for (const url of [mediaFileUrl, mediaProxyUrl]) expect(url.searchParams.has('admin_token')).toBe(false);
  });

  it('routes only backend paths a backend returned', () => {
    window.history.replaceState(null, '', '/b/nas/');

    expect(backendResourceUrl('/api/v1/media/thumbnail/onlyfans/2')).toBe('/b/nas/api/v1/media/thumbnail/onlyfans/2');
    expect(backendResourceUrl('/assets/logo.png')).toBe('/assets/logo.png');
    expect(backendResourceUrl('https://cdn.example.test/api/v1/media/stream/foo/3')).toBe(
      'https://cdn.example.test/api/v1/media/stream/foo/3',
    );
    expect(backendResourceUrl(null)).toBeNull();
    expect(backendUrl('https://cdn.example.test/x.mp4')).toBe('https://cdn.example.test/x.mp4');
  });
});
