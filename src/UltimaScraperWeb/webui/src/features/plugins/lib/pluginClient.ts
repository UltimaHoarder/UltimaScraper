import { createHttpClient, getActiveConnectionId, getApiBaseUrl } from '../../../api/http';
import type { PluginTransport } from './pluginHost';

const admin = createHttpClient();
// Keyed by backend and plugin: two backends can have plugins with one id.
const tokens = new Map<string, { token: string; expires: number }>();
const pendingTokens = new Map<string, Promise<string>>();
const tokenKey = (pluginId: string) => `${getActiveConnectionId() ?? ''}\u0000${pluginId}`;

async function tokenFor(pluginId: string): Promise<string> {
  const key = tokenKey(pluginId);
  const cached = tokens.get(key);
  if (cached && cached.expires > Date.now()) return cached.token;
  const pending = pendingTokens.get(key);
  if (pending) return pending;
  const request = admin.post<{ token: string; expires_in: number }>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/token`,
  ).then(({ data }) => {
    tokens.set(key, { token: data.token, expires: Date.now() + (data.expires_in - 30) * 1000 });
    return data.token;
  }).finally(() => pendingTokens.delete(key));
  pendingTokens.set(key, request);
  return request;
}

/** Forgets the plugin's token on every backend; it runs as the page leaves one. */
export function forgetPluginToken(pluginId: string): void {
  for (const key of [...tokens.keys()]) if (key.endsWith(`\u0000${pluginId}`)) tokens.delete(key);
}

export const pluginTransport: PluginTransport = async (pluginId, operation, taskType, payload, signal) => {
  const token = await tokenFor(pluginId);
  signal.throwIfAborted();
  const response = await fetch(`${getApiBaseUrl().replace(/\/$/, '')}/api/v1/plugins/runtime/${operation}`, {
    method: 'POST', signal, credentials: 'omit',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ task_type: taskType, payload }),
  });
  if (!response.ok) {
    if (response.status === 401) forgetPluginToken(pluginId);
    const body = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Plugin operation failed (${response.status}).`);
  }
  return response.json();
};
