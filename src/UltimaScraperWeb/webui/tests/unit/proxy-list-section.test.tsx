import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { NetworkProxy } from '../../src/api/types/network';
import { ProxyListSection } from '../../src/features/network/components/ProxyListSection';

const baseProxy: NetworkProxy = {
  id: 'http://proxy.example:8080',
  url: 'http://proxy.example:8080',
  username: null,
  enabled: true,
  max_connections: 8,
  assigned_auths: [],
};

function renderList(
  proxies: NetworkProxy[],
  selectedProxyIds = new Set<string>(),
  onAssignGroupSelected = vi.fn(),
  options: {
    onToggleSelectGroup?: (groupProxies: NetworkProxy[]) => void;
    onBulkEnableSelected?: (urls: string[]) => void;
    onBulkDisableSelected?: (urls: string[]) => void;
    onBulkEditSelected?: (urls: string[]) => void;
    onBulkDeleteSelected?: (urls: string[]) => void;
    onBulkTestSelected?: (urls: string[]) => void;
    isBulkTesting?: boolean;
    groupLookupTimeouts?: Record<string, number | null>;
    onSaveGroupLookupTimeout?: (group: string, timeout: number | null) => Promise<unknown>;
  } = {},
) {
  const onSelectGroupFilter = vi.fn();

  render(
    <ProxyListSection
      searchQuery=""
      onSearchQueryChange={vi.fn()}
      proxies={proxies}
      filteredProxies={proxies}
      totalAssigned={proxies.reduce((sum, proxy) => sum + proxy.assigned_auths.length, 0)}
      enabledCount={proxies.filter((proxy) => proxy.enabled !== false).length}
      disabledCount={0}
      unassignedCount={proxies.filter((proxy) => proxy.assigned_auths.length === 0).length}
      expandedProxyId={null}
      isProxyAuthsLoading={false}
      analyzerLoading={{}}
      analyzerErrors={{}}
      proxyStatePending={{}}
      proxyStateErrors={{}}
      onEditProxy={vi.fn()}
      onToggleExpandedProxy={vi.fn()}
      onOpenAnalyzer={vi.fn()}
      onDeleteProxy={vi.fn()}
      onRemoveAuth={vi.fn()}
      onToggleProxyEnabled={vi.fn()}
      existingGroups={['Datacenter US', 'Residential']}
      selectedGroupFilter={null}
      onSelectGroupFilter={onSelectGroupFilter}
      selectedProxyIds={selectedProxyIds}
      onAssignGroupSelected={onAssignGroupSelected}
      onToggleSelectGroup={options.onToggleSelectGroup}
      onBulkEnableSelected={options.onBulkEnableSelected}
      onBulkDisableSelected={options.onBulkDisableSelected}
      onBulkEditSelected={options.onBulkEditSelected}
      onBulkDeleteSelected={options.onBulkDeleteSelected}
      onBulkTestSelected={options.onBulkTestSelected}
      isBulkTesting={options.isBulkTesting}
      groupLookupTimeouts={options.groupLookupTimeouts}
      onSaveGroupLookupTimeout={options.onSaveGroupLookupTimeout}
    />,
  );

  return { onSelectGroupFilter };
}

