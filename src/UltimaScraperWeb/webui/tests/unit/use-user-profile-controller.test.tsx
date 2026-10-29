import type { ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeProvider } from '../../src/app/theme/ThemeProvider';
import { useUserProfileController } from '../../src/features/user-profile/hooks/useUserProfileController';
import type { DetailedUserResponse } from '../../src/api/types/users';
import { createTestQueryClient } from './testUtils';

const mockNavigate = vi.fn();
const mockSetSearchParams = vi.fn();

const mockCreateJob = vi.fn();
const mockSubmitDelegatedJob = vi.fn();
const mockBrowseUsers = vi.fn();
const mockResolveUserIdentifier = vi.fn();
const mockSearchUsernameDirectories = vi.fn();
const mockGetUserProfile = vi.fn();
const mockRefreshUserProfile = vi.fn();
const mockGetUserHistory = vi.fn();
const mockGetUserAliases = vi.fn();
const mockGetEligibleAuths = vi.fn();
const mockUpdateUser = vi.fn();
const mockBrowseContentLibrary = vi.fn();
const mockCreateOrderedPerformer = vi.fn();
const mockGetAuthList = vi.fn();
const mockGetSubscriptions = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useParams: () => ({ userId: '123' }),
    useSearchParams: () => [new URLSearchParams('site=onlyfans'), mockSetSearchParams],
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../../src/api/jobs', () => ({
  createJob: (...args: unknown[]) => mockCreateJob(...args),
}));

vi.mock('../../src/api/plugins', () => ({
  submitDelegatedJob: (...args: unknown[]) => mockSubmitDelegatedJob(...args),
}));

vi.mock('../../src/api/orders', () => ({
  createOrderedPerformer: (...args: unknown[]) => mockCreateOrderedPerformer(...args),
}));

vi.mock('../../src/api/auths', () => ({
  getAuthList: (...args: unknown[]) => mockGetAuthList(...args),
}));

vi.mock('../../src/api/content', () => ({
  browseContentLibrary: (...args: unknown[]) => mockBrowseContentLibrary(...args),
}));

vi.mock('../../src/api/subscriptions', () => ({
  getSubscriptions: (...args: unknown[]) => mockGetSubscriptions(...args),
}));

vi.mock('../../src/api/users', () => ({
  browseUsers: (...args: unknown[]) => mockBrowseUsers(...args),
  getEligibleAuths: (...args: unknown[]) => mockGetEligibleAuths(...args),
  getUserAliases: (...args: unknown[]) => mockGetUserAliases(...args),
  getUserHistory: (...args: unknown[]) => mockGetUserHistory(...args),
  getUserProfile: (...args: unknown[]) => mockGetUserProfile(...args),
  refreshUserProfile: (...args: unknown[]) => mockRefreshUserProfile(...args),
  resolveUserIdentifier: (...args: unknown[]) => mockResolveUserIdentifier(...args),
  searchUsernameDirectories: (...args: unknown[]) => mockSearchUsernameDirectories(...args),
  updateUser: (...args: unknown[]) => mockUpdateUser(...args),
}));

