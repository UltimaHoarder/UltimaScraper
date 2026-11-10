import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getAuthList } from '../../src/api/auths';
import { useAuthsPageController } from '../../src/features/auths/hooks/useAuthsPageController';
import type { AuthStateFilter } from '../../src/features/auths/lib/authsUtils';

vi.mock('../../src/api/auths', () => ({
  deleteAuth: vi.fn(),
  getAuthList: vi.fn(),
  testAuth: vi.fn(),
  toggleAuthStatus: vi.fn(),
  updateAuth: vi.fn(),
}));

const mockGetAuthList = vi.mocked(getAuthList);

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('auths page Active filter', () => {
  beforeEach(() => {
    mockGetAuthList.mockReset();
    mockGetAuthList.mockResolvedValue({ success: true, total: 0, auths: [] } as unknown as Awaited<
      ReturnType<typeof getAuthList>
    >);
  });

  it.each<[AuthStateFilter, boolean]>([
    ['enabled', true],
    // The API defaults to active auths only; "All Auths" must ask for the rest.
    ['', false],
    ['disabled', false],
  ])('%j asks the API for active_only=%s', async (filter, activeOnly) => {
    const { result } = renderHook(() => useAuthsPageController(), { wrapper });
    act(() => result.current.setStateFilter(filter));

    await waitFor(() =>
      expect(mockGetAuthList.mock.calls.some((call) => call[1] === activeOnly)).toBe(true),
    );
    expect(mockGetAuthList.mock.lastCall?.[1]).toBe(activeOnly);
  });
});
