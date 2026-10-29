import type { PluginSecretRecord } from '../../../api/types/plugins';

function formatSecretScope(secret: PluginSecretRecord): string {
  if (secret.scope_kind === 'remote_auth') {
    if (secret.scope_name === 'public_api') {
      return 'Remote Auth Scope: public_api (public API key)';
    }
    if (secret.scope_name === 'worker_api') {
      return 'Remote Auth Scope: worker_api (worker token)';
    }
    return `Remote Auth Scope: ${secret.scope_name}`;
  }
  if (secret.scope_kind === 'callback') {
    return `Callback Verifier: ${secret.scope_name}`;
  }
  if (secret.scope_kind === 'outbound') {
    return `Outbound Signer: ${secret.scope_name}`;
  }
  return `${secret.scope_kind}: ${secret.scope_name}`;
}

export function PluginManifestEditor({
  pluginId,
  manifestYaml,
  secrets,
  secretDrafts,
  onChange,
  onSave,
  onSecretDraftChange,
  onSetSecret,
  onCancel,
  isSaving,
  isSavingSecret,
  isLoading,
}: {
  pluginId: string;
  manifestYaml: string;
  secrets: PluginSecretRecord[];
  secretDrafts: Record<string, string>;
  onChange: (value: string) => void;
  onSave: () => void;
  onSecretDraftChange: (scopeKey: string, value: string) => void;
  onSetSecret: (scopeKind: string, scopeName: string) => void;
  onCancel: () => void;
  isSaving: boolean;
  isSavingSecret: boolean;
  isLoading: boolean;
}) {
  const visibleSecrets = secrets.filter((secret) => secret.scope_kind !== 'remote_integration');

  return (
    <div className="plugins-create-panel">
      <div className="plugins-create-header">
        <h3>Edit Plugin Manifest</h3>
      </div>
      <div className="plugins-editor-note">
        Editing raw YAML for <strong>{pluginId}</strong>. Saving validates the manifest and reloads the plugin.
      </div>
      <div className="plugins-section">
        <div className="plugins-section-title">Secrets</div>
        <div className="plugins-editor-note">
          Secrets are stored outside the manifest. Keep remote API credentials and callback verifier secrets in their separate scopes.
        </div>
        {visibleSecrets.length === 0 ? (
          <div className="plugins-muted-copy">No secret scopes are registered for this plugin yet.</div>
        ) : (
          <div className="plugins-list-editor">
            {visibleSecrets.map((secret) => {
              const scopeKey = `${secret.scope_kind}:${secret.scope_name}`;
              return (
                <div key={scopeKey} className="plugins-list-item">
                  <div className="plugins-list-item-header">
                    <span>{formatSecretScope(secret)}</span>
                    <span className="plugins-secret-timestamp">
                      {secret.rotated_at ? 'Updated' : 'Created'}{' '}
                      {new Date(secret.rotated_at ?? secret.created_at).toLocaleString()}
                    </span>
                  </div>
                  <div className="plugins-field-row">
                    <div className="plugins-field">
                      <label>Secret Value</label>
                      <input
                        type="password"
                        value={secretDrafts[scopeKey] ?? ''}
                        onChange={(event) => onSecretDraftChange(scopeKey, event.target.value)}
                        placeholder="Paste secret value"
                        autoComplete="off"
                        disabled={isLoading || isSavingSecret}
                      />
                    </div>
                    <div className="plugins-field plugins-field--action">
                      <button
                        type="button"
                        className="plugins-submit-btn"
                        disabled={isLoading || isSavingSecret || !(secretDrafts[scopeKey] ?? '').trim()}
                        onClick={() => onSetSecret(secret.scope_kind, secret.scope_name)}
                      >
                        {isSavingSecret ? 'Saving...' : 'Save Secret'}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="plugins-section">
        <div className="plugins-section-title">Manifest YAML</div>
        <textarea
          aria-label="Manifest YAML"
          className="plugins-manifest-textarea"
          value={manifestYaml}
          onChange={(event) => onChange(event.target.value)}
          spellCheck={false}
          disabled={isLoading || isSaving}
        />
      </div>
      <div className="plugins-form-actions">
        <button type="button" className="plugins-cancel-btn" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="plugins-submit-btn"
          disabled={isLoading || isSaving || manifestYaml.trim().length === 0}
          onClick={onSave}
        >
          {isLoading ? 'Loading...' : isSaving ? 'Saving...' : 'Save Manifest'}
        </button>
      </div>
    </div>
  );
}
