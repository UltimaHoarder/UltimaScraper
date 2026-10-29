import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { NetworkProxy } from '../../src/api/types/network';
import { ProxyCard } from '../../src/features/network/components/ProxyCard';

function renderProxyCard(proxy: NetworkProxy) {
  const onToggleEnabled = vi.fn();

  render(
    <ProxyCard
      proxy={proxy}
      isExpanded={false}
      isAuthsLoading={false}
      isAnalyzing={false}
      isStateChanging={false}
      onEdit={vi.fn()}
      onToggleExpanded={vi.fn()}
      onOpenAnalyzer={vi.fn()}
      onDelete={vi.fn()}
      onRemoveAuth={vi.fn()}
      onToggleEnabled={onToggleEnabled}
    />,
  );

  return { onToggleEnabled };
}

describe('ProxyCard', () => {
  it('enables a disabled proxy while keeping it visible', () => {
    const proxy: NetworkProxy = {
      id: 'http://disabled.example:8080',
      url: 'http://disabled.example:8080',
      username: null,
      enabled: false,
      max_connections: 8,
      assigned_auths: [42],
      active_assigned_count: 1,
    };
    const { onToggleEnabled } = renderProxyCard(proxy);

    expect(screen.getByText('Disabled', { selector: '.network-proxy__state' })).toBeVisible();
    expect(screen.getByText('1 assigned account')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: `Enable proxy ${proxy.url}` }));

    expect(onToggleEnabled).toHaveBeenCalledWith(proxy);
  });

  it('offers to disable an enabled proxy', () => {
    const proxy: NetworkProxy = {
      id: 'http://enabled.example:8080',
      url: 'http://enabled.example:8080',
      username: 'route-user',
      enabled: true,
      max_connections: -1,
      assigned_auths: [],
    };
    const { onToggleEnabled } = renderProxyCard(proxy);

    expect(screen.getByText('Idle', { selector: '.network-proxy__state' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: `Disable proxy ${proxy.url}` }));

    expect(onToggleEnabled).toHaveBeenCalledWith(proxy);
  });

  it('displays group badge and handles selection and reachability test', async () => {
    const onToggleSelect = vi.fn();
    const onTestReachability = vi.fn().mockResolvedValue({
      success: true,
      latency_ms: 120,
      message: 'Reachable',
    });

    const proxy: NetworkProxy = {
      id: 'http://grouped.example:8080',
      url: 'http://grouped.example:8080',
      username: 'route-user',
      group: 'Datacenter US',
      enabled: true,
      max_connections: 16,
      assigned_auths: [],
    };

    render(
      <ProxyCard
        proxy={proxy}
        isExpanded={false}
        isSelected={false}
        onToggleSelect={onToggleSelect}
        isAuthsLoading={false}
        isAnalyzing={false}
        isStateChanging={false}
        onEdit={vi.fn()}
        onToggleExpanded={vi.fn()}
        onOpenAnalyzer={vi.fn()}
        onDelete={vi.fn()}
        onRemoveAuth={vi.fn()}
        onToggleEnabled={vi.fn()}
        onTestReachability={onTestReachability}
      />,
    );

    expect(screen.getByText('Datacenter US')).toBeVisible();

    const checkbox = screen.getByRole('checkbox', { name: `Select proxy ${proxy.url}` });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(onToggleSelect).toHaveBeenCalledWith(proxy);

    const testBtn = screen.getByRole('button', { name: 'Test' });
    fireEvent.click(testBtn);
    expect(onTestReachability).toHaveBeenCalledWith(proxy);

    // After async test resolves
    expect(await screen.findByText('✓ 120ms')).toBeVisible();
  });

  it('displays external quickTestResult from bulk testing', () => {
    const proxy: NetworkProxy = {
      id: 'http://bulk-tested.example:8080',
      url: 'http://bulk-tested.example:8080',
      username: null,
      enabled: true,
      max_connections: 8,
      assigned_auths: [],
    };

    const { rerender } = render(
      <ProxyCard
        proxy={proxy}
        isExpanded={false}
        isAuthsLoading={false}
        isAnalyzing={false}
        isStateChanging={false}
        onEdit={vi.fn()}
        onToggleExpanded={vi.fn()}
        onOpenAnalyzer={vi.fn()}
        onDelete={vi.fn()}
        onRemoveAuth={vi.fn()}
        onToggleEnabled={vi.fn()}
        quickTestResult={{ testing: true }}
      />,
    );

    expect(screen.getByText('PROBING…')).toBeVisible();

    rerender(
      <ProxyCard
        proxy={proxy}
        isExpanded={false}
        isAuthsLoading={false}
        isAnalyzing={false}
        isStateChanging={false}
        onEdit={vi.fn()}
        onToggleExpanded={vi.fn()}
        onOpenAnalyzer={vi.fn()}
        onDelete={vi.fn()}
        onRemoveAuth={vi.fn()}
        onToggleEnabled={vi.fn()}
        quickTestResult={{ testing: false, success: true, latency_ms: 65, message: 'Reachable' }}
      />,
    );

    expect(screen.getByText('✓ 65ms')).toBeVisible();
  });
});
