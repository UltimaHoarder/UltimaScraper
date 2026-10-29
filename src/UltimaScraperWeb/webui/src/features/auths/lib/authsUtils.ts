import type { AuthCredential } from '../../../api/types/auths';

export const AUTH_SORT_OPTIONS = [
  { value: 'created_at', label: 'Created' },
  { value: 'last_tested_at', label: 'Last Tested' },
  { value: 'username', label: 'Username' },
  { value: 'user_id', label: 'User ID' },
  { value: 'status', label: 'Status' },
  { value: 'site', label: 'Site' },
];

export type AuthStateFilter = '' | 'enabled' | 'disabled';

export interface RefreshSubscriptionTarget {
  site: string;
  authRecordId?: number;
  accountUserId?: number;
}

export type EmailNotificationPreference = '' | 'enabled' | 'disabled';
export type AuthImportTab = 'curl' | 'json';

export interface VerificationSession {
  auth: AuthCredential;
  requestKey: string;
}

export function matchesStateFilter(
  auth: AuthCredential,
  stateFilter: AuthStateFilter,
) {
  if (!stateFilter) {
    return true;
  }
  return stateFilter === 'enabled' ? auth.active : !auth.active;
}

export function isOnlyFansAuth(auth: AuthCredential) {
  return auth.site.toLowerCase() === 'onlyfans';
}

export function needsAgeVerification(auth: AuthCredential) {
  return (
    isOnlyFansAuth(auth) &&
    auth.age_verification_required === true &&
    auth.is_age_verified !== true
  );
}

export function parseEmailNotificationPreference(
  preference: EmailNotificationPreference,
): boolean | null {
  if (preference === 'enabled') {
    return true;
  }
  if (preference === 'disabled') {
    return false;
  }
  return null;
}

export interface ExtractedCookieValues {
  authId?: string;
  sess?: string;
  authUid?: string;
}

export function extractCookieValues(
  cookie: string | null | undefined,
): ExtractedCookieValues {
  if (!cookie || typeof cookie !== 'string') return {};
  const res: ExtractedCookieValues = {};

  const authIdMatch = /(?:^|;\s*)auth_id=([^;]+)/i.exec(cookie);
  if (authIdMatch && authIdMatch[1].trim()) {
    res.authId = authIdMatch[1].trim();
  }

  const sessMatch = /(?:^|;\s*)sess=([^;]+)/i.exec(cookie);
  if (sessMatch && sessMatch[1].trim()) {
    res.sess = sessMatch[1].trim();
  }

  const fanslySessMatch = /(?:^|;\s*)session_active_session=([^;]+)/i.exec(cookie);
  if (fanslySessMatch && fanslySessMatch[1].trim()) {
    res.sess = fanslySessMatch[1].trim();
  }

  const authUidMatch = /(?:^|;\s*)auth_uid(?:_([0-9]+))?=([^;]*)/i.exec(cookie);
  if (authUidMatch) {
    const val = authUidMatch[2].trim();
    const idInKey = authUidMatch[1];
    if (val) {
      res.authUid = val;
    } else if (idInKey) {
      res.authUid = idInKey;
    }
  }

  if (!res.authUid && res.authId) {
    res.authUid = res.authId;
  }

  return res;
}

function stripLeadingCommentsAndWhitespace(str: string): string {
  let i = 0;
  while (i < str.length) {
    if (/\s/.test(str[i])) {
      i++;
      continue;
    }
    if (str[i] === '#' || (str[i] === '/' && str[i + 1] === '/')) {
      while (i < str.length && str[i] !== '\n') {
        i++;
      }
      continue;
    }
    break;
  }
  return str.slice(i);
}

/** A value produced by `parsePythonOrJson` (JSON plus Python literals). */
export type ParsedValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | ParsedValue[]
  | ParsedObject;

export interface ParsedObject {
  [key: string]: ParsedValue;
}

