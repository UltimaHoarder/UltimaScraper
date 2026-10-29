import { useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import type { AuthCredential } from '../../../api/types/auths';
import { formatRelativeTime } from '../../user-profile/lib/userProfileUtils';
import { formatAuthDate, getSiteIcon, spenderTypeLabel } from '../lib/authsUtils';

const SITE_NAMES: Record<string, string> = { onlyfans: 'OnlyFans', fansly: 'Fansly' };

const authKey = (auth: AuthCredential) => `${auth.site}-${auth.id}`;
const siteName = (site: string) => SITE_NAMES[site.toLowerCase()] ?? site;
const profilePath = (auth: AuthCredential) => `/users/${auth.user_id}?site=${encodeURIComponent(auth.site)}`;
const displayName = (auth: AuthCredential) => auth.username || `u${auth.user_id}`;

type Tone = 'ok' | 'bad' | 'idle';

function statusTone(status: string): Tone {
  const value = status.toLowerCase();
  if (value === 'valid' || value === 'active') return 'ok';
  if (['invalid', 'error', 'proxy_error', 'timeout', 'expired'].includes(value)) return 'bad';
  return 'idle';
}

interface UserGroup {
  key: string;
  name: string;
  auths: AuthCredential[];
}

/** One group per account on a site, in the order the accounts were listed. */
function groupByUser(auths: AuthCredential[]): UserGroup[] {
  const groups = new Map<string, UserGroup>();
  for (const auth of auths) {
    const key = `${auth.site}-${auth.user_id}`;
    const group = groups.get(key) ?? { key, name: displayName(auth), auths: [] };
    // Any of the auths may be the one that knows the username.
    if (auth.username && group.name === `u${auth.user_id}`) {
      group.name = auth.username;
    }
    group.auths.push(auth);
    groups.set(key, group);
  }
  return [...groups.values()];
}

const SPEND_LABELS: Record<string, string> = { free: 'Free only', paid: 'Paid only' };

/**
 * The OS a user agent names, when its masked start (about 20 characters)
 * still shows it. A bare "(Linux;" is left out: Android cuts off the same way.
 */
function platformOf(userAgent: string | null) {
  if (!userAgent) return null;
  if (/Android/i.test(userAgent)) return 'Android';
  if (/iPhone|iPad/i.test(userAgent)) return 'iOS';
  if (/Windows/i.test(userAgent)) return 'Windows';
  if (/Macint|Mac OS/i.test(userAgent)) return 'macOS';
  if (/X11/i.test(userAgent)) return 'Linux';
  return null;
}

/** Spending is the account's setting, shared by all its auths. */
function Spending({ auth }: { auth: AuthCredential }) {
  if (!auth.spend) return <span className="auths-matrix-muted">Locked</span>;
  return (
    <span className="auths-matrix-spend" title={`May purchase subscriptions: ${spenderTypeLabel(auth.spender_type)}`}>
      {SPEND_LABELS[auth.spender_type ?? ''] ?? 'Any price'}
    </span>
  );
}

function SiteName({ site }: { site: string }) {
  return (
    <span className="auths-matrix-site">
      <span aria-hidden="true">{getSiteIcon(site)}</span>
      {siteName(site)}
    </span>
  );
}

const statusText = (status: string) => status.replace(/_/g, ' ');

/** A status as its colour; the word is there for hover and screen readers. */
function StatusDot({ status }: { status: string }) {
  return (
    <span
      className={`auths-matrix-state auths-matrix-state--${statusTone(status)}`}
      role="img"
      aria-label={statusText(status)}
      title={statusText(status)}
    >
      <i />
    </span>
  );
}

/** Several statuses as one dot per colour, each naming the statuses it stands for. */
function StatusDots({ statuses }: { statuses: string[] }) {
  const byTone = new Map<Tone, Set<string>>();
  for (const status of statuses) {
    const tone = statusTone(status);
    byTone.set(tone, (byTone.get(tone) ?? new Set()).add(statusText(status)));
  }
  return (
    <span className="auths-matrix-statuses">
      {[...byTone].map(([tone, names]) => (
        <span
          key={tone}
          className={`auths-matrix-state auths-matrix-state--${tone}`}
          role="img"
          aria-label={[...names].join(', ')}
          title={[...names].join(', ')}
        >
          <i />
        </span>
      ))}
    </span>
  );
}

function RelativeTime({ value }: { value: string | null }) {
  return (
    <time dateTime={value ?? undefined} title={value ? formatAuthDate(value) : undefined}>
      {formatRelativeTime(value)}
    </time>
  );
}

/** What several auths add up to: one value when they agree, a count when they don't. */
function summarise(values: (string | null)[], none: string, plural: string) {
  const distinct = [...new Set(values)];
  if (distinct.length === 1) {
    return distinct[0] === null ? <span className="auths-matrix-muted">{none}</span> : <code>{distinct[0]}</code>;
  }
  return <span>{distinct.length} {plural}</span>;
}

interface AuthsMatrixProps {
  auths: AuthCredential[];
  togglePending: boolean;
  deletePending: boolean;
  batchPending: boolean;
  onManage: (auth: AuthCredential) => void;
  onTest: (auth: AuthCredential) => void;
  onToggle: (auth: AuthCredential) => void;
  onDelete: (auth: AuthCredential) => void;
  onBatchTest: (auths: AuthCredential[]) => void;
  onBatchSetActive: (auths: AuthCredential[], active: boolean) => void;
  /** Shown at the start of the selection bar. */
  summary?: ReactNode;
}

/**
 * Every account in one table: health, routing, worker and whether it may
 * spend money. An account with several auths is one row that opens to show
 * them; rows can be selected to act on several at once.
 */
export function AuthsMatrix({
  auths,
  togglePending,
  deletePending,
  batchPending,
  onManage,
  onTest,
  onToggle,
  onDelete,
  onBatchTest,
  onBatchSetActive,
  summary,
}: AuthsMatrixProps) {
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const groups = useMemo(() => groupByUser(auths), [auths]);
  // Only what is still listed counts, so a filter change can't act on hidden rows.
  const selected = useMemo(() => auths.filter((auth) => picked.has(authKey(auth))), [auths, picked]);
  const allSelected = auths.length > 0 && selected.length === auths.length;
  const none = selected.length === 0 || batchPending;

  const setPickedFor = (targets: AuthCredential[], on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      for (const auth of targets) {
        if (on) next.add(authKey(auth));
        else next.delete(authKey(auth));
      }
      return next;
    });

  const toggleOpen = (key: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  /** An auth's row; `session` names it when it is one of several on an account. */
  const authRow = (auth: AuthCredential, session?: string) => {
    const nested = session !== undefined;
    const name = displayName(auth);
    const isSelected = picked.has(authKey(auth));
    const label = nested ? `${name} ${session}` : name;
    return (
      <tr
        key={authKey(auth)}
        className={`${nested ? 'is-nested' : ''}${isSelected ? ' is-selected' : ''}${auth.active ? '' : ' is-disabled'}`}
      >
        <td className="auths-matrix-check">
          <input type="checkbox" checked={isSelected} onChange={() => setPickedFor([auth], !isSelected)} aria-label={`Select ${label}`} />
        </td>
        <th scope="row" data-label="Account" className="auths-matrix-account">
          {nested ? (
            <span className="auths-matrix-session">{session}</span>
          ) : (
            <div className="auths-matrix-group-name">
              <span className="auths-matrix-caret-space" aria-hidden="true" />
              <div>
                <Link to={profilePath(auth)}>@{name}</Link>
                <small>
                  <SiteName site={auth.site} /> · UID {auth.user_id}
                </small>
              </div>
            </div>
          )}
        </th>
        <td data-label="Status">
          <StatusDot status={auth.status} />
        </td>
        <td data-label="Proxy" className="auths-matrix-col-proxy">{auth.proxy_id ? <code>{auth.proxy_id}</code> : <span className="auths-matrix-muted">Direct</span>}</td>
        <td data-label="Worker">
          {auth.worker_shard !== null ? (
            <code title="Worker shard">Shard {auth.worker_shard}</code>
          ) : (
            <span className="auths-matrix-muted">No worker</span>
          )}
        </td>
        <td data-label="Spending">{!nested && <Spending auth={auth} />}</td>
        <td data-label="Active">
          <label className="auths-matrix-switch">
            <input
              type="checkbox"
              role="switch"
              checked={auth.active}
              disabled={togglePending}
              onChange={() => onToggle(auth)}
              aria-label={`${label} active`}
            />
            <span aria-hidden="true" />
          </label>
        </td>
        <td data-label="Added" className="auths-matrix-date auths-matrix-col-added">
          <RelativeTime value={auth.created_at} />
        </td>
        <td data-label="Last tested" className="auths-matrix-date">
          <RelativeTime value={auth.last_tested_at} />
        </td>
        <td data-label="Actions" className="auths-matrix-actions">
          <button type="button" className="auths-matrix-link" onClick={() => onTest(auth)}>
            Test
          </button>
          <button type="button" className="auths-matrix-link" onClick={() => onManage(auth)}>
            Manage
          </button>
          <button
            type="button"
            className="auths-matrix-link auths-matrix-link--danger"
            disabled={deletePending}
            onClick={() => onDelete(auth)}
          >
            Delete
          </button>
        </td>
      </tr>
    );
  };

  /** An account's auths, oldest first, each named by its place and the OS it came from. */
  const sessionRows = (group: UserGroup) =>
    [...group.auths]
      .sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? '') || a.id - b.id)
      .map((auth, index) => {
        const platform = platformOf(auth.user_agent_preview);
        return authRow(auth, `Session ${index + 1}${platform ? ` · ${platform}` : ''}`);
      });

  const groupRow = (group: UserGroup) => {
    const first = group.auths[0];
    const isOpen = open.has(group.key);
    const pickedCount = group.auths.filter((auth) => picked.has(authKey(auth))).length;
    const active = group.auths.filter((auth) => auth.active).length;
    const lastTested = group.auths
      .map((auth) => auth.last_tested_at)
      .filter((value): value is string => value !== null)
      .sort()
      .at(-1);
    return (
      <tr
        key={group.key}
        className={`is-group${isOpen ? ' is-open' : ''}${pickedCount > 0 ? ' is-selected' : ''}${active === 0 ? ' is-disabled' : ''}`}
      >
        <td className="auths-matrix-check">
          <input
            type="checkbox"
            checked={pickedCount === group.auths.length}
            ref={(element) => {
              if (element) element.indeterminate = pickedCount > 0 && pickedCount < group.auths.length;
            }}
            onChange={() => setPickedFor(group.auths, pickedCount < group.auths.length)}
            aria-label={`Select all of ${group.name}'s auths`}
          />
        </td>
        <th scope="row" data-label="Account" className="auths-matrix-account">
          <div className="auths-matrix-group-name">
            <button
              type="button"
              className="auths-matrix-caret"
              aria-expanded={isOpen}
              aria-label={`${isOpen ? 'Hide' : 'Show'} ${group.name}'s ${group.auths.length} auths`}
              onClick={() => toggleOpen(group.key)}
            >
              <span aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
            </button>
            <div>
              <Link to={profilePath(first)}>@{group.name}</Link>
              <small>
                <SiteName site={first.site} /> · UID {first.user_id}
              </small>
            </div>
          </div>
        </th>
        <td data-label="Status">
          <StatusDots statuses={group.auths.map((auth) => auth.status)} />
        </td>
        <td data-label="Proxy" className="auths-matrix-col-proxy">{summarise(group.auths.map((auth) => auth.proxy_id), 'Direct', 'proxies')}</td>
        <td data-label="Auths">
          <span className="auths-matrix-count">{group.auths.length} auths</span>
        </td>
        <td data-label="Spending">
          <Spending auth={first} />
        </td>
        <td data-label="Active">
          <span className={active === 0 ? 'auths-matrix-muted' : undefined}>
            {active} of {group.auths.length}
          </span>
        </td>
        <td className="auths-matrix-date auths-matrix-col-added" />
        <td data-label="Last tested" className="auths-matrix-date">
          <RelativeTime value={lastTested ?? null} />
        </td>
        <td data-label="Actions" className="auths-matrix-actions">
          <button
            type="button"
            className="auths-matrix-link"
            disabled={batchPending}
            onClick={() => onBatchTest(group.auths)}
          >
            Test all
          </button>
          <button type="button" className="auths-matrix-link" onClick={() => toggleOpen(group.key)}>
            {isOpen ? 'Hide' : 'Show'}
          </button>
        </td>
      </tr>
    );
  };

  return (
    <section className="auths-matrix" aria-label="Accounts">
      {/* Always shown, so ticking a box never moves the rows under the pointer. */}
      <div className={`auths-matrix-dock${selected.length === 0 ? ' is-empty' : ''}`} role="toolbar" aria-label="Selected auths">
        {summary}
        <span className="auths-matrix-dock-count">
          {selected.length > 0 ? `${selected.length} selected` : 'Tick auths to act on several'}
        </span>
        <button type="button" className="filter-bar__filters-btn" disabled={none} onClick={() => onBatchTest(selected)}>
          Test
        </button>
        <button type="button" className="filter-bar__filters-btn" disabled={none} onClick={() => onBatchSetActive(selected, true)}>
          Enable
        </button>
        <button type="button" className="filter-bar__filters-btn" disabled={none} onClick={() => onBatchSetActive(selected, false)}>
          Disable
        </button>
        {selected.length > 0 && (
          <button type="button" className="auths-matrix-link" onClick={() => setPicked(new Set())}>
            Clear selection
          </button>
        )}
        {batchPending && <span className="auths-matrix-muted">Working…</span>}
      </div>

      <div className="auths-matrix-frame">
        <table className="auths-matrix-table">
          <thead>
            <tr>
              <th className="auths-matrix-check">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(event) => setPicked(event.target.checked ? new Set(auths.map(authKey)) : new Set())}
                  aria-label="Select all auths"
                />
              </th>
              <th>Account</th>
              <th>Status</th>
              <th className="auths-matrix-col-proxy">Proxy</th>
              <th title="How many auths an account has; for a single auth, its worker">Auths</th>
              <th>Spending</th>
              <th>Active</th>
              <th className="auths-matrix-col-added">Added</th>
              <th>Tested</th>
              <th className="auths-matrix-actions-head">Actions</th>
            </tr>
          </thead>
          <tbody>
            {groups.flatMap((group) =>
              group.auths.length === 1
                ? [authRow(group.auths[0])]
                : [groupRow(group), ...(open.has(group.key) ? sessionRows(group) : [])],
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
