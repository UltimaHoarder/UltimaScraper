import { describe, expect, it } from 'vitest';

import { formatBytes } from '../../src/shared/lib/format';
import { formatBytes as formatSystemBytes } from '../../src/features/system/lib/systemUtils';
import { stripHtml } from '../../src/utils/sanitize';

describe('formatBytes', () => {
  it('uses binary units with configurable precision', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(1536, 2)).toBe('1.50 KB');
    expect(formatSystemBytes(2048)).toBe('2.00 KB');
  });

  it('keeps fractional and very large values on a known unit', () => {
    expect(formatBytes(0.4)).toBe('0 B');
    expect(formatBytes(1024 ** 7)).toBe('1048576.0 PB');
    expect(formatBytes(-2048)).toBe('-2.0 KB');
    expect(formatBytes(Number.NaN)).toBe('0 B');
  });
});

describe('stripHtml', () => {
  it('returns decoded plain text and tolerates empty input', () => {
    expect(stripHtml('<p>Hello <b>there</b> &amp; welcome</p>')).toBe('Hello there & welcome');
    expect(stripHtml(null)).toBe('');
    expect(stripHtml(undefined)).toBe('');
  });

  it('drops script and style content instead of surfacing it as text', () => {
    expect(stripHtml('<style>.x{color:red}</style>Bio<script>alert(1)</script>')).toBe('Bio');
  });
});
