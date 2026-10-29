import { describe, expect, it } from 'vitest';
import {
  canNormalizeToAuthJson,
  detectAuthImportType,
  extractCookieValues,
  isSupportedAuthImportInput,
  normalizeToAuthJson,
  parsePythonOrJson,
  type ParsedObject,
} from '../../src/features/auths/lib/authsUtils';

describe('authImportNormalizer', () => {
  const userInput = `{'id': None, 'username': '', 'cookie': 'auth_id=11111111; sess=fakesessiontoken0000000000; auth_hash=; auth_uniq_11111111=; auth_uid_11111111=; aws-waf-token=;', 'x_bc': '0000000000000000000000000000000000000000', 'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'email': '', 'password': '', 'hashed': False, 'support_2fa': True, 'active': True}`;

  it('extracts cookie values correctly', () => {
    const cookie =
      'auth_id=11111111; sess=fakesessiontoken0000000000; auth_hash=; auth_uniq_11111111=; auth_uid_11111111=; aws-waf-token=;';
    const values = extractCookieValues(cookie);
    expect(values.authId).toBe('11111111');
    expect(values.sess).toBe('fakesessiontoken0000000000');
    expect(values.authUid).toBe('11111111');
  });

  it('parses Python dictionary string with single quotes, None, and Booleans', () => {
    const parsed = parsePythonOrJson(userInput) as ParsedObject;
    expect(parsed.id).toBeNull();
    expect(parsed.username).toBe('');
    expect(parsed.hashed).toBe(false);
    expect(parsed.support_2fa).toBe(true);
    expect(parsed.active).toBe(true);
    expect(parsed.x_bc).toBe('0000000000000000000000000000000000000000');
    expect(parsed.user_agent).toContain('Mozilla/5.0');
    expect(parsed.cookie).toContain('auth_id=11111111');
  });

  it('detects user Python dict format as normalizable to auth JSON', () => {
    expect(canNormalizeToAuthJson(userInput)).toBe(true);
    expect(detectAuthImportType(userInput)).toBe('json');
    expect(isSupportedAuthImportInput(userInput, 'json')).toBe(true);
  });

  it('normalizes user Python dict format to valid Auth JSON schema', () => {
    const normalizedStr = normalizeToAuthJson(userInput);
    expect(() => JSON.parse(normalizedStr)).not.toThrow();

    const parsed = JSON.parse(normalizedStr);
    expect(parsed.auth_id).toBe('11111111');
    expect(parsed.sess).toBe('fakesessiontoken0000000000');
    expect(parsed.auth_uid_).toBe('11111111');
    expect(parsed.x_bc).toBe('0000000000000000000000000000000000000000');
    expect(parsed.user_agent).toBe(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    );
    expect(parsed.cookie).toBe(
      'auth_id=11111111; sess=fakesessiontoken0000000000; auth_hash=; auth_uniq_11111111=; auth_uid_11111111=; aws-waf-token=;',
    );
  });

  it('normalizes Fansly dictionary with authorization and user agent', () => {
    const fanslyInput = `{'authorization': 'test-auth-token-123', 'user_agent': 'Mozilla/5.0 Safari', 'cookie': 'session_active_session=sess_xyz;'}`;
    expect(canNormalizeToAuthJson(fanslyInput)).toBe(true);
    const normalized = JSON.parse(normalizeToAuthJson(fanslyInput));
    expect(normalized.authorization).toBe('test-auth-token-123');
    expect(normalized.user_agent).toBe('Mozilla/5.0 Safari');
    expect(normalized.sess).toBe('sess_xyz');
    expect(normalized.cookie).toBe('session_active_session=sess_xyz;');
  });

  it('handles standard JSON without breaking it', () => {
    const standardJson = JSON.stringify({
      sess: 'fakesessiontwo000000000000',
      auth_id: '222222222',
      auth_uid_: '222222222',
      user_agent: 'Mozilla/5.0',
      x_bc: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'app-token': '33d57ade8c02dbc5a333db99ff9ae26a',
    });
    expect(canNormalizeToAuthJson(standardJson)).toBe(true);
    const normalized = JSON.parse(normalizeToAuthJson(standardJson));
    expect(normalized.sess).toBe('fakesessiontwo000000000000');
    expect(normalized.auth_id).toBe('222222222');
    expect(normalized['app-token']).toBe('33d57ade8c02dbc5a333db99ff9ae26a');
  });

  it('ignores cURL commands and preserves them unchanged', () => {
    const curl = "curl 'https://onlyfans.com/api2/v2/init' -H 'cookie: sess=123;'";
    expect(canNormalizeToAuthJson(curl)).toBe(false);
    expect(detectAuthImportType(curl)).toBe('curl');
    expect(normalizeToAuthJson(curl)).toBe(curl);
  });

  it('handles Python comments and trailing commas gracefully', () => {
    const looseInput = `
      # exported account credentials
      {
        'auth_id': '555',
        'sess': 'sess_val',
        'x_bc': 'x_bc_val',
      }
    `;
    expect(canNormalizeToAuthJson(looseInput)).toBe(true);
    const normalized = JSON.parse(normalizeToAuthJson(looseInput));
    expect(normalized.auth_id).toBe('555');
    expect(normalized.sess).toBe('sess_val');
    expect(normalized.x_bc).toBe('x_bc_val');
  });
});
