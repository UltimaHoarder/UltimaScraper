import { useEffect, useState, type FormEvent, type ReactNode } from 'react';

import { addConnection, isClusterInvite } from '../../../api/webui';
import { parseTicketString } from '../../connections/lib/ticket';
import { SetupWizardPage } from '../../setup-wizard/SetupWizardPage';

type View = 'choose' | 'install' | 'connect';

const TITLES: Record<View, string> = {
  choose: 'Add host',
  install: 'Install',
  connect: 'Connect a running backend',
};

function Choice({ title, text, onClick }: { title: string; text: string; onClick: () => void }) {
  return (
    <button type="button" className="add-host-choice" onClick={onClick}>
      <strong>{title}</strong>
      <span>{text}</span>
    </button>
  );
}

/** Just the form for adding one backend by its address, or a ticket. */
function ConnectBackendForm({ onAdded }: { onAdded: (name: string) => void }) {
  const [ticket, setTicket] = useState('');
  const [ticketNote, setTicketNote] = useState('');
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [token, setToken] = useState('');
  const [tlsVerify, setTlsVerify] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const readTicket = (value: string) => {
    setTicket(value);
    setTicketNote('');
    if (!value.trim()) return;
    if (isClusterInvite(value)) {
      setTicketNote('That is a cluster invite: on the other WebUI it is for, use it in Set up under Join a cluster, not Connect.');
      return;
    }
    const parsed = parseTicketString(value);
    if (!parsed) {
      setTicketNote('That is not a connection ticket.');
      return;
    }
    setName(parsed.name);
    setBaseUrl(parsed.base_url);
    setToken(parsed.token ?? '');
    setTlsVerify(parsed.tls_verify);
    setTicketNote(`Filled in from the ticket for ${parsed.name}.`);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const created = await addConnection({
        name: name.trim(),
        base_url: baseUrl.trim(),
        token: token.trim() || null,
        tls_verify: tlsVerify,
      });
      onAdded(created.name);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Could not add the backend.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="connections-form" onSubmit={submit}>
      <label>
        <span>Connection ticket (optional)</span>
        <input value={ticket} onChange={(event) => readTicket(event.target.value)} placeholder="usr://ticket/…" spellCheck={false} />
      </label>
      {ticketNote && <p className="connections-hint">{ticketNote}</p>}
      <label>
        <span>Name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={60} />
      </label>
      <label>
        <span>Address</span>
        <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://192.168.1.20:8443" required spellCheck={false} />
      </label>
      <label>
        <span>Admin token</span>
        <input type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" />
      </label>
      <label className="connections-checkbox">
        <input type="checkbox" checked={tlsVerify} onChange={(event) => setTlsVerify(event.target.checked)} />
        <span>Verify its HTTPS certificate</span>
      </label>
      {error && <p className="connections-error" role="alert">{error}</p>}
      <div className="connections-actions">
        <button type="submit" className="fleet-register-button fleet-register-button--primary" disabled={saving}>
          {saving ? 'Connecting…' : 'Connect'}
        </button>
      </div>
    </form>
  );
}

/**
 * One place to grow a cluster: install on a local or remote host (the setup
 * wizard, for this cluster), or connect a backend that already runs. Another
 * WebUI is invited from the cluster page instead: it is not a host.
 */
export function AddHostModal({
  clusterId,
  clusterName,
  connectionId,
  onClose,
  onChanged,
}: {
  clusterId: string;
  clusterName: string;
  /** A connection to one of the cluster's backends. */
  connectionId: string | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [view, setView] = useState<View>('choose');
  const [added, setAdded] = useState('');

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  let body: ReactNode;
  if (view === 'choose') {
    body = (
      <div className="add-host-choices">
        <Choice
          title="Install"
          text={`Install a backend or workers on this machine (local) or another one over SSH (remote). They use ${clusterName}'s PostgreSQL and Redis.`}
          onClick={() => setView('install')}
        />
        <Choice
          title="Connect"
          text="Connect a backend that is already running: its address and admin token, or a connection ticket."
          onClick={() => setView('connect')}
        />
      </div>
    );
  } else if (view === 'install') {
    body = connectionId ? (
      <SetupWizardPage
        layout="modal"
        cluster={{ clusterId, connectionId, name: clusterName }}
        onDone={() => {
          onChanged();
          onClose();
        }}
      />
    ) : (
      <p className="connections-error" role="alert">
        This WebUI has no connection to a backend of {clusterName}, so it cannot read its PostgreSQL and Redis.
      </p>
    );
  } else {
    body = added ? (
      <div className="connections-form">
        <p className="connections-status is-ok" role="status">
          Connected {added}. If it shares {clusterName}&apos;s database, it appears among its hosts.
        </p>
        <div className="connections-actions">
          <button type="button" className="fleet-register-button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    ) : (
      <ConnectBackendForm
        onAdded={(name) => {
          setAdded(name);
          onChanged();
        }}
      />
    );
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <section
        className={`modal-content fleet-register-inspect-modal add-host-modal${view === 'install' ? ' is-wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-host-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="fleet-register-kicker">{clusterName}</span>
            <h3 id="add-host-title">{TITLES[view]}</h3>
          </div>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {view !== 'choose' && !(view === 'connect' && added) && (
            <button type="button" className="fleet-register-link add-host-back" onClick={() => setView('choose')}>
              ← Other ways to add a host
            </button>
          )}
          {body}
        </div>
      </section>
    </div>
  );
}