export function parsePythonOrJson(input: string): ParsedValue {
  let i = 0;
  const str = input.trim();

  function skipWhitespace() {
    while (i < str.length) {
      if (/\s/.test(str[i])) {
        i++;
        continue;
      }
      if (str[i] === '#' || (str[i] === '/' && str[i + 1] === '/')) {
        while (i < str.length && str[i] !== '\n') {
          i++;
        }
        continue;
      }
      break;
    }
  }

  function parseValue(): ParsedValue {
    skipWhitespace();
    if (i >= str.length) throw new Error('Unexpected end of input');

    const char = str[i];
    if (char === '{') return parseObject();
    if (char === '[') return parseArray();
    if (char === '"' || char === "'") return parseString();
    if (char === '-' || char === '+' || (char >= '0' && char <= '9')) return parseNumber();

    return parseIdentifier();
  }

  function parseString(): string {
    const quote = str[i];
    i++;
    let result = '';
    while (i < str.length) {
      const char = str[i];
      if (char === '\\') {
        i++;
        if (i >= str.length) throw new Error('Unterminated string escape');
        const next = str[i];
        if (next === quote) {
          result += quote;
        } else if (next === 'n') {
          result += '\n';
        } else if (next === 'r') {
          result += '\r';
        } else if (next === 't') {
          result += '\t';
        } else if (next === '\\') {
          result += '\\';
        } else {
          result += next;
        }
        i++;
      } else if (char === quote) {
        i++;
        return result;
      } else {
        result += char;
        i++;
      }
    }
    throw new Error('Unterminated string');
  }

  function parseNumber(): number {
    const start = i;
    if (str[i] === '-' || str[i] === '+') i++;
    while (i < str.length && /[0-9.]/.test(str[i])) i++;
    const numStr = str.slice(start, i);
    const num = Number(numStr);
    if (isNaN(num)) throw new Error(`Invalid number: ${numStr}`);
    return num;
  }

  function parseIdentifier(): boolean | null | undefined {
    const start = i;
    while (i < str.length && /[a-zA-Z0-9_$]/.test(str[i])) i++;
    const ident = str.slice(start, i);
    if (ident === 'None' || ident === 'null') return null;
    if (ident === 'True' || ident === 'true') return true;
    if (ident === 'False' || ident === 'false') return false;
    if (ident === 'undefined') return undefined;
    throw new Error(`Unexpected identifier: ${ident}`);
  }

  function parseObject(): ParsedObject {
    i++;
    const obj: ParsedObject = {};
    skipWhitespace();
    if (i < str.length && str[i] === '}') {
      i++;
      return obj;
    }

    while (i < str.length) {
      skipWhitespace();
      if (i >= str.length) throw new Error('Unterminated object');
      let key: string;
      if (str[i] === '"' || str[i] === "'") {
        key = parseString();
      } else {
        const start = i;
        while (i < str.length && /[a-zA-Z0-9_$-]/.test(str[i])) i++;
        key = str.slice(start, i);
        if (!key) throw new Error('Expected object key');
      }

      skipWhitespace();
      if (i >= str.length || str[i] !== ':') throw new Error(`Expected ':' after key "${key}"`);
      i++;

      const value = parseValue();
      obj[key] = value;

      skipWhitespace();
      if (i < str.length && str[i] === ',') {
        i++;
        skipWhitespace();
        if (i < str.length && str[i] === '}') {
          i++;
          return obj;
        }
      } else if (i < str.length && str[i] === '}') {
        i++;
        return obj;
      } else {
        throw new Error("Expected ',' or '}' in object");
      }
    }
    throw new Error('Unterminated object');
  }

  function parseArray(): ParsedValue[] {
    i++;
    const arr: ParsedValue[] = [];
    skipWhitespace();
    if (i < str.length && str[i] === ']') {
      i++;
      return arr;
    }

    while (i < str.length) {
      arr.push(parseValue());
      skipWhitespace();
      if (i < str.length && str[i] === ',') {
        i++;
        skipWhitespace();
        if (i < str.length && str[i] === ']') {
          i++;
          return arr;
        }
      } else if (i < str.length && str[i] === ']') {
        i++;
        return arr;
      } else {
        throw new Error("Expected ',' or ']' in array");
      }
    }
    throw new Error('Unterminated array');
  }

  const result = parseValue();
  skipWhitespace();
  return result;
}

export function canNormalizeToAuthJson(value: string): boolean {
  const cleaned = stripLeadingCommentsAndWhitespace(value);
  if (!cleaned || cleaned.toLowerCase().startsWith('curl')) {
    return false;
  }
  if (!cleaned.startsWith('{')) {
    return false;
  }
  try {
    const parsed = parsePythonOrJson(value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return false;
    }
    const keys = Object.keys(parsed).map((k) => k.toLowerCase().replace(/-/g, '_'));
    const authKeys = [
      'cookie',
      'sess',
      'session',
      'auth_id',
      'auth_uid',
      'auth_uid_',
      'x_bc',
      'user_agent',
      'authorization',
      'app_token',
      'id',
      'user_id',
    ];
    return keys.some((k) => authKeys.includes(k));
  } catch {
    return false;
  }
}

