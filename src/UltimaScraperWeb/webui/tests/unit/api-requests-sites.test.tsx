import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { executeApiMethod, getApiMethods, type ApiMethodSpec } from '../../src/api/apiRequests';
import { getAuthList } from '../../src/api/auths';
import { APIRequestsTool } from '../../src/features/tools/components/APIRequestsTool';
import { methodsForSite } from '../../src/features/tools/lib/apiRequestSites';

vi.mock('../../src/api/apiRequests', () => ({
  executeApiMethod: vi.fn(),
  getApiMethods: vi.fn(),
}));

vi.mock('../../src/api/auths', () => ({
  getAuthList: vi.fn(),
}));

function method(name: string, sites?: string[]): ApiMethodSpec {
  return { method: name, description: `${name} description`, args: {}, sites };
}

const methods = {
  get_user: method('get_user', ['onlyfans', 'fansly', 'privacy']),
  get_chats: method('get_chats', ['onlyfans', 'privacy']),
  blocked_users: method('blocked_users', ['onlyfans']),
  ping: method('ping'),
};

function optionValues(select: HTMLElement) {
  return within(select)
    .getAllByRole('option')
    .map((option) => (option as HTMLOptionElement).value);
}

describe('API requests sites', () => {
  beforeEach(() => {
    vi.mocked(getApiMethods).mockResolvedValue({
      methods,
      sites: [
        { key: 'onlyfans', label: 'OnlyFans' },
        { key: 'fansly', label: 'Fansly' },
        { key: 'privacy', label: 'Privacy' },
      ],
    });
    vi.mocked(getAuthList).mockImplementation(async (site) => ({
      success: true,
      total: 1,
      auths: [{ id: 7, site, username: `${site}-account`, user_id: 70 }],
    }) as unknown as Awaited<ReturnType<typeof getAuthList>>);
    vi.mocked(executeApiMethod).mockResolvedValue({ success: true, method: 'get_chats', data: [] });
  });

  it('keeps the methods a site can run', () => {
    expect(Object.keys(methodsForSite(methods, 'privacy'))).toEqual(['get_user', 'get_chats', 'ping']);
    expect(Object.keys(methodsForSite(methods, 'fansly'))).toEqual(['get_user', 'ping']);
  });

  it("offers the backend's sites and only their methods", async () => {
    render(<APIRequestsTool />);
    const [siteSelect, , methodSelect] = screen.getAllByRole('combobox');

    await waitFor(() => expect(optionValues(siteSelect)).toEqual(['onlyfans', 'fansly', 'privacy']));
    expect(within(siteSelect).getByRole('option', { name: 'Privacy' })).toBeTruthy();
    expect(optionValues(methodSelect)).toEqual(['get_user', 'get_chats', 'blocked_users', 'ping']);

    fireEvent.change(methodSelect, { target: { value: 'get_chats' } });
    fireEvent.change(siteSelect, { target: { value: 'privacy' } });
    await waitFor(() => expect(optionValues(methodSelect)).toEqual(['get_user', 'get_chats', 'ping']));
    // Privacy can run the chosen method, so it stays chosen.
    expect((methodSelect as HTMLSelectElement).value).toBe('get_chats');

    fireEvent.change(siteSelect, { target: { value: 'fansly' } });
    await waitFor(() => expect(optionValues(methodSelect)).toEqual(['get_user', 'ping']));
    expect((methodSelect as HTMLSelectElement).value).toBe('get_user');
    expect(getAuthList).toHaveBeenLastCalledWith('fansly', true);
  });

  it('runs the method on the chosen site', async () => {
    render(<APIRequestsTool />);
    const [siteSelect, , methodSelect] = screen.getAllByRole('combobox');
    await waitFor(() => expect(optionValues(siteSelect)).toContain('privacy'));

    fireEvent.change(siteSelect, { target: { value: 'privacy' } });
    await screen.findByRole('option', { name: 'privacy-account (ID 7)' });
    fireEvent.change(methodSelect, { target: { value: 'get_chats' } });
    fireEvent.click(screen.getByRole('button', { name: 'Execute' }));

    await waitFor(() =>
      expect(executeApiMethod).toHaveBeenCalledWith({
        site: 'privacy',
        auth_id: 7,
        method: 'get_chats',
        args: {},
      }),
    );
  });
});
