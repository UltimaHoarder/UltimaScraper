import { useState } from 'react';

import {
  isClusterInvite,
  joinCluster,
  previewClusterInvite,
  type ClusterInvitePreview,
  type ClusterJoinResult,
} from '../../api/webui';

/** Paste a cluster invite, see what it adds, then join. */
export function JoinClusterForm({
  onJoined,
  onCancel,
}: {
  onJoined: (result: ClusterJoinResult) => void;
  onCancel?: () => void;
}) {
  const [invite, setInvite] = useState('');
  const [preview, setPreview] = useState<ClusterInvitePreview | null>(null);
  const [error, setError] = useState('');
  const [joining, setJoining] = useState(false);

  const change = async (value: string) => {
    setInvite(value);
    setPreview(null);
    setError('');
    if (!value.trim()) return;
    if (!isClusterInvite(value)) {
      setError('That is not a cluster invite (usr://cluster/…). A connection ticket for one backend goes under Connect a backend.');
      return;
    }
    try {
      setPreview(await previewClusterInvite(value));
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : 'The invite could not be read.');
    }
  };

  const join = async () => {
    setJoining(true);
    setError('');
    try {
      const result = await joinCluster(invite);
      setInvite('');
      setPreview(null);
      onJoined(result);
    } catch (joinError) {
      setError(joinError instanceof Error ? joinError.message : 'Could not join the cluster.');
    } finally {
      setJoining(false);
    }
  };

  const oneTime = preview?.version === 2;
  const adding = preview?.members.filter((member) => !member.already_connected) ?? [];
  const canJoin = oneTime ? preview?.verified === true : adding.length > 0;

  return (
    <section className="connections-form join-cluster" aria-label="Join a cluster">
      <label>
        <span>Cluster invite</span>
        <input
          value={invite}
          onChange={(event) => void change(event.target.value)}
          placeholder="Paste usr://cluster/… from another WebUI"
          spellCheck={false}
          autoFocus
        />
      </label>
      {error && (
        <p className="connections-error" role="alert">
          {error}
        </p>
      )}
      {preview && oneTime && (
        <div className="cluster-panel-section">
          <p className="connections-copy">
            One-time invite, redeemed at <code className="connections-url">{preview.entry_url}</code>. Joining adds
            every backend of the cluster that serves HTTPS, and gives this WebUI its own credential.
          </p>
          {preview.verified ? (
            <p className="connections-status is-ok" role="status">
              Certificate verified ({preview.fingerprint?.slice(0, 23)}…)
            </p>
          ) : (
            <p className="connections-error" role="alert">
              {preview.error ?? 'The member could not be verified.'}
            </p>
          )}
        </div>
      )}
      {preview && !oneTime && (
        <div className="cluster-panel-section">
          <p className="connections-copy">
            <strong>{preview.name}</strong> · {preview.members.length} backend{preview.members.length === 1 ? '' : 's'}
          </p>
          <ul className="cluster-panel-list">
            {preview.members.map((member) => (
              <li key={member.backend_id}>
                <strong>{member.name}</strong>
                <code className="connections-url">{member.base_url}</code>
                {member.already_connected && <span className="connections-tag">Already here</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="connections-actions">
        <button
          type="button"
          className="connections-button is-primary"
          disabled={!preview || joining || !canJoin}
          onClick={() => void join()}
        >
          {joining ? 'Joining…' : preview && !oneTime && adding.length === 0 ? 'Nothing new to add' : 'Join'}
        </button>
        {onCancel && (
          <button type="button" className="connections-button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </section>
  );
}
