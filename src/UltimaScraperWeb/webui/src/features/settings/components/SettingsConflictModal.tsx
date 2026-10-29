import {
  formatJson,
  type ConflictLeafEntry,
  type ConflictModalState,
  type MergeChoice,
} from '../lib/settingsUtils';

interface SettingsConflictModalProps {
  conflictState: ConflictModalState;
  conflictEntriesByTopField: Record<string, ConflictLeafEntry[]>;
  conflictChoices: Record<string, MergeChoice>;
  conflictSaveError: string | null;
  onChoiceChange: (path: string, choice: MergeChoice) => void;
  onDiscard: () => void;
  onMerge: () => void;
}

export function SettingsConflictModal({
  conflictState,
  conflictEntriesByTopField,
  conflictChoices,
  conflictSaveError,
  onChoiceChange,
  onDiscard,
  onMerge,
}: SettingsConflictModalProps) {
  return (
    <div className="conflict-overlay" role="dialog" aria-modal="true">
      <div className="conflict-modal">
        <h3>Settings Conflict Detected</h3>
        <p className="section-description">
          Another backend updated this settings row before your save completed.
          {conflictState.currentVersion !== null
            ? ` Current version: ${conflictState.currentVersion}.`
            : ''}
          {conflictState.currentUpdatedAt
            ? ` Updated at: ${conflictState.currentUpdatedAt}.`
            : ''}
        </p>

        <div className="conflict-list">
          {Object.entries(conflictEntriesByTopField).map(([topField, entries]) => (
            <div key={topField} className="conflict-item">
              <div className="conflict-header">
                <span className="conflict-field">{topField}</span>
                {entries.some((entry) => entry.isConflict) && (
                  <span className="conflict-badge">conflict</span>
                )}
              </div>
              {entries.map((entry) => (
                <div key={entry.path} className="conflict-nested-row">
                  <div className="conflict-path">
                    {entry.pathParts.length > 1 ? entry.pathParts.slice(1).join('.') : topField}
                  </div>
                  <div className="conflict-columns">
                    <label className="conflict-choice">
                      <input
                        type="radio"
                        name={`choice-${entry.path.replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                        checked={(conflictChoices[entry.path] ?? 'local') === 'local'}
                        onChange={() => onChoiceChange(entry.path, 'local')}
                      />
                      <span>Local</span>
                      <pre>{formatJson(entry.localValue)}</pre>
                    </label>
                    <label className="conflict-choice">
                      <input
                        type="radio"
                        name={`choice-${entry.path.replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                        checked={(conflictChoices[entry.path] ?? 'local') === 'remote'}
                        onChange={() => onChoiceChange(entry.path, 'remote')}
                      />
                      <span>Remote</span>
                      <pre>{formatJson(entry.remoteValue)}</pre>
                    </label>
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>

        {conflictSaveError && <div className="error-message">{conflictSaveError}</div>}

        <div className="conflict-actions">
          <button className="btn-reset" onClick={onDiscard}>
            Discard Local
          </button>
          <button className="btn-save" onClick={onMerge}>
            Merge & Save
          </button>
        </div>
      </div>
    </div>
  );
}
