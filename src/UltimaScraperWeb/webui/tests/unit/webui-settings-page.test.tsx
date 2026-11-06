import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderWithProviders } from './testUtils';
import { SettingsPage } from '../../src/themes/ultima-atlas/views/settings/SettingsPage';
import { SecuritySettingsSection } from '../../src/features/settings/components/SecuritySettingsSection';
import { ConnectionsSettingsSection } from '../../src/features/settings/components/ConnectionsSettingsSection';
import { AppearanceSettingsSection } from '../../src/features/settings/components/AppearanceSettingsSection';
import { AboutSettingsSection } from '../../src/features/settings/components/AboutSettingsSection';
import * as webuiApi from '../../src/api/webui';

vi.mock('../../src/app/bootstrap/AppBootstrapProvider', () => ({
  useAppBootstrap: () => ({
    bootstrap: {
      backend_id: 'alpha-test',
      version: '1.2.3',
      api_version: 1,
      setup: { is_configured: true },
    },
    isLoading: false,
    isFetching: false,
    failureCount: 0,
    error: null,
    statusText: 'Ready · alpha-test · v1.2.3',
    retryBootstrap: vi.fn(),
  }),
}));

vi.mock('../../src/api/webui', async () => {
  const actual = await vi.importActual<typeof webuiApi>('../../src/api/webui');
  return {
    ...actual,
    changeWebUIPassword: vi.fn().mockResolvedValue(undefined),
    revokeAllWebUISessions: vi.fn().mockResolvedValue(undefined),
    signOutOfWebUI: vi.fn().mockResolvedValue(undefined),
    listConnections: vi.fn().mockResolvedValue([
      {
        id: 'default',
        name: 'Default Node',
        base_url: 'http://127.0.0.1:8000',
        tls_verify: true,
        managed: true,
        has_token: true,
        trust_plugins: false,
      },
    ]),
    listClusters: vi.fn().mockResolvedValue({
      members: [],
      clusters: [],
    }),
    testConnection: vi.fn().mockResolvedValue({
      reachable: true,
      authenticated: true,
      message: 'OK',
      latency_ms: 12,
    }),
    addConnection: vi.fn().mockResolvedValue({
      id: 'new-conn',
      name: 'New Node',
      base_url: 'http://127.0.0.1:8001',
      tls_verify: true,
      managed: false,
      has_token: false,
      trust_plugins: false,
    }),
  };
});

