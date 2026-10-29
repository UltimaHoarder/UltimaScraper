import { describe, expect, it } from 'vitest';
import { parseBulkProxyText, parseProxyLine } from '../../src/features/network/lib/proxyParser';

describe('proxyParser', () => {
  it('parses standard http url with embedded credentials', () => {
    const result = parseProxyLine('http://anon:anon@203.0.113.10:6754');
    expect(result.url).toBe('http://203.0.113.10:6754');
    expect(result.username).toBe('anon');
    expect(result.password).toBe('anon');
    expect(result.group).toBeNull();
  });

  it('parses socks5 url with comment group', () => {
    const result = parseProxyLine('socks5://user:pass@127.0.0.1:1080 # Residential US');
    expect(result.url).toBe('socks5://127.0.0.1:1080');
    expect(result.username).toBe('user');
    expect(result.password).toBe('pass');
    expect(result.group).toBe('Residential US');
  });

  it('parses colon-separated host:port:user:pass with default group', () => {
    const result = parseProxyLine('203.0.113.20:6014:alice:secret', 'Datacenter');
    expect(result.url).toBe('http://203.0.113.20:6014');
    expect(result.username).toBe('alice');
    expect(result.password).toBe('secret');
    expect(result.group).toBe('Datacenter');
  });

  it('parses simple host:port format', () => {
    const result = parseProxyLine('203.0.113.30:6462');
    expect(result.url).toBe('http://203.0.113.30:6462');
    expect(result.username).toBeNull();
    expect(result.password).toBeNull();
  });

  it('parses bulk multiline text with comments and empty lines', () => {
    const text = `
      // Some comment
      http://anon:anon@203.0.113.10:6754
      http://anon:anon@203.0.113.20:6014 # Group B
      203.0.113.30:6462:john:doe
      invalid-line
    `;

    const parsed = parseBulkProxyText(text, 'DefaultGroup');
    expect(parsed).toHaveLength(4);

    expect(parsed[0].url).toBe('http://203.0.113.10:6754');
    expect(parsed[0].group).toBe('DefaultGroup');
    expect(parsed[0].error).toBeNull();

    expect(parsed[1].url).toBe('http://203.0.113.20:6014');
    expect(parsed[1].group).toBe('Group B');
    expect(parsed[1].error).toBeNull();

    expect(parsed[2].url).toBe('http://203.0.113.30:6462');
    expect(parsed[2].username).toBe('john');
    expect(parsed[2].group).toBe('DefaultGroup');
    expect(parsed[2].error).toBeNull();

    expect(parsed[3].error).toBeTruthy();
  });
});
