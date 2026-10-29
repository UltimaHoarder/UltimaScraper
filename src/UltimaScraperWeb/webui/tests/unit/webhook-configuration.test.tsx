import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WebhookConfigurationEditor } from '../../src/features/webhooks/components/WebhookConfigurationEditor';
import { webhookHookCatalog } from '../../src/features/webhooks/lib/webhookConfiguration';
import type { SiteWebhookRouting, WebhookConfiguration, WebhooksResponse, WebhookSite } from '../../src/api/types/webhooks';
import { createTestQueryClient } from './testUtils';

const api = vi.hoisted(() => ({ saveWebhookConfiguration: vi.fn() }));
vi.mock('../../src/api/webhooks', () => api);
const empty = () => ({ destinations: [], rules: [] });
const initial: WebhookConfiguration = { version: 14, catalog: webhookHookCatalog, sites: { onlyfans: empty(), fansly: empty() } };
const legacy = { auth: { active: false, url: null, hide_info: [] }, download: { active: false, url: null, hide_info: [] } };
function setup(configuration = structuredClone(initial)) {
  const data: WebhooksResponse = { sites: { onlyfans: legacy, fansly: legacy }, configuration };
  const onSaved = vi.fn();
  const onReload = vi.fn().mockResolvedValue({ ...data, configuration: { ...initial, version: 15 } });
  render(<QueryClientProvider client={createTestQueryClient()}><WebhookConfigurationEditor data={data} onSaved={onSaved} onReload={onReload} /></QueryClientProvider>);
  return { onSaved, onReload };
}
function addDestination(index: number, name: string, url: string) {
  fireEvent.click(screen.getByRole('button', { name: '＋ Add destination' }));
  fireEvent.change(screen.getByRole('textbox', { name: `Destination ${index} name` }), { target: { value: name } });
  fireEvent.change(screen.getByRole('textbox', { name: `Destination ${index} URL` }), { target: { value: url } });
}
beforeEach(() => {
  api.saveWebhookConfiguration.mockImplementation(async (site: WebhookSite, routing: SiteWebhookRouting) => ({ ...structuredClone(initial), version: 15, sites: { ...structuredClone(initial.sites), [site]: routing } }));
});

describe('webhook configuration flow', () => {
  it('saves several selected hooks to several destinations in one site configuration', async () => {
    const { onSaved } = setup();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Auth' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Download' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Chat messages' }));
    addDestination(1, 'Operations', 'https://example.test/ops');
    addDestination(2, 'Discord', 'https://example.test/discord');
    fireEvent.change(screen.getByRole('combobox', { name: 'Destination 2 payload' }), { target: { value: 'discord' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
    await screen.findByText('OnlyFans configuration saved.');
    const [site, routing, version] = api.saveWebhookConfiguration.mock.calls[0];
    expect(site).toBe('onlyfans'); expect(version).toBe(14);
    expect(routing.rules[0].hooks).toEqual(['auth', 'download', 'chat_message']);
    expect(routing.rules[0].destination_ids).toEqual(routing.destinations.map((destination: { id: string }) => destination.id));
    expect(routing.destinations.map((destination: { url: string }) => destination.url)).toEqual(['https://example.test/ops', 'https://example.test/discord']);
    expect(onSaved).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Save configuration' })).toBeDisabled();
  });

  it('keeps per-site drafts and only offers events supported by the selected site', () => {
    setup();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Comments' }));
    fireEvent.click(screen.getByRole('button', { name: 'Configure Fansly' }));
    expect(screen.queryByRole('checkbox', { name: 'Hook: Comments' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Hook: Auth' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Hook: Download' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Configure OnlyFans' }));
    expect(screen.getByRole('checkbox', { name: 'Hook: Comments' })).toBeChecked();
  });

  it('validates empty selections, invalid URLs, and duplicate destinations before saving', () => {
    setup();
    fireEvent.change(screen.getByRole('textbox', { name: 'Rule name' }), { target: { value: 'Alerts' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose at least one hook');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Auth' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose at least one destination');
    addDestination(1, 'Ops', 'file:///tmp/not-http');
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
    expect(screen.getByRole('alert')).toHaveTextContent('valid HTTP or HTTPS URL');
    fireEvent.change(screen.getByRole('textbox', { name: 'Destination 1 URL' }), { target: { value: 'https://example.test/hook' } });
    addDestination(2, 'Duplicate', 'https://example.test/hook');
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
    expect(screen.getByRole('alert')).toHaveTextContent('already configured');
    expect(api.saveWebhookConfiguration).not.toHaveBeenCalled();
  });

  it('preserves edits on a revision conflict until the user explicitly discards and reloads', async () => {
    api.saveWebhookConfiguration.mockRejectedValue(new Error('Configuration changed. Reload the configuration and apply your changes again.'));
    const { onReload } = setup();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Auth' }));
    addDestination(1, 'Ops', 'https://example.test/hook');
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('textbox', { name: 'Destination 1 URL' })).toHaveValue('https://example.test/hook');
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes and reload' }));
    await waitFor(() => expect(onReload).toHaveBeenCalledOnce());
    await screen.findByText('Configuration reloaded.');
    expect(screen.queryByRole('textbox', { name: 'Destination 1 URL' })).not.toBeInTheDocument();
  });

  it('reuses destinations across rules and removes destination references from all rules', async () => {
    setup();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Auth' }));
    addDestination(1, 'Shared', 'https://example.test/shared');
    fireEvent.click(screen.getByRole('button', { name: '＋ Add rule' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Download' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Send to Shared' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
    await screen.findByText('OnlyFans configuration saved.');
    const routing = api.saveWebhookConfiguration.mock.calls[0][1];
    expect(routing.destinations).toHaveLength(1);
    expect(routing.rules).toHaveLength(2);
    expect(routing.rules[0].destination_ids).toEqual(routing.rules[1].destination_ids);
    fireEvent.click(screen.getByRole('button', { name: 'Remove destination 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose at least one destination');
  });
});
