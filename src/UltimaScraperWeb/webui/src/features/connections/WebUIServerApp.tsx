import { useEffect, useState, type ReactNode } from 'react';

import { connectionIdFromPath, navigateTo } from '../../api/http';
import { connectionHome, getWebUISession, listConnections, type BackendConnection } from '../../api/webui';
import { SetupWizardPage } from '../setup-wizard/SetupWizardPage';
import { ConnectionsPage } from './ConnectionsPage';
import { WebUISignInGate } from './WebUISignInGate';
import { pickConnection, rememberConnection } from './lib/lastConnection';
import { followInApp, useLocationPath } from './lib/navigation';
import './signInCard.css';

function Notice({ children }: { children: ReactNode }) {
  return (
    <main className="admin-token-gate">
      <section className="admin-token-card">
        <p className="admin-token-eyebrow">UltimaScraper</p>
        {children}
      </section>
    </main>
  );
}

/**
 * A page path from before backends had their own /b/{connection} prefix, such
 * as a bookmarked /jobs, opened on the chosen backend.
 */
function backendPathFor(connectionId: string, { pathname, search, hash }: Pick<Location, 'pathname' | 'search' | 'hash'>): string {
  if (connectionId === 'default') {
    return pathname === '/' ? '/' : `${pathname}${search}${hash}`;
  }
  const home = connectionHome(connectionId);
  return pathname === '/' ? home : `${home.replace(/\/$/, '')}${pathname}${search}${hash}`;
}

function RedirectToSetup() {
  useEffect(() => {
    navigateTo('/setup', { replace: true });
  }, []);
  return null;
}

/** Opens the last-used backend (or the deployment's), or the Setup wizard when there is none. */
function OpenBackend({
  renderBackend,
}: {
  renderBackend: (connectionId: string, basename: string) => ReactNode;
}) {
  const [targetId, setTargetId] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    // The page asked for, read before anything navigates.
    const requested = { pathname: window.location.pathname, search: window.location.search, hash: window.location.hash };
    let current = true;
    Promise.all([listConnections(), getWebUISession()]).then(([connections, session]) => {
      if (!current) return;
      const target = pickConnection(connections, session.default_connection, session.main_connections);
      if (!target) {
        navigateTo('/setup', { replace: true });
        return;
      }
      if (target.id !== 'default') {
        navigateTo(backendPathFor(target.id, requested), { replace: true });
        return;
      }
      setTargetId('default');
    }, () => current && setFailed(true));
    return () => {
      current = false;
    };
  }, []);

  if (targetId === 'default') {
    return (
      <BackendApp connectionId="default">
        {renderBackend('default', '')}
      </BackendApp>
    );
  }

  return (
    <Notice>
      <p className="admin-token-copy" role={failed ? 'alert' : 'status'}>
        {failed ? 'Could not load your backends. Reload the page to try again.' : 'Opening your backend…'}
      </p>
    </Notice>
  );
}

type KnownConnections = { list: BackendConnection[]; fetchedFor: string } | 'failed' | null;

/**
 * Renders the app for one backend, after checking this WebUI knows it. The
 * list is kept across switches and fetched again only for an id it lacks.
 */
function BackendApp({ connectionId, children }: { connectionId: string; children: ReactNode }) {
  const [known, setKnown] = useState<KnownConnections>(null);
  const needsFetch =
    known === null ||
    (known !== 'failed' &&
      known.fetchedFor !== connectionId &&
      !known.list.some((entry) => entry.id === connectionId));

  useEffect(() => {
    if (!needsFetch) return;
    let current = true;
    listConnections().then(
      (list) => current && setKnown({ list, fetchedFor: connectionId }),
      () => current && setKnown('failed'),
    );
    return () => {
      current = false;
    };
  }, [connectionId, needsFetch]);

  const connection =
    known && known !== 'failed' ? known.list.find((entry) => entry.id === connectionId) ?? null : null;

  useEffect(() => {
    if (connection) rememberConnection(connection.id);
  }, [connection]);

  if (needsFetch) {
    return (
      <Notice>
        <p className="admin-token-copy" role="status">Connecting…</p>
      </Notice>
    );
  }
  if (connection === null) {
    if (connectionId === 'default' && known && known !== 'failed' && known.list.length === 0) {
      navigateTo('/setup', { replace: true });
      return null;
    }
    return (
      <Notice>
        <h1>Unknown backend</h1>
        <p className="admin-token-copy">
          This WebUI has no backend called “{connectionId}”. <a href="/connections" onClick={(event) => followInApp(event, '/connections')}>Choose a backend</a>.
        </p>
      </Notice>
    );
  }
  return children;
}

/**
 * The app as served by the WebUI server: sign in, then either the Backends page
 * (/connections) or the full app for one backend (default local at /, or remote under /b/{connection}/).
 * Moving between them, or between backends, does not reload the page: each
 * backend's app remounts with its own cache (see AppProviders).
 */
export function WebUIServerApp({
  renderBackend,
}: {
  renderBackend: (connectionId: string, basename: string) => ReactNode;
}) {
  const path = useLocationPath();
  const connectionId = connectionIdFromPath(path);

  let content: ReactNode;
  if (connectionId !== null) {
    if (connectionId === 'default') {
      const cleanPath = path.replace(/^\/b\/default(?:\/|$)/, '/') || '/';
      const search = window.location.search || '';
      const hash = window.location.hash || '';
      navigateTo(`${cleanPath}${search}${hash}`, { replace: true });
      return null;
    }
    content = (
      <BackendApp connectionId={connectionId}>
        {renderBackend(connectionId, `/b/${encodeURIComponent(connectionId)}`)}
      </BackendApp>
    );
  } else if (path === '/setup' || path.startsWith('/setup/')) {
    content = <SetupWizardPage />;
  } else if (path === '/connections/deploy') {
    content = <RedirectToSetup />;
  } else if (path === '/connections' || path.startsWith('/connections/')) {
    content = <ConnectionsPage />;
  } else {
    content = <OpenBackend renderBackend={renderBackend} />;
  }

  return <WebUISignInGate>{content}</WebUISignInGate>;
}