describe('ProxyListSection', () => {
  it('renders configured proxies under their routing group headers', () => {
    const { onSelectGroupFilter } = renderList([
      { ...baseProxy, group: ' Datacenter US ' },
      { ...baseProxy, id: 'http://residential.example:8080', url: 'http://residential.example:8080', group: 'Residential' },
      { ...baseProxy, id: 'http://ungrouped.example:8080', url: 'http://ungrouped.example:8080' },
    ]);

    expect(screen.getByText('Datacenter US', { selector: 'strong' })).toBeVisible();
    expect(screen.getByText('Residential', { selector: 'strong' })).toBeVisible();
    expect(screen.getByText('Ungrouped routes', { selector: 'strong' })).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: /DATACENTER US 1/i }));
    expect(onSelectGroupFilter).toHaveBeenCalledWith('Datacenter US');
  });

  it('keeps group assignment visible and assigns the selected routes', () => {
    const onAssignGroupSelected = vi.fn();
    renderList([baseProxy], new Set([baseProxy.url]), onAssignGroupSelected);

    const groupInput = screen.getByPlaceholderText('ASSIGN GROUP NAME…');
    fireEvent.change(groupInput, { target: { value: 'Edge Pool' } });
    fireEvent.click(screen.getByRole('button', { name: 'ASSIGN GROUP' }));

    expect(onAssignGroupSelected).toHaveBeenCalledWith('Edge Pool');
  });

  it('renders routing groups open by default and toggles collapsed state on header click', () => {
    renderList([
      { ...baseProxy, id: 'http://dc1.example:8080', url: 'http://dc1.example:8080', group: 'Datacenter US' },
      { ...baseProxy, id: 'http://res1.example:8080', url: 'http://res1.example:8080', group: 'Residential' },
    ]);

    // Both proxies are visible by default (open by default)
    expect(screen.getByText('http://dc1.example:8080')).toBeVisible();
    expect(screen.getByText('http://res1.example:8080')).toBeVisible();

    // Click header to collapse Datacenter US
    const dcHeader = screen.getByRole('button', { name: /Toggle routing group Datacenter US/i });
    expect(dcHeader).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(dcHeader);

    // Datacenter US is collapsed, proxy is hidden; Residential is still open
    expect(dcHeader).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('http://dc1.example:8080')).not.toBeInTheDocument();
    expect(screen.getByText('http://res1.example:8080')).toBeVisible();

    // Click again to re-expand
    fireEvent.click(dcHeader);
    expect(dcHeader).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('http://dc1.example:8080')).toBeVisible();
  });

  it('toggles group selection via group header checkbox without collapsing accordion', () => {
    const onToggleSelectGroup = vi.fn();
    const dc1 = { ...baseProxy, id: 'http://dc1.example:8080', url: 'http://dc1.example:8080', group: 'Datacenter US' };
    const dc2 = { ...baseProxy, id: 'http://dc2.example:8080', url: 'http://dc2.example:8080', group: 'Datacenter US' };

    renderList([dc1, dc2], new Set(), vi.fn(), { onToggleSelectGroup });

    const groupCheckbox = screen.getByRole('checkbox', { name: /Select all proxies in Datacenter US/i });
    expect(groupCheckbox).not.toBeChecked();

    // Clicking group checkbox fires onToggleSelectGroup with the group proxies
    fireEvent.click(groupCheckbox);
    expect(onToggleSelectGroup).toHaveBeenCalledWith([dc1, dc2]);

    // Ensure the group accordion remains open (not collapsed by event bubbling)
    const dcHeader = screen.getByRole('button', { name: /Toggle routing group Datacenter US/i });
    expect(dcHeader).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('http://dc1.example:8080')).toBeVisible();
  });

  it('omits floating toolbar when 0 routes are staged', () => {
    renderList([baseProxy], new Set());
    expect(screen.queryByRole('toolbar', { name: 'Floating selection actions' })).not.toBeInTheDocument();
  });

  it('renders and fires bulk actions (test, enable, disable, revoke) when routes are staged in both inline and floating bars', () => {
    const onBulkTestSelected = vi.fn();
    const onBulkEnableSelected = vi.fn();
    const onBulkDisableSelected = vi.fn();
    const onBulkDeleteSelected = vi.fn();
    const dc1 = { ...baseProxy, id: 'http://dc1.example:8080', url: 'http://dc1.example:8080', group: 'Datacenter US' };
    const dc2 = { ...baseProxy, id: 'http://dc2.example:8080', url: 'http://dc2.example:8080', group: 'Datacenter US' };

    renderList([dc1, dc2], new Set([dc1.url, dc2.url]), vi.fn(), {
      onBulkTestSelected,
      onBulkEnableSelected,
      onBulkDisableSelected,
      onBulkDeleteSelected,
    });

    // Staged indicator shows 2 routes staged in both bars
    const stagedIndicators = screen.getAllByText(/ROUTES STAGED/i);
    expect(stagedIndicators).toHaveLength(2);
    expect(stagedIndicators[0]).toBeVisible();
    expect(stagedIndicators[0].textContent).toContain('2');

    // Floating toolbar is present
    const floatingToolbar = screen.getByRole('toolbar', { name: 'Floating selection actions' });
    expect(floatingToolbar).toBeInTheDocument();
    expect(floatingToolbar).toHaveClass('selection-bar-floating');

    // Bulk buttons are rendered in both inline and floating toolbars
    const testButtons = screen.getAllByRole('button', { name: /⚡ TEST \(2\)/i });
    const enableButtons = screen.getAllByRole('button', { name: /ENABLE \(2\)/i });
    const disableButtons = screen.getAllByRole('button', { name: /DISABLE \(2\)/i });
    const revokeButtons = screen.getAllByRole('button', { name: /REVOKE \(2\)/i });

    expect(testButtons).toHaveLength(2);
    expect(enableButtons).toHaveLength(2);
    expect(disableButtons).toHaveLength(2);
    expect(revokeButtons).toHaveLength(2);

    // Test actions from inline bar
    fireEvent.click(testButtons[0]);
    expect(onBulkTestSelected).toHaveBeenCalledWith([dc1.url, dc2.url]);

    fireEvent.click(enableButtons[0]);
    expect(onBulkEnableSelected).toHaveBeenCalledWith([dc1.url, dc2.url]);

    fireEvent.click(disableButtons[0]);
    expect(onBulkDisableSelected).toHaveBeenCalledWith([dc1.url, dc2.url]);

    fireEvent.click(revokeButtons[0]);
    expect(onBulkDeleteSelected).toHaveBeenCalledWith([dc1.url, dc2.url]);

    // Test actions from floating toolbar
    fireEvent.click(testButtons[1]);
    expect(onBulkTestSelected).toHaveBeenCalledTimes(2);

    fireEvent.click(enableButtons[1]);
    expect(onBulkEnableSelected).toHaveBeenCalledTimes(2);

    fireEvent.click(disableButtons[1]);
    expect(onBulkDisableSelected).toHaveBeenCalledTimes(2);

    fireEvent.click(revokeButtons[1]);
    expect(onBulkDeleteSelected).toHaveBeenCalledTimes(2);
  });

  it('opens bulk connection editing for all staged routes from both toolbars', () => {
    const onBulkEditSelected = vi.fn();
    const first = { ...baseProxy, id: 'http://first.example:8080', url: 'http://first.example:8080' };
    const second = { ...baseProxy, id: 'http://second.example:8080', url: 'http://second.example:8080' };

    renderList([first, second], new Set([first.url, second.url]), vi.fn(), {
      onBulkEditSelected,
    });

    const editButtons = screen.getAllByRole('button', { name: /EDIT CONNECTIONS \(2\)/i });
    expect(editButtons).toHaveLength(2);

    // Inline bar click
    fireEvent.click(editButtons[0]);
    expect(onBulkEditSelected).toHaveBeenCalledWith([first.url, second.url]);

    // Floating toolbar click
    fireEvent.click(editButtons[1]);
    expect(onBulkEditSelected).toHaveBeenCalledTimes(2);
  });

  it('shows and edits each routing group\'s lookup timeout without collapsing the group', async () => {
    const onSave = vi.fn().mockResolvedValue({});
    renderList(
      [
        { ...baseProxy, group: 'Datacenter US' },
        { ...baseProxy, id: 'http://residential.example:8080', url: 'http://residential.example:8080', group: 'Residential' },
      ],
      new Set(),
      vi.fn(),
      { groupLookupTimeouts: { 'Datacenter US': 8, Residential: null }, onSaveGroupLookupTimeout: onSave },
    );

    expect(screen.getByRole('button', { name: 'TIMEOUT 8s' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'TIMEOUT DEFAULT' }));
    // The group stays open: the chip does not toggle the header.
    expect(screen.getByRole('button', { name: 'Toggle routing group Residential' })).toHaveAttribute('aria-expanded', 'true');

    const input = screen.getByRole('spinbutton', { name: 'Guest lookup timeout for Residential in seconds' });
    fireEvent.change(input, { target: { value: '0.2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('at least 0.5 seconds');
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: '6' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith('Residential', 6));

    fireEvent.click(screen.getByRole('button', { name: 'TIMEOUT 8s' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith('Datacenter US', null));
  });
});
