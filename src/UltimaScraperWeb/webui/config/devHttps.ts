import { readFileSync } from 'node:fs'

type RuntimeEnvironment = Readonly<Record<string, string | undefined>>

/**
 * HTTPS for the dev server, from the certificate main.py passes it
 * (USR_WEBUI_TLS_CERT_FILE and USR_WEBUI_TLS_KEY_FILE); plain HTTP without.
 */
export function resolveDevHttps(env: RuntimeEnvironment): { cert: Buffer; key: Buffer } | undefined {
  const cert = env.USR_WEBUI_TLS_CERT_FILE?.trim()
  const key = env.USR_WEBUI_TLS_KEY_FILE?.trim()
  if (!cert && !key) return undefined
  if (!cert || !key) {
    throw new Error('Set both USR_WEBUI_TLS_CERT_FILE and USR_WEBUI_TLS_KEY_FILE for HTTPS.')
  }
  return { cert: readFileSync(cert), key: readFileSync(key) }
}
