/**
 * Connection ticket parser and generator for the WebUI.
 */

export interface ConnectionTicketPayload {
  name: string;
  base_url: string;
  token: string | null;
  tls_verify: boolean;
  cluster_id?: string | null;
}

/**
 * Parses a ticket string into connection fields.
 * Supports:
 * - usr://ticket/<urlsafe_base64_json>
 * - usr_ticket_<urlsafe_base64_json>
 * - raw base64 JSON
 * - usr://[token@]host[:port][?name=...&tls=...]
 */
export function parseTicketString(input: string): ConnectionTicketPayload | null {
  const cleaned = input.trim();
  if (!cleaned) return null;

  // 1. usr://ticket/...
  if (cleaned.startsWith('usr://ticket/')) {
    return decodeBase64Payload(cleaned.slice('usr://ticket/'.length));
  }

  // 2. usr_ticket_...
  if (cleaned.startsWith('usr_ticket_')) {
    return decodeBase64Payload(cleaned.slice('usr_ticket_'.length));
  }

  // 3. usr://[token@]host[:port] URI
  if (cleaned.startsWith('usr://')) {
    try {
      const url = new URL(cleaned);
      const token = url.username || url.password || null;
      const port = url.port ? `:${url.port}` : '';
      const tlsParam = (url.searchParams.get('tls') ?? url.searchParams.get('tls_verify') ?? '').toLowerCase();
      const isHttps = tlsParam === '1' || tlsParam === 'true' || url.port === '443';
      const scheme = isHttps ? 'https' : 'http';
      const hostname = url.hostname;
      if (!hostname) return null;

      const path = url.pathname === '/' ? '' : url.pathname;
      return {
        name: url.searchParams.get('name') || 'Backend',
        base_url: `${scheme}://${hostname}${port}${path}`.replace(/\/$/, ''),
        token,
        tls_verify: tlsParam !== '0' && tlsParam !== 'false',
        cluster_id: url.searchParams.get('cluster_id') || undefined,
      };
    } catch {
      return null;
    }
  }

  // 4. Try as raw base64
  return decodeBase64Payload(cleaned);
}

function decodeBase64Payload(b64Part: string): ConnectionTicketPayload | null {
  const trimmed = b64Part.trim().replace(/\/$/, '');
  if (!trimmed) return null;

  try {
    let standard = trimmed.replace(/-/g, '+').replace(/_/g, '/');
    while (standard.length % 4 !== 0) {
      standard += '=';
    }
    const decoded = atob(standard);
    const data = JSON.parse(decoded);
    if (!data || typeof data !== 'object') return null;

    const baseUrl = data.base_url || data.url;
    if (!baseUrl || typeof baseUrl !== 'string') return null;

    return {
      name: String(data.name || 'Backend').trim(),
      base_url: String(baseUrl).trim().replace(/\/$/, ''),
      token: data.token ? String(data.token).trim() : null,
      tls_verify: data.tls_verify !== false,
      cluster_id: data.cluster_id ? String(data.cluster_id).trim() : undefined,
    };
  } catch {
    return null;
  }
}
