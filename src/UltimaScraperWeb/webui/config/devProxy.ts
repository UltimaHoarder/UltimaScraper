import type { ProxyOptions } from 'vite'

type RuntimeEnvironment = Readonly<Record<string, string | undefined>>

const CLASSIFIER: Record<string, ProxyOptions> = {
  '/classifier-api': {
    target: 'http://127.0.0.1:8029',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/classifier-api/, '/api/v1'),
  },
}

export class MissingWebUIServer extends Error {
  constructor() {
    super(
      'The dev server needs the WebUI server: start UltimaScraper with main.py, ' +
        'or set USR_WEBUI_SERVER_URL to a running WebUI server (e.g. http://127.0.0.1:21120).',
    )
    this.name = 'MissingWebUIServer'
  }
}

function serverUrl(value: string | undefined): string | null {
  const url = value?.trim().replace(/\/+$/, '')
  return url && /^https?:\/\/[^/]+$/.test(url) ? url : null
}

/**
 * Sends sign-in, backend and socket traffic to the WebUI server at
 * USR_WEBUI_SERVER_URL (set by main.py), as in production. The page never
 * talks to a backend itself.
 */
export function resolveDevProxy(env: RuntimeEnvironment): Record<string, ProxyOptions> {
  const server = serverUrl(env.USR_WEBUI_SERVER_URL)
  if (!server) throw new MissingWebUIServer()
  // The Host header stays as the browser sent it: the server compares it with
  // Origin before accepting writes and sockets. X-Forwarded-For names the
  // browser, which the server trusts from this loopback proxy.
  const through: ProxyOptions = { target: server, changeOrigin: false, xfwd: true }
  return {
    '^/webui/api/': through,
    '^/b/[^/]+/(api|ws)(/|$)': { ...through, ws: true },
    // Routes to the default backend, kept from before /b/{connection}.
    '/api': through,
    '/ws': { ...through, ws: true },
    ...CLASSIFIER,
  }
}