export function normalizeToAuthJson(value: string): string {
  const cleaned = stripLeadingCommentsAndWhitespace(value);
  if (!cleaned || cleaned.toLowerCase().startsWith('curl')) {
    return value;
  }
  if (!cleaned.startsWith('{')) {
    return value;
  }

  let obj: ParsedValue;
  try {
    obj = parsePythonOrJson(value);
  } catch {
    return value;
  }

  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
    return value;
  }

  const cookie =
    typeof obj.cookie === 'string'
      ? obj.cookie.trim()
      : typeof obj.Cookie === 'string'
      ? obj.Cookie.trim()
      : undefined;
  const cookieVals = extractCookieValues(cookie);

  const authId =
    obj.auth_id !== undefined && obj.auth_id !== null && String(obj.auth_id).trim() !== ''
      ? String(obj.auth_id).trim()
      : obj.user_id !== undefined && obj.user_id !== null && String(obj.user_id).trim() !== ''
      ? String(obj.user_id).trim()
      : obj.id !== undefined && obj.id !== null && obj.id !== 0 && String(obj.id).trim() !== ''
      ? String(obj.id).trim()
      : cookieVals.authId;

  const sess =
    obj.sess !== undefined && obj.sess !== null && String(obj.sess).trim() !== ''
      ? String(obj.sess).trim()
      : obj.session !== undefined && obj.session !== null && String(obj.session).trim() !== ''
      ? String(obj.session).trim()
      : cookieVals.sess;

  const authUid =
    obj.auth_uid_ !== undefined && obj.auth_uid_ !== null && String(obj.auth_uid_).trim() !== ''
      ? String(obj.auth_uid_).trim()
      : obj.auth_uid !== undefined && obj.auth_uid !== null && String(obj.auth_uid).trim() !== ''
      ? String(obj.auth_uid).trim()
      : cookieVals.authUid || authId;

  const userAgent =
    obj.user_agent !== undefined && obj.user_agent !== null && String(obj.user_agent).trim() !== ''
      ? String(obj.user_agent).trim()
      : obj['user-agent'] !== undefined && obj['user-agent'] !== null && String(obj['user-agent']).trim() !== ''
      ? String(obj['user-agent']).trim()
      : obj.userAgent !== undefined && obj.userAgent !== null && String(obj.userAgent).trim() !== ''
      ? String(obj.userAgent).trim()
      : undefined;

  const xBc =
    obj.x_bc !== undefined && obj.x_bc !== null && String(obj.x_bc).trim() !== ''
      ? String(obj.x_bc).trim()
      : obj['x-bc'] !== undefined && obj['x-bc'] !== null && String(obj['x-bc']).trim() !== ''
      ? String(obj['x-bc']).trim()
      : obj.xBc !== undefined && obj.xBc !== null && String(obj.xBc).trim() !== ''
      ? String(obj.xBc).trim()
      : undefined;

  const appToken =
    obj['app-token'] !== undefined && obj['app-token'] !== null && String(obj['app-token']).trim() !== ''
      ? String(obj['app-token']).trim()
      : obj.app_token !== undefined && obj.app_token !== null && String(obj.app_token).trim() !== ''
      ? String(obj.app_token).trim()
      : obj.appToken !== undefined && obj.appToken !== null && String(obj.appToken).trim() !== ''
      ? String(obj.appToken).trim()
      : undefined;

  const authorization =
    obj.authorization !== undefined && obj.authorization !== null && String(obj.authorization).trim() !== ''
      ? String(obj.authorization).trim()
      : obj.Authorization !== undefined && obj.Authorization !== null && String(obj.Authorization).trim() !== ''
      ? String(obj.Authorization).trim()
      : undefined;

  const normalized: ParsedObject = {};
  if (authId) normalized.auth_id = authId;
  if (sess) normalized.sess = sess;
  if (authUid) normalized.auth_uid_ = authUid;
  if (userAgent) normalized.user_agent = userAgent;
  if (xBc) normalized.x_bc = xBc;
  if (appToken) normalized['app-token'] = appToken;
  if (authorization) normalized.authorization = authorization;
  if (cookie) normalized.cookie = cookie;

  for (const [k, v] of Object.entries(obj)) {
    const lowerKey = k.toLowerCase().replace(/-/g, '_');
    const handled = [
      'auth_id',
      'user_id',
      'id',
      'sess',
      'session',
      'auth_uid_',
      'auth_uid',
      'user_agent',
      'x_bc',
      'app_token',
      'authorization',
      'cookie',
    ];
    if (!handled.includes(lowerKey)) {
      if (v !== null && v !== undefined && v !== '') {
        normalized[k] = v;
      }
    }
  }

  return JSON.stringify(normalized, null, 2);
}

export function detectAuthImportType(value: string): AuthImportTab | null {
  const trimmed = value.trim();
  if (!trimmed.length) {
    return null;
  }
  if (trimmed.toLowerCase().startsWith('curl')) {
    return 'curl';
  }
  if (canNormalizeToAuthJson(trimmed) || trimmed.startsWith('{')) {
    return 'json';
  }
  return null;
}

export function isSupportedAuthImportInput(
  value: string,
  importTab: AuthImportTab,
) {
  const trimmedValue = value.trim();
  if (!trimmedValue.length) {
    return false;
  }
  if (importTab === 'curl') {
    return trimmedValue.toLowerCase().startsWith('curl');
  }
  return trimmedValue.startsWith('{') || canNormalizeToAuthJson(trimmedValue);
}

export function createVerificationRequestKey() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function formatAuthDate(dateStr: string | null) {
  if (!dateStr) {
    return 'Never';
  }
  try {
    return new Date(dateStr).toLocaleString();
  } catch {
    return dateStr;
  }
}

export function getSiteIcon(site: string) {
  switch (site.toLowerCase()) {
    case 'onlyfans':
      return '🔵';
    case 'fansly':
      return '💙';
    default:
      return '🌐';
  }
}

/** What a spender may buy, in words. */
export function spenderTypeLabel(spenderType: string | null) {
  switch (spenderType) {
    case 'free':
      return 'free only';
    case 'paid':
      return 'paid only';
    default:
      return 'any price';
  }
}
