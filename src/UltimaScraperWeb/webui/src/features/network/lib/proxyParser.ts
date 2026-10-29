export interface ParsedProxyLine {
  id: string;
  raw: string;
  url: string;
  username: string | null;
  password: string | null;
  group: string | null;
  error?: string | null;
}

export function parseProxyLine(
  line: string,
  defaultGroup?: string | null,
): { url: string; username: string | null; password: string | null; group: string | null } {
  let raw = line.trim();
  if (!raw) {
    throw new Error('Empty line');
  }

  let group = defaultGroup?.trim() || null;
  if (raw.includes('#')) {
    const [mainPart, commentPart] = raw.split('#', 2);
    raw = mainPart.trim();
    const commentGroup = commentPart?.trim();
    if (commentGroup) {
      group = commentGroup;
    }
  }

  if (!raw) {
    throw new Error('Empty line');
  }

  // If scheme present: http://user:pass@host:port
  if (raw.includes('://')) {
    try {
      const parsed = new URL(raw);
      const scheme = parsed.protocol.replace(':', '').toLowerCase();
      const host = parsed.hostname;
      const port = parsed.port;
      const username = parsed.username ? decodeURIComponent(parsed.username) : null;
      const password = parsed.password ? decodeURIComponent(parsed.password) : null;
      if (!host) {
        throw new Error(`Missing host in: ${raw}`);
      }
      const cleanUrl = port ? `${scheme}://${host}:${port}` : `${scheme}://${host}`;
      return { url: cleanUrl, username, password, group };
    } catch {
      // Fall through
    }
  }

  // If contains @: user:pass@host:port
  if (raw.includes('@')) {
    try {
      const parsed = new URL(`http://${raw}`);
      const host = parsed.hostname;
      const port = parsed.port;
      const username = parsed.username ? decodeURIComponent(parsed.username) : null;
      const password = parsed.password ? decodeURIComponent(parsed.password) : null;
      if (!host) {
        throw new Error(`Missing host in: ${raw}`);
      }
      const cleanUrl = port ? `http://${host}:${port}` : `http://${host}`;
      return { url: cleanUrl, username, password, group };
    } catch {
      // Fall through
    }
  }

  // If colon-separated: host:port:user:pass or host:port
  const parts = raw.split(':');
  if (parts.length === 4) {
    const [host, portStr, user, pass] = parts;
    const port = Number.parseInt(portStr, 10);
    if (Number.isNaN(port) || port <= 0 || port > 65535) {
      throw new Error(`Invalid port in: ${raw}`);
    }
    return {
      url: `http://${host}:${port}`,
      username: user || null,
      password: pass || null,
      group,
    };
  }

  if (parts.length === 2) {
    const [host, portStr] = parts;
    const port = Number.parseInt(portStr, 10);
    if (Number.isNaN(port) || port <= 0 || port > 65535) {
      throw new Error(`Invalid port in: ${raw}`);
    }
    return {
      url: `http://${host}:${port}`,
      username: null,
      password: null,
      group,
    };
  }

  throw new Error(`Unrecognized proxy format: ${raw}`);
}

export function parseBulkProxyText(
  text: string,
  defaultGroup?: string | null,
): ParsedProxyLine[] {
  const lines = text.split('\n');
  const results: ParsedProxyLine[] = [];

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i].trim();
    if (!raw || raw.startsWith('//')) {
      continue;
    }
    try {
      const parsed = parseProxyLine(raw, defaultGroup);
      results.push({
        id: `proxy-import-${i}-${parsed.url}`,
        raw,
        url: parsed.url,
        username: parsed.username,
        password: parsed.password,
        group: parsed.group,
        error: null,
      });
    } catch (err) {
      results.push({
        id: `proxy-import-${i}-err`,
        raw,
        url: raw,
        username: null,
        password: null,
        group: defaultGroup?.trim() || null,
        error: err instanceof Error ? err.message : 'Invalid proxy format',
      });
    }
  }

  return results;
}

export function formatProxyForText(proxy: {
  url: string;
  username?: string | null;
  group?: string | null;
}): string {
  let line = proxy.url;
  if (proxy.username) {
    try {
      const parsed = new URL(proxy.url);
      line = `${parsed.protocol}//${encodeURIComponent(proxy.username)}@${parsed.host}`;
    } catch {
      line = `${proxy.username}@${proxy.url}`;
    }
  }
  if (proxy.group) {
    line = `${line} # ${proxy.group}`;
  }
  return line;
}
