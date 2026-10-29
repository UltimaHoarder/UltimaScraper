import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { BulkEditConnectionsModal } from '../../src/features/network/components/BulkEditConnectionsModal';
import type { NetworkProxy } from '../../src/api/types/network';

const mockProxies: NetworkProxy[] = [
  {
    id: 'http://1.1.1.1:8080',
    url: 'http://1.1.1.1:8080',
    username: null,
    enabled: true,
    max_connections: 8,
    assigned_auths: [1],
  },
  {
    id: 'http://2.2.2.2:8080',
    url: 'http://2.2.2.2:8080',
    username: null,
    enabled: true,
    max_connections: 16,
    assigned_auths: [],
  },
  {
    id: 'http://3.3.3.3:8080',
    url: 'http://3.3.3.3:8080',
    username: null,
    enabled: false,
    max_connections: -1,
    assigned_auths: [],
  },
];

describe('BulkEditConnectionsModal', () => {
  it('does not render when closed', () => {
    const onClose = vi.fn();
    const onSave = vi.fn();

    render(
      <BulkEditConnectionsModal
        isOpen={false}
        selectedProxyUrls={['http://1.1.1.1:8080']}
        proxies={mockProxies}
        isSaving={false}
        onClose={onClose}
        onSave={onSave}
      />,
    );

    expect(screen.queryByText(/Bulk Capacity Edit/i)).toBeNull();
  });

  it('renders correctly with selected proxies and preview', () => {
    const onClose = vi.fn();
    const onSave = vi.fn();

    render(
      <BulkEditConnectionsModal
        isOpen={true}
        selectedProxyUrls={['http://1.1.1.1:8080', 'http://2.2.2.2:8080']}
        proxies={mockProxies}
        isSaving={false}
        onClose={onClose}
        onSave={onSave}
      />,
    );

    expect(screen.getByText(/Edit Connections — 2 Proxies/i)).toBeVisible();
    expect(screen.getByText('http://1.1.1.1:8080')).toBeVisible();
    expect(screen.getByText('http://2.2.2.2:8080')).toBeVisible();
  });

  it('allows editing max_connections and calls onSave', () => {
    const onClose = vi.fn();
    const onSave = vi.fn();

    render(
      <BulkEditConnectionsModal
        isOpen={true}
        selectedProxyUrls={['http://1.1.1.1:8080', 'http://2.2.2.2:8080']}
        proxies={mockProxies}
        isSaving={false}
        onClose={onClose}
        onSave={onSave}
      />,
    );

    const connectionsInput = screen.getByPlaceholderText(/Mixed values/i);
    fireEvent.change(connectionsInput, { target: { value: '32' } });

    const applyButton = screen.getByRole('button', { name: /Apply to 2 Proxies/i });
    expect(applyButton).toBeEnabled();
    fireEvent.click(applyButton);

    expect(onSave).toHaveBeenCalledWith({
      max_connections: 32,
    });
  });

  it('allows editing max_concurrency when enabled', () => {
    const onClose = vi.fn();
    const onSave = vi.fn();

    render(
      <BulkEditConnectionsModal
        isOpen={true}
        selectedProxyUrls={['http://1.1.1.1:8080']}
        proxies={mockProxies}
        isSaving={false}
        onClose={onClose}
        onSave={onSave}
      />,
    );

    // Enable max concurrency
    const concurrencyCheckbox = screen.getByLabelText(/Max Concurrency/i);
    fireEvent.click(concurrencyCheckbox);

    const concurrencyInput = screen.getByPlaceholderText(/e\.g\. 32/i);
    fireEvent.change(concurrencyInput, { target: { value: '64' } });

    const applyButton = screen.getByRole('button', { name: /Apply to 1 Proxy/i });
    fireEvent.click(applyButton);

    expect(onSave).toHaveBeenCalledWith({
      max_concurrency: 64,
    });
  });
});
