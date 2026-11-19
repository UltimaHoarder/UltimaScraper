import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as authsApi from '../../src/api/auths';
import * as networkApi from '../../src/api/network';
import { AddCurlModal } from '../../src/features/auths/components/AddCurlModal';
import { renderWithProviders } from './testUtils';

describe('AddCurlModal', () => {
  const userInput = `{'id': None, 'username': '', 'cookie': 'auth_id=11111111; sess=fakesessiontoken0000000000; auth_hash=; auth_uniq_11111111=; auth_uid_11111111=; aws-waf-token=;', 'x_bc': '0000000000000000000000000000000000000000', 'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'email': '', 'password': '', 'hashed': False, 'support_2fa': True, 'active': True}`;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(networkApi, 'listProxies').mockResolvedValue([]);
  });

  it('automatically switches to Auth JSON tab and normalizes Python dict when pasted', async () => {
    const parseAuthJsonMock = vi
      .spyOn(authsApi, 'parseAuthJson')
      .mockResolvedValue({
        authorization: null,
        app_token: null,
        error: null,
        success: true,
        site: 'onlyfans',
        auth_id: '11111111',
        user_id: 11111111,
        sess: 'fakesessiontoken0000000000',
        cookie: 'auth_id=11111111; sess=fakesessiontoken0000000000;',
        x_bc: '0000000000000000000000000000000000000000',
        user_agent: 'Mozilla/5.0',
        raw_headers: {},
      });

    renderWithProviders(<AddCurlModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    // Starts on cURL tab
    const curlTab = screen.getByRole('tab', { name: 'cURL' });
    const jsonTab = screen.getByRole('tab', { name: 'Auth JSON' });
    expect(curlTab).toHaveAttribute('aria-selected', 'true');
    expect(jsonTab).toHaveAttribute('aria-selected', 'false');

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;

    // Simulate paste
    fireEvent.paste(textarea, {
      clipboardData: {
        getData: () => userInput,
      },
    });

    // Should switch tab to Auth JSON
    expect(jsonTab).toHaveAttribute('aria-selected', 'true');
    expect(curlTab).toHaveAttribute('aria-selected', 'false');

    // Textarea value should be valid normalized JSON
    expect(textarea.value).toContain('"auth_id": "11111111"');
    expect(textarea.value).toContain('"sess": "fakesessiontoken0000000000"');
    expect(textarea.value).toContain('"x_bc": "0000000000000000000000000000000000000000"');
    expect(() => JSON.parse(textarea.value)).not.toThrow();

    await waitFor(() => {
      expect(parseAuthJsonMock).toHaveBeenCalled();
    });

    const parsedArg = parseAuthJsonMock.mock.calls[0][0];
    const parsedPayload = JSON.parse(parsedArg);
    expect(parsedPayload.auth_id).toBe('11111111');
    expect(parsedPayload.sess).toBe('fakesessiontoken0000000000');
  });

  it('normalizes Python dict on change and adds auth successfully', async () => {
    vi.spyOn(authsApi, 'parseAuthJson').mockResolvedValue({
      error: null,
      x_bc: null,
      authorization: null,
      user_agent: null,
      app_token: null,
      success: true,
      site: 'onlyfans',
      auth_id: '11111111',
      user_id: 11111111,
      sess: 'fakesessiontoken0000000000',
      cookie: 'auth_id=11111111;',
      raw_headers: {},
    });

    const addAuthMock = vi.spyOn(authsApi, 'addAuthFromCurl').mockResolvedValue({
      error: null,
      success: true,
      auth_id: 1,
      user_id: 11111111,
      username: 'tester',
    });

    const onSuccess = vi.fn();
    renderWithProviders(<AddCurlModal onClose={vi.fn()} onSuccess={onSuccess} />);

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: userInput } });

    // Textarea was normalized
    expect(() => JSON.parse(textarea.value)).not.toThrow();

    // Wait for parsed data to show and enable Add Account button
    const addButton = screen.getByRole('button', { name: /Add Account/i });
    await waitFor(() => {
      expect(addButton).not.toBeDisabled();
    });

    fireEvent.click(addButton);

    await waitFor(() => {
      expect(addAuthMock).toHaveBeenCalled();
    });

    const addedArg = addAuthMock.mock.calls[0][0];
    const addedPayload = JSON.parse(addedArg);
    expect(addedPayload.auth_id).toBe('11111111');
    expect(addedPayload.sess).toBe('fakesessiontoken0000000000');
    // Spender left unticked: an existing account keeps its setting.
    expect(addAuthMock.mock.calls[0][5]).toBeNull();
    expect(onSuccess).toHaveBeenCalled();
  });

  it('marks the new account a spender of the chosen type', async () => {
    vi.spyOn(authsApi, 'parseCurl').mockResolvedValue({
      error: null,
      x_bc: null,
      authorization: 'Bearer fake',
      user_agent: 'Mozilla/5.0',
      app_token: null,
      success: true,
      site: 'fansly',
      auth_id: null,
      user_id: null,
      sess: null,
      cookie: null,
      raw_headers: {},
    });
    const addAuthMock = vi.spyOn(authsApi, 'addAuthFromCurl').mockResolvedValue({
      error: null,
      success: true,
      auth_id: 1,
      user_id: 22,
      username: 'spender',
    });

    renderWithProviders(<AddCurlModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Site:'), { target: { value: 'fansly' } });
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: "curl 'https://apiv3.fansly.com/api/v1/account/me' -H 'authorization: fake'" },
    });

    expect(screen.queryByLabelText('Spender Type')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Spender (can purchase subscriptions)'));
    fireEvent.change(screen.getByLabelText('Spender Type'), { target: { value: 'free' } });

    const addButton = screen.getByRole('button', { name: /Add Account/i });
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);

    await waitFor(() => expect(addAuthMock).toHaveBeenCalled());
    expect(addAuthMock.mock.calls[0][1]).toBe('fansly');
    expect(addAuthMock.mock.calls[0][5]).toEqual({ spenderType: 'free' });
  });

  it("lists only the credentials the parsed site signs in with", async () => {
    vi.spyOn(authsApi, 'parseCurl').mockResolvedValue({
      error: null,
      x_bc: null,
      authorization: 'Bearer fake',
      user_agent: 'Mozilla/5.0',
      app_token: null,
      success: true,
      site: 'privacy',
      auth_id: null,
      user_id: null,
      sess: null,
      cookie: null,
      raw_headers: {},
    });

    renderWithProviders(<AddCurlModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Site:'), { target: { value: 'privacy' } });
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: "curl 'https://service.privacy.com.br/profile/me' -H 'authorization: fake'" },
    });

    expect(await screen.findByText('Authorization:')).toBeInTheDocument();
    expect(screen.getByText('User Agent:')).toBeInTheDocument();
    for (const unused of ['App Token:', 'Cookie:', 'X-BC:']) {
      expect(screen.queryByText(unused)).not.toBeInTheDocument();
    }
    expect(screen.queryByText('❌ Not found')).not.toBeInTheDocument();
  });
});
