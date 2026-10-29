import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { NetworkProxy } from '../../src/api/types/network';

import { BulkProxyModal } from '../../src/features/network/components/BulkProxyModal';

describe('BulkProxyModal', () => {
  it('parses pasted proxy list, assigns default group, and imports all', () => {
    const onImport = vi.fn();
    const onBulkTest = vi.fn();
    const onClose = vi.fn();

    render(
      <BulkProxyModal
        isOpen={true}
        existingGroups={['ExistingGroup']}
        isImporting={false}
        onClose={onClose}
        onImport={onImport}
        onBulkTest={onBulkTest}
      />,
    );

    expect(screen.getByText('Bulk Add Proxies')).toBeVisible();

    // Set default group
    const groupInput = screen.getByLabelText(/Assign to Group Name/i);
    fireEvent.change(groupInput, { target: { value: 'Residential-US' } });

    // Paste proxies
    const textarea = screen.getByLabelText(/Paste Proxies/i);
    fireEvent.change(textarea, {
      target: {
        value: `http://anon:anon@203.0.113.10:6754\nhttp://anon:anon@203.0.113.20:6014 # Special Group\nsocks5://usr:pwd@10.0.0.1:1080`,
      },
    });

    // Check preview table rows
    expect(screen.getByText('http://203.0.113.10:6754')).toBeVisible();
    expect(screen.getByText('http://203.0.113.20:6014')).toBeVisible();
    expect(screen.getByText('socks5://10.0.0.1:1080')).toBeVisible();

    // Click Import All
    const importAllBtn = screen.getByRole('button', { name: /Import All \(3\)/i });
    fireEvent.click(importAllBtn);

    expect(onImport).toHaveBeenCalledWith([
      {
        url: 'http://203.0.113.10:6754',
        username: 'anon',
        password: 'anon',
        group: 'Residential-US',
        max_connections: -1,
        enabled: true,
      },
      {
        url: 'http://203.0.113.20:6014',
        username: 'anon',
        password: 'anon',
        group: 'Special Group',
        max_connections: -1,
        enabled: true,
      },
      {
        url: 'socks5://10.0.0.1:1080',
        username: 'usr',
        password: 'pwd',
        group: 'Residential-US',
        max_connections: -1,
        enabled: true,
      },
    ]);
  });

  it('runs bulk testing and enables active-only import', async () => {
    const onImport = vi.fn();
    const onBulkTest = vi.fn().mockResolvedValue([
      { url: 'http://203.0.113.10:6754', success: true, latency_ms: 85, message: 'Reachable' },
      { url: 'http://203.0.113.20:6014', success: false, latency_ms: null, message: 'Connection refused' },
    ]);

    render(
      <BulkProxyModal
        isOpen={true}
        existingGroups={[]}
        isImporting={false}
        onClose={vi.fn()}
        onImport={onImport}
        onBulkTest={onBulkTest}
      />,
    );

    const textarea = screen.getByLabelText(/Paste Proxies/i);
    fireEvent.change(textarea, {
      target: {
        value: `http://anon:anon@203.0.113.10:6754\nhttp://anon:anon@203.0.113.20:6014`,
      },
    });

    const testAllBtn = screen.getByRole('button', { name: /Test All \(2\)/i });
    fireEvent.click(testAllBtn);

    expect(onBulkTest).toHaveBeenCalledWith([
      { url: 'http://203.0.113.10:6754', username: 'anon', password: 'anon' },
      { url: 'http://203.0.113.20:6014', username: 'anon', password: 'anon' },
    ]);

    // Await active status badge
    await waitFor(() => {
      expect(screen.getByText(/✓ Active \(85 ms\)/i)).toBeVisible();
      expect(screen.getByText(/✗ Offline: Connection refused/i)).toBeVisible();
    });

    // "Import Active Only (1)" should now be visible
    const importActiveBtn = screen.getByRole('button', { name: /Import Active Only \(1\)/i });
    fireEvent.click(importActiveBtn);

    expect(onImport).toHaveBeenCalledWith([
      {
        url: 'http://203.0.113.10:6754',
        username: 'anon',
        password: 'anon',
        group: null,
        max_connections: -1,
        enabled: true,
      },
    ]);
  });

  it('supports bulk edit mode: pre-fills existing proxies, calculates sync diff plan, and applies sync', () => {
    const onImport = vi.fn();
    const onBulkSync = vi.fn();
    const onBulkTest = vi.fn();
    const onClose = vi.fn();

    const currentProxies = [
      {
        id: 'http://203.0.113.10:6754',
        url: 'http://203.0.113.10:6754',
        username: 'userA',
        enabled: true,
        max_connections: 8,
        group: 'GroupA',
        assigned_auths: [1],
      },
      {
        id: 'http://203.0.113.20:6014',
        url: 'http://203.0.113.20:6014',
        username: null,
        enabled: true,
        max_connections: -1,
        group: null,
        assigned_auths: [],
      },
      {
        id: 'http://203.0.113.30:6462',
        url: 'http://203.0.113.30:6462',
        username: null,
        enabled: true,
        max_connections: -1,
        group: null,
        assigned_auths: [],
      },
    ];

    render(
      <BulkProxyModal
        isOpen={true}
        existingGroups={['GroupA']}
        currentProxies={currentProxies}
        initialMode="edit"
        isImporting={false}
        onClose={onClose}
        onImport={onImport}
        onBulkSync={onBulkSync}
        onBulkTest={onBulkTest}
      />,
    );

    expect(screen.getByText('Bulk Edit Proxies')).toBeVisible();

    // The textarea should be prefilled with all 3 current proxies
    const textarea = screen.getByLabelText(/Proxy Pool List/i) as HTMLTextAreaElement;
    expect(textarea.value).toContain('http://userA@203.0.113.10:6754 # GroupA');
    expect(textarea.value).toContain('http://203.0.113.20:6014');
    expect(textarea.value).toContain('http://203.0.113.30:6462');

    // Initially: all 3 kept, 0 added, 0 deleted
    expect(screen.getByText(/✓ KEEP 3 EXISTING/i)).toBeVisible();
    expect(screen.getByText(/\+ ADD 0 NEW/i)).toBeVisible();
    expect(screen.getByText(/− DELETE 0 OMITTED/i)).toBeVisible();

    // Now edit the text: keep only http://203.0.113.20:6014, remove the other 2, and add http://10.0.0.1:8080
    fireEvent.change(textarea, {
      target: {
        value: `http://203.0.113.20:6014\nhttp://anon:anon@10.0.0.1:8080 # NewGroup`,
      },
    });

    // Plan should update: KEEP 1, ADD 1, DELETE 2
    expect(screen.getByText(/✓ KEEP 1 EXISTING/i)).toBeVisible();
    expect(screen.getByText(/\+ ADD 1 NEW/i)).toBeVisible();
    expect(screen.getByText(/− DELETE 2 OMITTED/i)).toBeVisible();

    // Table rows should show plan badges
    expect(screen.getByText('KEEP AS-IS')).toBeVisible();
    expect(screen.getByText('+ ADD NEW')).toBeVisible();

    // Omitted routes chips should list the 2 deleted proxies
    expect(screen.getByText(/2 Omitted Routes/i)).toBeVisible();
    expect(screen.getByText('http://203.0.113.10:6754')).toBeVisible();
    expect(screen.getByText('http://203.0.113.30:6462')).toBeVisible();

    // Apply button text
    const applyBtn = screen.getByRole('button', {
      name: /Apply Changes \(Add 1, Keep 1, Delete 2\)/i,
    });
    fireEvent.click(applyBtn);

    expect(onBulkSync).toHaveBeenCalledWith(
      [
        {
          url: 'http://203.0.113.20:6014',
          username: null,
          password: null,
          group: null,
          max_connections: -1,
          enabled: true,
        },
        {
          url: 'http://10.0.0.1:8080',
          username: 'anon',
          password: 'anon',
          group: 'NewGroup',
          max_connections: -1,
          enabled: true,
        },
      ],
      `http://203.0.113.20:6014\nhttp://anon:anon@10.0.0.1:8080 # NewGroup`,
      null,
    );
  });

  it('supports group-scoped bulk edit: scopes diff plan to target group and does not delete other groups', () => {
    const onBulkSync = vi.fn();
    const groupProxies: NetworkProxy[] = [
      {
        id: 'http://dc1.test:8080',
        url: 'http://dc1.test:8080',
        username: null,
        enabled: true,
        max_connections: -1,
        group: 'Datacenter',
        assigned_auths: [],
      },
      {
        id: 'http://dc2.test:8080',
        url: 'http://dc2.test:8080',
        username: null,
        enabled: true,
        max_connections: -1,
        group: 'Datacenter',
        assigned_auths: [],
      },
      {
        id: 'http://res1.test:8080',
        url: 'http://res1.test:8080',
        username: null,
        enabled: true,
        max_connections: -1,
        group: 'Residential',
        assigned_auths: [],
      },
    ];

    render(
      <BulkProxyModal
        isOpen={true}
        existingGroups={['Datacenter', 'Residential']}
        currentProxies={groupProxies}
        selectedGroupFilter="Datacenter"
        initialMode="edit"
        isImporting={false}
        onClose={vi.fn()}
        onImport={vi.fn()}
        onBulkSync={onBulkSync}
        onBulkTest={vi.fn().mockResolvedValue([])}
      />,
    );

    // Initial plan should only count Datacenter (2 proxies), not Residential
    expect(screen.getByText(/✓ KEEP 2 EXISTING/i)).toBeVisible();
    expect(screen.getByText(/− DELETE 0 OMITTED/i)).toBeVisible();

    // Textarea should only have Datacenter proxies loaded
    const textarea = screen.getByLabelText(/Proxy Pool List/i) as HTMLTextAreaElement;
    expect(textarea.value).toContain('http://dc1.test:8080');
    expect(textarea.value).toContain('http://dc2.test:8080');
    expect(textarea.value).not.toContain('http://res1.test:8080');

    // Change text: keep dc1, omit dc2, add dc3
    fireEvent.change(textarea, {
      target: {
        value: `http://dc1.test:8080\nhttp://dc3.test:8080`,
      },
    });

    // Plan should show: KEEP 1, ADD 1, DELETE 1 (only dc2 omitted)
    expect(screen.getByText(/✓ KEEP 1 EXISTING/i)).toBeVisible();
    expect(screen.getByText(/\+ ADD 1 NEW/i)).toBeVisible();
    expect(screen.getByText(/− DELETE 1 OMITTED/i)).toBeVisible();

    // The deleted list must only show dc2, NEVER res1 from Residential
    expect(screen.getByText('http://dc2.test:8080')).toBeVisible();
    expect(screen.queryByText('http://res1.test:8080')).toBeNull();

    // Apply
    const applyBtn = screen.getByRole('button', {
      name: /Apply Changes/i,
    });
    fireEvent.click(applyBtn);

    expect(onBulkSync).toHaveBeenCalledWith(
      [
        {
          url: 'http://dc1.test:8080',
          username: null,
          password: null,
          group: 'Datacenter',
          max_connections: -1,
          enabled: true,
        },
        {
          url: 'http://dc3.test:8080',
          username: null,
          password: null,
          group: 'Datacenter',
          max_connections: -1,
          enabled: true,
        },
      ],
      `http://dc1.test:8080\nhttp://dc3.test:8080`,
      'Datacenter',
    );
  });
});

