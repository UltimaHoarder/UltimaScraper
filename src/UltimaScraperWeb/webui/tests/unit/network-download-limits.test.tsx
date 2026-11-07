import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getSettings, updateSettings } from '../../src/api/settings';
import type { SettingsResponse } from '../../src/api/types/settings';
import { DownloadLimitsCard } from '../../src/features/network/components/DownloadLimitsCard';
import { parseDownloadLimits } from '../../src/features/network/lib/downloadLimits';
import { useNetworkDownloadLimits } from '../../src/features/network/hooks/useNetworkDownloadLimits';

vi.mock('../../src/api/settings', () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}));

const mockGetSettings = vi.mocked(getSettings);
const mockUpdateSettings = vi.mocked(updateSettings);

function settings(perDomain: number, version: number): SettingsResponse {
  return {
    config_version: version,
    network: {
      downloads: {
        max_concurrency: 64,
        per_domain_concurrency: perDomain,
        head_concurrency: 64,
        buffer_size_bytes: 10485760,
      },
    },
  } as unknown as SettingsResponse;
}

function Harness() {
  const limits = useNetworkDownloadLimits();
  return (
    <DownloadLimitsCard
      limits={limits.limits}
      isLoading={limits.isLoading}
      loadError={limits.loadError}
      isSaving={limits.isSaving}
      saveError={limits.saveError}
      onSave={limits.save}
    />
  );
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}

describe('parseDownloadLimits', () => {
  it('takes whole numbers of at least 1', () => {
    expect(
      parseDownloadLimits({ max_concurrency: '64', per_domain_concurrency: ' 16 ', head_concurrency: '8' }),
    ).toEqual({ max_concurrency: 64, per_domain_concurrency: 16, head_concurrency: 8 });
  });

  it.each(['0', '', '1.5', '-2', 'abc'])('refuses %j', (value) => {
    expect(
      parseDownloadLimits({ max_concurrency: '64', per_domain_concurrency: value, head_concurrency: '8' }),
    ).toBeNull();
  });
});

describe('DownloadLimitsCard', () => {
  beforeEach(() => {
    mockGetSettings.mockReset();
    mockUpdateSettings.mockReset();
  });

  it('saves only the network download limits, against the version it read', async () => {
    mockGetSettings.mockResolvedValue(settings(8, 130));
    mockUpdateSettings.mockResolvedValue(settings(16, 131));
    renderCard();

    const perDomain = await screen.findByLabelText(/Per-domain concurrency/);
    expect(perDomain).toHaveValue(8);
    const save = screen.getByRole('button', { name: 'Save limits' });
    expect(save).toBeDisabled();

    fireEvent.change(perDomain, { target: { value: '16' } });
    fireEvent.click(save);

    await waitFor(() => expect(mockUpdateSettings).toHaveBeenCalledTimes(1));
    expect(mockUpdateSettings).toHaveBeenCalledWith({
      network: {
        downloads: { max_concurrency: 64, per_domain_concurrency: 16, head_concurrency: 64 },
      },
      expected_version: 130,
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Saved.');
    expect(screen.getByLabelText(/Per-domain concurrency/)).toHaveValue(16);
    expect(screen.getByRole('button', { name: 'Save limits' })).toBeDisabled();
  });

  it('will not save a limit below 1', async () => {
    mockGetSettings.mockResolvedValue(settings(8, 130));
    renderCard();

    fireEvent.change(await screen.findByLabelText(/Per-domain concurrency/), { target: { value: '0' } });

    expect(screen.getByRole('button', { name: 'Save limits' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('at least 1');
  });

  it('shows why a save failed', async () => {
    mockGetSettings.mockResolvedValue(settings(8, 130));
    mockUpdateSettings.mockRejectedValue(new Error('Settings changed since you loaded them'));
    renderCard();

    fireEvent.change(await screen.findByLabelText(/Per-domain concurrency/), { target: { value: '16' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save limits' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Settings changed since you loaded them');
  });
});
