import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';

import {
  detectHost,
  listDeployments,
  operateDeployment,
  type Deployment,
} from '../../api/webui';
import { RunLog } from './RunLog';
import { useInstallRun } from './lib/useInstallRun';
import { normalizeImagePrefix } from '../setup-wizard/lib/imageVersion';
import { ACTION_HINTS, ACTION_LABELS, type Action } from './lib/deploymentActions';

export function OperationPanel({
  deployment,
  action,
  initialCredentials,
  onClose,
  onFinished,
}: {
  deployment: Deployment;
  action: Action;
  initialCredentials?: {
    authMethod?: 'password' | 'key';
    password?: string;
    privateKey?: string;
    sudoPassword?: string;
  };
  onClose: () => void;
  onFinished: () => void;
}) {
  const ssh = deployment.details.kind === 'ssh';
  const [authMethod, setAuthMethod] = useState<'password' | 'key'>(initialCredentials?.authMethod ?? 'password');
  const [password, setPassword] = useState(initialCredentials?.password ?? '');
  const [privateKey, setPrivateKey] = useState(initialCredentials?.privateKey ?? '');
  const [sudoPassword, setSudoPassword] = useState(initialCredentials?.sudoPassword ?? '');
  const [localNeedsSudoPassword, setLocalNeedsSudoPassword] = useState(false);
  // Starts on the running version: re-pulling a moving tag such as edge is the usual upgrade.
  const [version, setVersion] = useState(deployment.details.version ?? '');
  const [imageSource, setImageSource] = useState(deployment.details.image_source || 'copy');
  const [imagePrefix, setImagePrefix] = useState(deployment.details.image_prefix ?? '');
  const [deleteData, setDeleteData] = useState(false);
  const [removeFiles, setRemoveFiles] = useState(true);
  const [webuiPassword, setWebuiPassword] = useState('');
  const [error, setError] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const { status, events } = useInstallRun(runId);
  const finished = status !== null && status.state !== 'running';

  useEffect(() => {
    if (ssh) return;
    let active = true;
    detectHost({
      target: { kind: 'local' },
      install_dir: deployment.details.install_dir,
    })
      .then((res) => {
        if (!active) return;
        setLocalNeedsSudoPassword(
          res.needs_sudo_for.length > 0 && res.facts.sudo_mode === 'password',
        );
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [deployment.details.install_dir, ssh]);

  // Report each run once, however often the parent re-renders.
  const reportedRun = useRef<string | null>(null);
  useEffect(() => {
    if (!finished || !runId || reportedRun.current === runId) return;
    reportedRun.current = runId;
    onFinished();
  }, [finished, runId, onFinished]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    if (action === 'uninstall' && deleteData && !window.confirm(`Delete all of ${deployment.name}'s data? This cannot be undone.`)) {
      return;
    }
    try {
      const started = await operateDeployment(deployment.id, {
        action,
        credentials: {
          password: ssh && authMethod === 'password' ? password : undefined,
          private_key: ssh && authMethod === 'key' ? privateKey : undefined,
          sudo_password: sudoPassword || undefined,
        },
        ...(action === 'upgrade'
          ? { version: version.trim(), image_source: imageSource, image_prefix: normalizeImagePrefix(imagePrefix) || undefined }
          : {}),
        ...(action === 'uninstall'
          ? { delete_data: deleteData, remove_files: removeFiles, webui_password: webuiPassword }
          : {}),
      });
      setRunId(started.id);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : 'The operation did not start.');
    }
  };

  if (runId) {
    return (
      <div className="deployment-panel">
        <RunLog events={events} />
        {finished && (
          <div className="connections-actions">
            <button type="button" className="connections-button" onClick={onClose}>
              Close
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <form className="connections-form deployment-panel" onSubmit={submit}>
      <p className="connections-copy">{ACTION_HINTS[action]}</p>
      {error && <p className="connections-error" role="alert">{error}</p>}
      {ssh && (
        <>
          <div className="deploy-choice">
            <label className="connections-checkbox">
              <input type="radio" checked={authMethod === 'password'} onChange={() => setAuthMethod('password')} />
              <span>SSH password</span>
            </label>
            <label className="connections-checkbox">
              <input type="radio" checked={authMethod === 'key'} onChange={() => setAuthMethod('key')} />
              <span>Private key</span>
            </label>
          </div>
          {authMethod === 'password' ? (
            <label>
              <span>Password for {deployment.details.username}@{deployment.details.host}</span>
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="off" required />
            </label>
          ) : (
            <label>
              <span>Private key</span>
              <textarea rows={4} value={privateKey} onChange={(event) => setPrivateKey(event.target.value)} spellCheck={false} required />
            </label>
          )}
        </>
      )}
      {(ssh || localNeedsSudoPassword) && (
        <label>
          <span>{ssh ? 'sudo password (optional)' : 'sudo password'}</span>
          <input
            type="password"
            value={sudoPassword}
            onChange={(event) => setSudoPassword(event.target.value)}
            autoComplete="off"
            required={!ssh && localNeedsSudoPassword}
          />
        </label>
      )}
      {action === 'upgrade' && (
        <div className="deploy-row">
          <label>
            <span>Images</span>
            <select value={imageSource} onChange={(event) => setImageSource(event.target.value as typeof imageSource)}>
              <option value="copy">Copy from this server</option>
              <option value="target">Already on the host</option>
              <option value="registry">Pull from a registry</option>
            </select>
          </label>
          <label className="deploy-port">
            <span>Version</span>
            <input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="0.2.0" required />
          </label>
        </div>
      )}
      {action === 'upgrade' && version.trim() === deployment.details.version && (
        <p className="deploy-note">
          {deployment.name} runs {deployment.details.version}. Upgrading to it again pulls the newest build of
          that tag; enter another version to switch.
        </p>
      )}
      {action === 'upgrade' && imageSource === 'registry' && (
        <label>
          <span>Registry</span>
          <input
            value={imagePrefix}
            placeholder="forgejo.example/org/ultimascraper"
            onChange={(event) => setImagePrefix(event.target.value)}
            onBlur={() => setImagePrefix((prev) => normalizeImagePrefix(prev))}
            spellCheck={false}
            required
          />
        </label>
      )}
      {action === 'uninstall' && (
        <>
          <label className="connections-checkbox">
            <input type="checkbox" checked={removeFiles} onChange={(event) => setRemoveFiles(event.target.checked)} />
            <span>Remove {deployment.details.install_dir}</span>
          </label>
          <label className="connections-checkbox">
            <input type="checkbox" checked={deleteData} onChange={(event) => setDeleteData(event.target.checked)} />
            <span>
              {deployment.details.components?.postgres
                ? 'Also delete its data (database, downloads metadata, settings)'
                : 'Also delete local container data (logs, local cache, TLS certs) — cluster database will NOT be touched'}
            </span>
          </label>
          <label>
            <span>Your WebUI password, to confirm</span>
            <input
              type="password"
              value={webuiPassword}
              onChange={(event) => setWebuiPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
        </>
      )}
      <div className="connections-actions">
        <button type="submit" className={`connections-button ${action === 'uninstall' ? 'is-danger' : 'is-primary'}`}>
          {ACTION_LABELS[action]}
        </button>
        <button type="button" className="connections-button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** What this WebUI installed, with repair, upgrade and uninstall. */
export function DeploymentsSection({ onChanged }: { onChanged: () => void }) {
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [open, setOpen] = useState<{ id: string; action: Action } | null>(null);

  const load = useCallback(() => {
    listDeployments().then(setDeployments, () => setDeployments([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const finished = useCallback(() => {
    load();
    onChanged();
  }, [load, onChanged]);

  if (deployments.length === 0) return null;

  return (
    <section className="deployments" aria-labelledby="deployments-title">
      <h2 id="deployments-title">Deployments</h2>
      <ul className="connections-list">
        {deployments.map((deployment) => (
          <li key={deployment.id} className="connections-row deployment-row">
            <div className="connections-row-main">
              <strong>{deployment.name}</strong>
              <span className="connections-tag" title="The image tag this deployment follows">
                {deployment.details.version}
              </span>
              {deployment.details.image_version && deployment.details.image_version !== deployment.details.version && (
                <span className="connections-tag" title="The build that tag pointed to at the last install, upgrade or repair">
                  {deployment.details.image_version}
                </span>
              )}
              <span className="connections-tag">{deployment.details.architecture}</span>
              <code className="connections-url">
                {deployment.target}:{deployment.details.install_dir}
              </code>
            </div>
            <div className="connections-actions">
              {(['repair', 'upgrade', 'uninstall'] as Action[]).map((action) => (
                <button
                  key={action}
                  type="button"
                  className="connections-button"
                  aria-expanded={open?.id === deployment.id && open.action === action}
                  onClick={() => setOpen({ id: deployment.id, action })}
                >
                  {ACTION_LABELS[action]}
                </button>
              ))}
            </div>
            {open?.id === deployment.id && (
              <OperationPanel
                key={open.action}
                deployment={deployment}
                action={open.action}
                onClose={() => setOpen(null)}
                onFinished={finished}
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
