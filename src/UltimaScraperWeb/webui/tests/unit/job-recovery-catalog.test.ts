import { describe, expect, it } from 'vitest';

import {
  countCategoryErrors,
  failedItemReasons,
  filterFailedItemsByCategory,
} from '../../src/features/jobs/lib/jobRecoveryCatalog';

const breakdown = { url_expired: 3, no_url: 2, ip_mismatch: '4', mystery_failure: 5 };
const expired = { id: 'a', errors: [{ reason: 'url_expired' }] };
const unknown = { id: 'b', errors: [{ reason: 'mystery_failure' }, { note: 'no reason' }] };
const malformed = { id: 'c', errors: 'not a list' };

describe('job recovery catalog', () => {
  it('counts recorded errors per recovery category', () => {
    expect(countCategoryErrors(breakdown, 'all')).toBe(14);
    expect(countCategoryErrors(breakdown, 'url_expired')).toBe(5);
    expect(countCategoryErrors(breakdown, 'ip_mismatch')).toBe(4);
    expect(countCategoryErrors(breakdown, 'other')).toBe(5);
    expect(countCategoryErrors(breakdown, 'data_issues')).toBe(0);
  });

  it('filters failed items by their recorded reasons', () => {
    const items = [expired, unknown, malformed];
    expect(filterFailedItemsByCategory(items, 'all')).toBe(items);
    expect(filterFailedItemsByCategory(items, 'url_expired')).toEqual([expired]);
    expect(filterFailedItemsByCategory(items, 'other')).toEqual([unknown]);
    expect(failedItemReasons(unknown)).toEqual(['mystery_failure']);
    expect(failedItemReasons(malformed)).toEqual([]);
  });
});
