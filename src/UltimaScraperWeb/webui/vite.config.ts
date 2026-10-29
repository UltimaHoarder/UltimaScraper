import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolveDevHttps } from './config/devHttps'
import { resolveDevProxy } from './config/devProxy'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const remoteBind = (
    env.USR_ALLOW_REMOTE_BIND ||
    process.env.USR_ALLOW_REMOTE_BIND ||
    ''
  )
    .trim()
    .toLowerCase()
  const allowRemoteBind = ['1', 'true', 'yes', 'on'].includes(remoteBind)
  // Only the dev server proxies; a production build is served by the WebUI server.
  const proxy = command === 'serve'
    ? resolveDevProxy({ USR_WEBUI_SERVER_URL: env.USR_WEBUI_SERVER_URL || process.env.USR_WEBUI_SERVER_URL })
    : undefined
  const https = command === 'serve'
    ? resolveDevHttps({
      USR_WEBUI_TLS_CERT_FILE: env.USR_WEBUI_TLS_CERT_FILE || process.env.USR_WEBUI_TLS_CERT_FILE,
      USR_WEBUI_TLS_KEY_FILE: env.USR_WEBUI_TLS_KEY_FILE || process.env.USR_WEBUI_TLS_KEY_FILE,
    })
    : undefined

  return {
    plugins: [react()],
    // Prevents stale/linked dependency graphs from loading a second React copy
    // during Vite development.
    resolve: {
      dedupe: ['react', 'react-dom'],
    },
    server: {
      host: allowRemoteBind ? '0.0.0.0' : '127.0.0.1',
      port: 21120,
      // A taken port is an error, not a reason to open a second WebUI on 5174.
      strictPort: true,
      https,
      proxy,
    },
  }
})
