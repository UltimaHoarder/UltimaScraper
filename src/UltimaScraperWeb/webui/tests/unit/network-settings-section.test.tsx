import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { NetworkSettingsSection } from '../../src/features/settings/components/NetworkSettingsSection';
import type { SettingsResponse } from '../../src/api/types/settings';
import { renderWithProviders } from './testUtils';

const settings = {
  network: {
    guest_session_pool: true,
    guest_route_rate_limit: 35,
    guest_lookup_timeout: 3.5,
    downloads: {
      max_concurrency: 64,
      per_domain_concurrency: 8,
      head_concurrency: 64,
      buffer_size_bytes: 10485760,
    },
  },
} as unknown as SettingsResponse;

describe('NetworkSettingsSection', () => {
  it('renders guest lookup timeout input and calls onNestedChange on valid update', () => {
    const onNestedChange = vi.fn();
    const onDeepNestedChange = vi.fn();

    renderWithProviders(
      <NetworkSettingsSection
        settings={settings}
        getNestedValue={() => undefined}
        getDeepNestedValue={() => undefined}
        onNestedChange={onNestedChange}
        onDeepNestedChange={onDeepNestedChange}
      />,
      { withRouter: false },
    );

    const input = screen.getByLabelText('Guest Lookup Timeout (seconds)') as HTMLInputElement;
    expect(input).toBeDefined();
    expect(input.value).toBe('3.5');

    fireEvent.change(input, { target: { value: '6.5' } });

    expect(onNestedChange).toHaveBeenCalledWith('network', 'guest_lookup_timeout', 6.5);
  });

  it('allows clearing input during typing and resets to 3.5 on blur if invalid or below 0.5', () => {
    const onNestedChange = vi.fn();
    const onDeepNestedChange = vi.fn();

    renderWithProviders(
      <NetworkSettingsSection
        settings={settings}
        getNestedValue={() => undefined}
        getDeepNestedValue={() => undefined}
        onNestedChange={onNestedChange}
        onDeepNestedChange={onDeepNestedChange}
      />,
      { withRouter: false },
    );

    const input = screen.getByLabelText('Guest Lookup Timeout (seconds)') as HTMLInputElement;

    fireEvent.change(input, { target: { value: '' } });
    expect(onNestedChange).toHaveBeenCalledWith('network', 'guest_lookup_timeout', '');

    fireEvent.blur(input, { target: { value: '' } });
    expect(onNestedChange).toHaveBeenCalledWith('network', 'guest_lookup_timeout', 3.5);

    fireEvent.blur(input, { target: { value: '0.2' } });
    expect(onNestedChange).toHaveBeenCalledWith('network', 'guest_lookup_timeout', 3.5);
  });
});
