import { describe, expect, it } from 'vitest';

import { MissingWebUIServer, resolveDevProxy } from '../../config/devProxy';

const matches = (proxy: Record<string, unknown>, path: string) =>
  Object.keys(proxy).filter((key) => (key.startsWith('^') ? new RegExp(key).test(path) : path.startsWith(key)));

describe('dev server proxy', () => {
  it('has no way to the backend except through the WebUI server', () => {
    expect(() => resolveDevProxy({})).toThrow(MissingWebUIServer);
    expect(() => resolveDevProxy({ USR_WEBUI_SERVER_URL: 'nas:8080' })).toThrow(MissingWebUIServer);
  });

  it('sends backend and sign-in traffic through the WebUI server', () => {
    const proxy = resolveDevProxy({ USR_WEBUI_SERVER_URL: 'http://127.0.0.1:41234/' });

    for (const options of Object.values(proxy).filter((entry) => entry.target !== 'http://127.0.0.1:8029')) {
      // The server checks Origin against the Host the browser used, and learns
      // the browser's address from X-Forwarded-For.
      expect(options).toMatchObject({ target: 'http://127.0.0.1:41234', changeOrigin: false, xfwd: true });
    }
    expect(matches(proxy, '/webui/api/v1/session')).toEqual(['^/webui/api/']);
    expect(matches(proxy, '/b/nas/api/v1/jobs')).toEqual(['^/b/[^/]+/(api|ws)(/|$)']);
    expect(proxy['^/b/[^/]+/(api|ws)(/|$)'].ws).toBe(true);
    // App routes stay with Vite, which serves the dev build.
    expect(matches(proxy, '/b/nas/jobs')).toEqual([]);
    expect(matches(proxy, '/connections')).toEqual([]);
  });
});
