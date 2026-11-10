import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getAuthBalance } from '../../src/api/auths';
import { getChatMessages } from '../../src/api/chats';
import { getEligibleAuths } from '../../src/api/users';
import { DirectChatModal } from '../../src/components/chats/DirectChatModal';

vi.mock('../../src/api/auths', () => ({ getAuthBalance: vi.fn() }));
vi.mock('../../src/api/chats', () => ({
  buyChatMessage: vi.fn(),
  getChatMessages: vi.fn(),
  likeChatMessage: vi.fn(),
  sendChatMessage: vi.fn(),
}));
vi.mock('../../src/api/users', () => ({ getEligibleAuths: vi.fn() }));
vi.mock('../../src/hooks/useWebSocket', () => ({ useWebSocket: () => ({}) }));

const mockGetAuthBalance = vi.mocked(getAuthBalance);
const mockGetChatMessages = vi.mocked(getChatMessages);
const mockGetEligibleAuths = vi.mocked(getEligibleAuths);

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DirectChatModal isOpen onClose={() => {}} site="onlyfans" userId={7} username="performer" />
    </QueryClientProvider>,
  );
}

function eligible(...auths: Array<[number, string, boolean]>) {
  mockGetEligibleAuths.mockResolvedValue({
    auths: auths.map(([auth_id, auth_username, is_active]) => ({ auth_id, auth_username, is_active })),
    error: null,
  } as Awaited<ReturnType<typeof getEligibleAuths>>);
}

describe('DirectChatModal accounts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // jsdom has no scrollIntoView; the message list scrolls to the newest message.
    Element.prototype.scrollIntoView = vi.fn();
    mockGetAuthBalance.mockResolvedValue({ success: true, balance: 12.5 } as Awaited<ReturnType<typeof getAuthBalance>>);
    mockGetChatMessages.mockResolvedValue({ success: true, messages: [], has_more: false } as unknown as Awaited<ReturnType<typeof getChatMessages>>);
  });

  it('offers an account whose subscription expired, labelled as expired', async () => {
    eligible([1, 'expired_auth', false]);
    renderModal();

    expect(await screen.findByText(/@expired_auth\s*\(expired\)/)).toBeInTheDocument();
    expect(await screen.findByText('No messages yet. Start the conversation.')).toBeInTheDocument();
    expect(screen.queryByText('No auth accounts can chat with this user.')).not.toBeInTheDocument();
    expect(await screen.findByText('Balance: $12.50')).toBeInTheDocument();
    expect(mockGetChatMessages.mock.calls[0][2]).toBe(1);
  });

  it('selects an active account ahead of an expired one', async () => {
    eligible([1, 'expired_auth', false], [2, 'active_auth', true]);
    renderModal();

    const options = await screen.findAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual(['@active_auth', '@expired_auth (expired)']);
    expect(screen.getByRole('combobox')).toHaveValue('2');
  });

  it('still says so when no account has any subscription history', async () => {
    eligible();
    renderModal();

    expect(await screen.findByText('No auth accounts can chat with this user.')).toBeInTheDocument();
  });
});
