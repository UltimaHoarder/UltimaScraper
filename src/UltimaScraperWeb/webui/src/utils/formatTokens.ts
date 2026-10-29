export interface FormatToken {
  token: string;
  description: string;
}

// Tokens that identify the performer folder; alt formats only match on these.
const PERFORMER_TOKENS: FormatToken[] = [
  { token: 'site_name', description: 'Site folder name, e.g. OnlyFans' },
  { token: 'user_username', description: 'Creator username' },
  { token: 'user_id', description: 'Creator ID' },
  { token: 'first_username_letter', description: 'First letter of the username, uppercased' },
  { token: 'first_id_digit', description: 'First digit of the creator ID' },
];

const CONTENT_TOKENS: FormatToken[] = [
  { token: 'authed_username', description: 'Username of the account that downloaded it' },
  {
    token: 'content_type',
    description: 'Posts, Messages, Stories… (archived posts become Archived/Posts in directories)',
  },
  { token: 'content_value', description: 'Free or Paid' },
  { token: 'content_id', description: 'Post or message ID' },
  { token: 'content_date', description: 'Post date, using the date format' },
  { token: 'media_type', description: 'Images, Videos, Audios…' },
  { token: 'media_id', description: 'Media ID' },
];

const FILE_TOKENS: FormatToken[] = [
  { token: 'content_text', description: 'Post text, cut to the max text length' },
  { token: 'media_filename', description: 'Original filename without its extension' },
  { token: 'media_ext', description: 'File extension' },
];

export const FORMAT_TOKENS = {
  directory: [...PERFORMER_TOKENS, ...CONTENT_TOKENS],
  altDirectory: PERFORMER_TOKENS,
  filename: [...PERFORMER_TOKENS, ...CONTENT_TOKENS, ...FILE_TOKENS],
} satisfies Record<string, FormatToken[]>;

export type FormatTokenField = keyof typeof FORMAT_TOKENS;

// Older names saved formats may still use; the backend still renders them.
const LEGACY_TOKENS = ['value', 'api_type', 'model_username', 'filename', 'ext', 'text', 'date', 'first_letter'];

const KNOWN_TOKENS = new Set([...FORMAT_TOKENS.filename.map(({ token }) => token), ...LEGACY_TOKENS]);

/** The {tokens} in a format the backend would reject, in order of appearance. */
export function invalidFormatTokens(template: string): string[] {
  const invalid: string[] = [];
  for (const [, token] of template.matchAll(/\{([^}]*)\}/g)) {
    if (!KNOWN_TOKENS.has(token) && !invalid.includes(token)) invalid.push(token);
  }
  return invalid;
}
