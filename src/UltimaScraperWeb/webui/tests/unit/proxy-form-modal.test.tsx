import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { NetworkProxy } from '../../src/api/types/network';
import { ProxyFormModal } from '../../src/features/network/components/ProxyFormModal';

describe('ProxyFormModal', () => {
  const dummyProxy: NetworkProxy = {
    id: 'http://62.105.205.21:5165',
    url: 'http://62.105.205.21:5165',
    username: 'user',
    max_connections: 16,
    assigned_auths: [],
    guest_lookup_timeout: 8.5,
  };

  it('renders guest lookup timeout field with current value when editing proxy', () => {
    const onTimeoutChange = vi.fn();
    render(
      <ProxyFormModal
        isOpen={true}
        editingProxy={dummyProxy}
        proxyUrl={dummyProxy.url}
        username="user"
        password=""
        group=""
        maxConnections={16}
        guestLookupTimeout={8.5}
        formError={null}
        testStatus="idle"
        testMessage={null}
        testLatencyMs={null}
        isTesting={false}
        isSaving={false}
        onClose={vi.fn()}
        onProxyUrlChange={vi.fn()}
        onUsernameChange={vi.fn()}
        onPasswordChange={vi.fn()}
        onGroupChange={vi.fn()}
        onMaxConnectionsChange={vi.fn()}
        onGuestLookupTimeoutChange={onTimeoutChange}
        onTest={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    const input = screen.getByLabelText(/Guest Lookup Timeout/i);
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue(8.5);

    fireEvent.change(input, { target: { value: '6.0' } });
    expect(onTimeoutChange).toHaveBeenCalledWith(6.0);

    fireEvent.change(input, { target: { value: '' } });
    expect(onTimeoutChange).toHaveBeenCalledWith(null);
  });

  it('renders empty guest lookup timeout field with hint when adding new proxy', () => {
    render(
      <ProxyFormModal
        isOpen={true}
        editingProxy={null}
        proxyUrl="http://new-proxy:8080"
        username=""
        password=""
        group=""
        maxConnections={-1}
        guestLookupTimeout={null}
        formError={null}
        testStatus="idle"
        testMessage={null}
        testLatencyMs={null}
        isTesting={false}
        isSaving={false}
        onClose={vi.fn()}
        onProxyUrlChange={vi.fn()}
        onUsernameChange={vi.fn()}
        onPasswordChange={vi.fn()}
        onGroupChange={vi.fn()}
        onMaxConnectionsChange={vi.fn()}
        onGuestLookupTimeoutChange={vi.fn()}
        onTest={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    const input = screen.getByLabelText(/Guest Lookup Timeout/i);
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue(null);
    expect(screen.getByText(/Override guest profile lookup timeout for this proxy/i)).toBeInTheDocument();
  });
});