describe('WebUI SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    (webuiApi.listConnections as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 'default',
        name: 'Default Node',
        base_url: 'http://127.0.0.1:8000',
        tls_verify: true,
        managed: true,
        has_token: true,
        trust_plugins: false,
      },
    ]);
    (webuiApi.listClusters as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      members: [],
      clusters: [],
    });
    (webuiApi.testConnection as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      reachable: true,
      authenticated: true,
      message: 'OK',
      latency_ms: 12,
    });
  });

  it('renders all four WebUI settings tabs', () => {
    renderWithProviders(<SettingsPage />);

    expect(screen.getByRole('button', { name: /Security & Access/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Fleet Connections/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Appearance & UI/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /About & Diagnostics/i })).toBeInTheDocument();
  });

  it('switches tabs when clicked', async () => {
    renderWithProviders(<SettingsPage />);

    // Default tab is security
    expect(screen.getByTestId('security-settings-section')).toBeInTheDocument();

    // Click Appearance
    fireEvent.click(screen.getByRole('button', { name: /Appearance & UI/i }));
    await waitFor(() => {
      expect(screen.getByTestId('appearance-settings-section')).toBeInTheDocument();
    });

    // Click Fleet Connections
    fireEvent.click(screen.getByRole('button', { name: /Fleet Connections/i }));
    await waitFor(() => {
      expect(screen.getByTestId('connections-settings-section')).toBeInTheDocument();
    });

    // Click About
    fireEvent.click(screen.getByRole('button', { name: /About & Diagnostics/i }));
    await waitFor(() => {
      expect(screen.getByTestId('about-settings-section')).toBeInTheDocument();
    });
  });

  it('validates password fields and submits password change', async () => {
    renderWithProviders(<SecuritySettingsSection />, { withRouter: false });

    const currentInput = screen.getByLabelText('Current Password');
    const newInput = screen.getByLabelText('New Password');
    const confirmInput = screen.getByLabelText('Confirm New Password');

    // Too short
    fireEvent.change(currentInput, { target: { value: 'oldpass' } });
    fireEvent.change(newInput, { target: { value: 'secret7' } });
    fireEvent.change(confirmInput, { target: { value: 'secret7' } });

    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(await screen.findByText('Use a new password of at least 8 characters.')).toBeInTheDocument();
    expect(webuiApi.changeWebUIPassword).not.toHaveBeenCalled();

    // Mismatched passwords
    fireEvent.change(newInput, { target: { value: 'new-secret-password' } });
    fireEvent.change(confirmInput, { target: { value: 'wrong-confirmation' } });

    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(await screen.findByText('New passwords do not match.')).toBeInTheDocument();
    expect(webuiApi.changeWebUIPassword).not.toHaveBeenCalled();

    // Matching passwords
    fireEvent.change(confirmInput, { target: { value: 'new-secret-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    await waitFor(() => {
      expect(webuiApi.changeWebUIPassword).toHaveBeenCalledWith('oldpass', 'new-secret-password');
      expect(screen.getByText(/Every other browser has been signed out/i)).toBeInTheDocument();
    });
  });

  it('toggles compact mode in appearance settings and updates preferences', async () => {
    renderWithProviders(<AppearanceSettingsSection />, { withRouter: false });

    const checkbox = screen.getByLabelText(/Enable High-Density Compact Mode/i) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);

    fireEvent.click(checkbox);
    expect(checkbox.checked).toBe(true);

    const stored = JSON.parse(localStorage.getItem('usr_webui_preferences') || '{}');
    expect(stored.compactMode).toBe(true);
  });

  it('allows resetting preferences in about settings', async () => {
    localStorage.setItem('usr_webui_preferences', JSON.stringify({ compactMode: true }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderWithProviders(<AboutSettingsSection />, { withRouter: false });

    fireEvent.click(screen.getByRole('button', { name: 'Reset UI Preferences' }));

    await waitFor(() => {
      expect(screen.getByText(/Preferences have been restored to defaults/i)).toBeInTheDocument();
    });
  });

  it('renders registered connections and tests connection status', async () => {
    renderWithProviders(<ConnectionsSettingsSection />);

    await waitFor(() => {
      expect(screen.getByText('Default Node')).toBeInTheDocument();
      expect(screen.getByText('http://127.0.0.1:8000')).toBeInTheDocument();
    });

    const testBtn = screen.getByRole('button', { name: 'Test' });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(webuiApi.testConnection).toHaveBeenCalledWith('default');
      expect(screen.getByText(/✓ Reachable/i)).toBeInTheDocument();
    });
  });

  it('adds a new backend connection from form', async () => {
    (webuiApi.addConnection as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'worker-beta',
      name: 'Worker Beta',
      base_url: 'http://192.168.1.100:8000',
      tls_verify: true,
      managed: false,
      has_token: false,
      trust_plugins: false,
    });

    renderWithProviders(<ConnectionsSettingsSection />);

    fireEvent.click(screen.getByRole('button', { name: '+ Connect a backend' }));

    fireEvent.change(screen.getByLabelText('Connection Name'), { target: { value: 'Worker Beta' } });
    fireEvent.change(screen.getByLabelText('Backend Base URL'), { target: { value: 'http://192.168.1.100:8000' } });

    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

    await waitFor(() => {
      expect(webuiApi.addConnection).toHaveBeenCalledWith({
        name: 'Worker Beta',
        base_url: 'http://192.168.1.100:8000',
        token: null,
        tls_verify: true,
      });
      expect(screen.getByText(/Connection "Worker Beta" successfully registered/i)).toBeInTheDocument();
    });
  });
});