describe('useUserProfileController', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateJob.mockResolvedValue({ job_name: 'ignored' });
    mockSubmitDelegatedJob.mockResolvedValue({
      correlation_id: 'corr-1',
      plugin_id: 'usweb-remote',
      integration_id: 'usweb-remote',
      status: 'submitted',
      external_job_id: 'remote-job-1',
      http_status_code: 201,
      response_body: null,
      last_error: null,
      retry_count: 0,
      payload_hash: 'hash-1',
      message_id: null,
    });
    mockBrowseUsers.mockResolvedValue({ success: true, users: [] });
    mockResolveUserIdentifier.mockResolvedValue({
      success: true,
      status: 'resolved',
      user_id: 123,
      username: 'alice',
      candidates: [],
      total: 1,
      page: 1,
      page_size: 20,
    });
    mockSearchUsernameDirectories.mockResolvedValue({ success: true, directories: [] });
    mockGetUserProfile.mockResolvedValue({
      user: {
        user_id: 123,
        username: 'alice',
        site: 'onlyfans',
        name: 'Alice',
        description: 'Creator profile',
        avatar_url: null,
        header_url: null,
        socials: [],
        performer: true,
        favorite: false,
        is_active: true,
        post_count: 12,
        image_count: 40,
        video_count: 8,
        price: 10,
        media_count: 0,
        audio_count: 0,
        size: 2048,
        display_size: 2048,
        estimated_size: 4096,
        size_source: 'actual',
        statistics_bucket_date: '2026-03-08',
        archived_post_count: 0,
        favourited_count: 0,
        subscribers_count: 0,
        location: null,
        website: null,
        sex: null,
        gender: null,
        join_date: null,
        last_checked_at: null,
        downloaded_at: null,
        first_downloaded_at: null,
        created_at: null,
        subscription_expires_at: null,
        is_subscribed: false,
      },
    });
    mockRefreshUserProfile.mockResolvedValue({ accepted: true, is_refreshing: true });
    mockGetUserHistory.mockResolvedValue({ success: true, snapshots: [] });
    mockGetUserAliases.mockResolvedValue({ success: true, aliases: [] });
    mockGetEligibleAuths.mockResolvedValue({
      error: null,
      auths: [{ auth_id: 99, auth_username: 'auth-main', is_active: true }],
    });
    mockUpdateUser.mockResolvedValue({ success: true });
    mockBrowseContentLibrary.mockResolvedValue({ success: true, content: [], total: 0 });
    mockCreateOrderedPerformer.mockResolvedValue({ success: true });
    mockGetAuthList.mockResolvedValue({
      success: true,
      auths: [
        {
          id: 77,
          site: 'onlyfans',
          username: 'auth-main',
          user_id: 123,
          status: 'valid',
          active: true,
          last_tested_at: null,
          created_at: null,
          cookie_preview: null,
          has_authorization: true,
          user_agent_preview: null,
          proxy_id: null,
          worker_shard: null,
          is_age_verified: true,
          age_verification_required: false,
          spend: false,
          spender_type: null,
        },
      ],
      total: 1,
    });
    mockGetSubscriptions.mockResolvedValue({
      success: true,
      subscriptions: [
        {
          id: 1,
          user_id: 456,
          username: 'bob',
          name: 'Bob',
          description: null,
          sex: null,
          avatar_url: null,
          header_url: null,
          price: 10,
          post_count: 12,
          media_count: 30,
          image_count: 20,
          video_count: 10,
          is_active: true,
          expires_at: null,
          ignored: false,
          site: 'onlyfans',
        },
      ],
      total: 1,
    });
  });

  it('reloads aliases when a background profile refresh finishes', async () => {
    const queryClient = createTestQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useUserProfileController(), { wrapper });

    await waitFor(() => {
      expect(result.current.user?.username).toBe('alice');
      expect(mockGetUserAliases).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      queryClient.setQueryData<DetailedUserResponse>(
        ['user-profile', 123, 'onlyfans'],
        (current) => current ? { ...current, is_refreshing: true } : current,
      );
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    mockGetUserAliases.mockResolvedValue({
      success: true,
      aliases: [
        {
          id: 9,
          user_id: 123,
          username: 'alice-old',
          created_at: '2026-08-16T06:00:00Z',
          site: 'onlyfans',
        },
      ],
      total: 1,
    });

    await act(async () => {
      queryClient.setQueryData<DetailedUserResponse>(
        ['user-profile', 123, 'onlyfans'],
        (current) => current ? { ...current, is_refreshing: false } : current,
      );
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    await waitFor(() => {
      expect(mockGetUserAliases).toHaveBeenCalledTimes(2);
      expect(mockResolveUserIdentifier).toHaveBeenCalledTimes(2);
      expect(result.current.userAliases.map((alias) => alias.username)).toEqual(['alice-old']);
    });
  });

  it('keeps polling after an old process reports a stale error until another refresh commits', async () => {
    const queryClient = createTestQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    );
    const { result, unmount } = renderHook(() => useUserProfileController(), { wrapper });
    await waitFor(() => expect(result.current.user?.username).toBe('alice'));
    const saved = result.current.profileData!;
    try {
      vi.useFakeTimers();
      await act(async () => {
        queryClient.setQueryData(['user-profile', 123, 'onlyfans'], {
          ...saved,
          is_stale: true,
          is_refreshing: false,
          refresh_error: 'Worker lease expired; attempt budget exhausted',
        });
      });
      mockGetUserProfile.mockResolvedValue({
        ...saved,
        user: { ...saved.user!, name: 'Fresh profile' },
        is_stale: false,
        is_refreshing: false,
        refresh_error: null,
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_001);
      });
      expect(result.current.user?.name).toBe('Fresh profile');
      expect(result.current.profileData?.refresh_error).toBeNull();
      const calls = mockGetUserProfile.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(mockGetUserProfile).toHaveBeenCalledTimes(calls);
    } finally {
      unmount();
      queryClient.clear();
      vi.useRealTimers();
    }
  });

  it('delegates scrape workflow using eligible auth selection and sends only auth_id from the browser', async () => {
    const queryClient = createTestQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useUserProfileController(), { wrapper });

    await waitFor(() => {
      expect(result.current.user?.username).toBe('alice');
    });

    await act(async () => {
      await result.current.handleDelegateScrape();
    });

    await waitFor(() => {
      expect(mockGetEligibleAuths).toHaveBeenCalledWith(123, 'onlyfans');
      expect(mockSubmitDelegatedJob).toHaveBeenCalledTimes(1);
    });

    const [pluginId, request] = mockSubmitDelegatedJob.mock.calls[0];
    expect(pluginId).toBe('usweb-remote');
    expect(request.payload.auth_id).toBe(99);
    expect(request.payload).not.toHaveProperty('auth_bundle');
    expect(request.payload.origin).toEqual({
      source: 'user_profile',
      action: 'scrape_and_download',
    });
    expect(request.payload.tasks[0]).toMatchObject({
      kind: 'scrape',
      alias: 'scrape_posts',
      site_name: 'OnlyFans',
      user_id: 123,
      user_username: 'alice',
      content_type: 'Posts',
      rescrape_existing: true,
    });
    expect(request.payload.tasks[1]).toMatchObject({
      kind: 'download',
      alias: 'download_posts',
      depends_on_aliases: ['scrape_posts'],
      site_name: 'OnlyFans',
      user_id: 123,
      user_username: 'alice',
      content_type: 'Posts',
    });
  });

  it('loads auth-scoped subscriptions when the subscriptions tab is opened', async () => {
    const queryClient = createTestQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useUserProfileController(), { wrapper });

    await waitFor(() => {
      expect(result.current.user?.username).toBe('alice');
      expect(result.current.hasSubscriptionsTab).toBe(true);
    });

    await act(async () => {
      result.current.handleTabClick('subscriptions');
    });

    await waitFor(() => {
      expect(mockGetSubscriptions).toHaveBeenCalledWith(
        'onlyfans',
        undefined,
        true,
        77,
        100,
        0,
        'username',
        'asc',
        undefined,
      );
    });

    expect(result.current.selectedProfileAuth?.id).toBe(77);
    expect(result.current.profileSubscriptionsTotal).toBe(1);
  });

  it('searches directories automatically once the profile loads', async () => {
    const queryClient = createTestQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useUserProfileController(), { wrapper });

    await waitFor(() => {
      expect(result.current.user?.username).toBe('alice');
    });

    await waitFor(() => {
      expect(mockSearchUsernameDirectories).toHaveBeenCalledWith('alice', 'onlyfans', 123);
      expect(result.current.directoryLookupFetched).toBe(true);
    });
  });

  it('keeps confirmed size as the primary metric and exposes the larger estimate separately', async () => {
    const queryClient = createTestQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useUserProfileController(), { wrapper });

    await waitFor(() => {
      expect(result.current.user?.username).toBe('alice');
    });

    expect(result.current.confirmedProfileSize).toBe(2048);
    expect(result.current.estimatedProfileSize).toBe(4096);
    expect(result.current.resolvedProfileSize).toBe(2048);
    expect(result.current.showEstimatedProfileSize).toBe(true);
    expect(result.current.estimatedSizeMeta).toContain('2026-03-08');
  });
});
