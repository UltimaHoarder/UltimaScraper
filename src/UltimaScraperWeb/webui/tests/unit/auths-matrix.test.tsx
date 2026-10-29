import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { AuthCredential } from "../../src/api/types/auths";
import { AuthsMatrix } from "../../src/features/auths/components/AuthsMatrix";

const auth = (overrides: Partial<AuthCredential>): AuthCredential => ({
  id: 1,
  site: "onlyfans",
  username: "alice",
  user_id: 11,
  status: "valid",
  active: true,
  last_tested_at: null,
  created_at: "2026-01-02T10:00:00Z",
  cookie_preview: null,
  has_authorization: true,
  user_agent_preview: null,
  proxy_id: null,
  worker_shard: null,
  is_age_verified: null,
  age_verification_required: null,
  spend: false,
  spender_type: null,
  ...overrides,
});

const AUTHS = [
  auth({}),
  auth({
    id: 2,
    username: "bob",
    user_id: 22,
    status: "invalid",
    spend: true,
    spender_type: "paid",
    proxy_id: "nl-1",
    worker_shard: 3,
  }),
];

function renderMatrix(auths = AUTHS) {
  const props = {
    auths,
    togglePending: false,
    deletePending: false,
    batchPending: false,
    onManage: vi.fn(),
    onTest: vi.fn(),
    onToggle: vi.fn(),
    onDelete: vi.fn(),
    onBatchTest: vi.fn(),
    onBatchSetActive: vi.fn(),
  };
  const view = render(
    <MemoryRouter>
      <AuthsMatrix {...props} />
    </MemoryRouter>,
  );
  return { props, view };
}

describe("AuthsMatrix", () => {
  it("shows each account with its routing, worker and spending", () => {
    renderMatrix();

    const bob = screen.getByRole("row", { name: /@bob/ });
    expect(within(bob).getByRole("img", { name: "invalid" })).toBeInTheDocument();
    expect(within(bob).queryByText("invalid")).not.toBeInTheDocument();
    expect(bob).toHaveTextContent("UID 22");
    expect(bob).not.toHaveTextContent("#2");
    expect(within(bob).getByText("Never")).toBeInTheDocument();
    expect(within(bob).getByText("nl-1")).toBeInTheDocument();
    expect(within(bob).getByText("Shard 3")).toBeInTheDocument();
    expect(within(bob).getByText("Paid only")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /@alice/ })).getByText("Locked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Locked|Paid only/ })).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("row", { name: /@alice/ })).getByText("Direct"),
    ).toBeInTheDocument();
  });

  it("acts on the selected accounts", () => {
    const { props } = renderMatrix();

    const dock = screen.getByRole("toolbar", { name: "Selected auths" });
    expect(within(dock).getByRole("button", { name: "Test" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Select bob"));
    expect(dock).toHaveTextContent("1 selected");

    fireEvent.click(within(dock).getByRole("button", { name: "Disable" }));
    expect(props.onBatchSetActive).toHaveBeenCalledWith([AUTHS[1]], false);

    fireEvent.click(screen.getByLabelText("Select all auths"));
    fireEvent.click(within(dock).getByRole("button", { name: "Test" }));
    expect(props.onBatchTest).toHaveBeenCalledWith(AUTHS);

    fireEvent.click(
      within(dock).getByRole("button", { name: "Clear selection" }),
    );
    expect(dock).toHaveTextContent("Tick auths");
    expect(
      within(dock).getByRole("button", { name: "Disable" }),
    ).toBeDisabled();
  });

  it("forgets a selected account once it is no longer listed", () => {
    const { props, view } = renderMatrix();

    fireEvent.click(screen.getByLabelText("Select all auths"));
    view.rerender(
      <MemoryRouter>
        <AuthsMatrix {...props} auths={[AUTHS[0]]} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("toolbar")).toHaveTextContent("1 selected");
  });

  it("switches an auth on or off from its row", () => {
    const { props } = renderMatrix();

    fireEvent.click(screen.getByRole("switch", { name: "bob active" }));
    expect(props.onToggle).toHaveBeenCalledWith(AUTHS[1]);
  });

  it('folds an account with several auths into one row that opens', () => {
    const second = auth({
      id: 3,
      status: 'invalid',
      proxy_id: 'nl-1',
      last_tested_at: '2026-10-27T10:00:00Z',
      user_agent_preview: 'Mozilla/5.0 (Windows...********',
    });
    const { props } = renderMatrix([AUTHS[0], second, AUTHS[1]]);

    const alice = screen.getByRole('row', { name: /@alice/ });
    expect(alice).toHaveTextContent('2 auths');
    expect(alice).toHaveTextContent('Locked');
    expect(alice).toHaveTextContent('2 proxies');
    expect(screen.queryByText(/Session/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: "Show alice's 2 auths" }));
    expect(screen.getByRole('row', { name: /^Select alice Session 1 Session 1/ })).toBeInTheDocument();
    const nested = screen.getByRole('row', { name: /Session 2 · Windows/ });
    expect(nested).not.toHaveTextContent('Locked');
    expect(within(nested).getByRole('img', { name: 'invalid' })).toBeInTheDocument();
    expect(nested.querySelectorAll('time')[0]).toHaveAttribute('datetime', '2026-01-02T10:00:00Z');
    expect(nested).toHaveTextContent('No worker');
    expect(nested.querySelectorAll('time')[1]).toHaveAttribute('datetime', '2026-10-27T10:00:00Z');
    expect(nested.querySelectorAll('time')[1].textContent).toMatch(/ago$/);
    fireEvent.click(within(nested).getByRole('button', { name: 'Manage' }));
    expect(props.onManage).toHaveBeenCalledWith(second);

    fireEvent.click(screen.getByLabelText("Select all of alice's auths"));
    expect(screen.getByRole('toolbar')).toHaveTextContent('2 selected');
    fireEvent.click(screen.getByLabelText('Select alice Session 2 · Windows'));
    expect(screen.getByLabelText("Select all of alice's auths")).toHaveProperty('indeterminate', true);

    fireEvent.click(within(alice).getByRole('button', { name: 'Test all' }));
    expect(props.onBatchTest).toHaveBeenCalledWith([AUTHS[0], second]);
  });

  it('shows one dot per colour for an account whose auths differ', () => {
    renderMatrix([
      AUTHS[0],
      auth({ id: 3 }),
      auth({ id: 4, status: 'proxy_error' }),
      auth({ id: 5, status: 'invalid' }),
    ]);

    const alice = screen.getByRole('row', { name: /@alice/ });
    const dots = within(alice).getAllByRole('img');
    expect(dots).toHaveLength(2);
    expect(within(alice).getByRole('img', { name: 'valid' })).toBeInTheDocument();
    expect(within(alice).getByRole('img', { name: 'proxy error, invalid' })).toBeInTheDocument();
  });
});
