import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ManageAuthModal } from '../../src/features/auths/components/ManageAuthModal';
import type { AuthCredential } from '../../src/api/types/auths';
import { renderWithProviders } from './testUtils';

const mockParseCurl = vi.fn();
const mockParseAuthJson = vi.fn();
const mockListProxies = vi.fn();

vi.mock('../../src/api/auths', () => ({
  parseCurl: (...args: unknown[]) => mockParseCurl(...args),
  parseAuthJson: (...args: unknown[]) => mockParseAuthJson(...args),
}));

vi.mock('../../src/api/network', () => ({
  listProxies: (...args: unknown[]) => mockListProxies(...args),
}));

const sampleAuth: AuthCredential = {
  id: 42,
  site: 'privacy',
  user_id: 27699715,
  username: 'tester',
  active: true,
  status: 'invalid',
  proxy_id: null,
  spend: false,
  spender_type: 'all',
  cookie_preview: 'old_cookie',
  user_agent_preview: 'OldUA/1.0',
  has_authorization: false,
  created_at: null,
  updated_at: null,
} as unknown as AuthCredential;

describe('ManageAuthModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListProxies.mockResolvedValue([]);
  });

  it('parses and auto-applies cURL credentials on paste without an Apply Parsed Values button', async () => {
    const onSave = vi.fn();
    mockParseCurl.mockResolvedValue({
      success: true,
      site: 'privacy',
      cookie: 'sess=fresh_cookie_123',
      x_bc: null,
      authorization: null,
      user_agent: 'Mozilla/5.0 FreshUA',
      user_id: 27699715,
      app_token: null,
      sess: 'fresh_cookie_123',
      auth_id: '27699715',
      error: null,
      raw_headers: {},
    });

    renderWithProviders(
      <ManageAuthModal
        auth={sampleAuth}
        onClose={vi.fn()}
        onSave={onSave}
        isSaving={false}
        onTest={vi.fn()}
        onUpdateSubscriptions={vi.fn()}
        onScrapePaidContent={vi.fn()}
        onVerifyAge={vi.fn()}
        onVerifyIdentity={vi.fn()}
        isUpdatingSubscriptions={false}
        isScrapingPaidContent={false}
      />,
    );

    fireEvent.click(screen.getByRole('tab', { name: 'Refresh' }));
    const textarea = screen.getByLabelText('Paste cURL');

    const curlText = "curl 'https://privacy.com.br/api' -H 'cookie: sess=fresh_cookie_123' -H 'user-agent: Mozilla/5.0 FreshUA'";
    fireEvent.paste(textarea, {
      clipboardData: {
        getData: () => curlText,
      },
    });

    await waitFor(() => {
      expect(mockParseCurl).toHaveBeenCalledWith(curlText, 'privacy');
    });

    await waitFor(() => {
      expect(screen.getByText(/Parsed cookie, user agent/i)).toBeInTheDocument();
    });

    expect(screen.queryByRole('button', { name: /Apply Parsed Values/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    expect(onSave).toHaveBeenCalledWith({
      cookie: 'sess=fresh_cookie_123',
      user_agent: 'Mozilla/5.0 FreshUA',
    });
  });

  it('parses and auto-applies Auth JSON on paste and shows error on parse failure', async () => {
    const onSave = vi.fn();
    mockParseAuthJson.mockResolvedValue({
      success: false,
      site: 'privacy',
      cookie: null,
      x_bc: null,
      authorization: null,
      user_agent: null,
      user_id: null,
      app_token: null,
      sess: null,
      auth_id: null,
      error: 'Missing required cookie fields',
      raw_headers: {},
    });

    renderWithProviders(
      <ManageAuthModal
        auth={sampleAuth}
        onClose={vi.fn()}
        onSave={onSave}
        isSaving={false}
        onTest={vi.fn()}
        onUpdateSubscriptions={vi.fn()}
        onScrapePaidContent={vi.fn()}
        onVerifyAge={vi.fn()}
        onVerifyIdentity={vi.fn()}
        isUpdatingSubscriptions={false}
        isScrapingPaidContent={false}
      />,
    );

    fireEvent.click(screen.getByRole('tab', { name: 'Refresh' }));
    const textarea = screen.getByLabelText('Paste cURL');

    fireEvent.paste(textarea, {
      clipboardData: {
        getData: () => '{"sess": ""}',
      },
    });

    await waitFor(() => {
      expect(mockParseAuthJson).toHaveBeenCalled();
      expect(screen.getByText('Missing required cookie fields')).toBeInTheDocument();
    });

    expect(screen.queryByRole('button', { name: /Apply Parsed Values/i })).not.toBeInTheDocument();
  });
});
