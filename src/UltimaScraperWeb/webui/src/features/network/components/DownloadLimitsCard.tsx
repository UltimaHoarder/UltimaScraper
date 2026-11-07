import { useState, type FormEvent } from 'react';

import type { DownloadLimits } from '../hooks/useNetworkDownloadLimits';
import {
  parseDownloadLimits,
  toDownloadLimitsDraft,
  type DownloadLimitsDraft,
} from '../lib/downloadLimits';

const FIELDS: { key: keyof DownloadLimits; label: string; help: string }[] = [
  {
    key: 'max_concurrency',
    label: 'Max concurrency',
    help: 'Parts transferring at once in one download task.',
  },
  {
    key: 'per_domain_concurrency',
    label: 'Per-domain concurrency',
    help: 'Connections to one host, such as the OnlyFans CDN. A large file can use them all.',
  },
  {
    key: 'head_concurrency',
    label: 'HEAD concurrency',
    help: 'Size checks running at once.',
  },
];

interface DownloadLimitsCardProps {
  limits: DownloadLimits | null;
  isLoading: boolean;
  loadError: Error | null;
  isSaving: boolean;
  saveError: Error | null;
  onSave: (limits: DownloadLimits) => Promise<unknown>;
}

export function DownloadLimitsCard({
  limits,
  isLoading,
  loadError,
  isSaving,
  saveError,
  onSave,
}: DownloadLimitsCardProps) {
  const [draft, setDraft] = useState<DownloadLimitsDraft | null>(
    limits ? toDownloadLimitsDraft(limits) : null,
  );
  const [saved, setSaved] = useState(false);

  // Start again from the saved values whenever they change.
  const savedKey = limits ? JSON.stringify(limits) : '';
  const [shownKey, setShownKey] = useState(savedKey);
  if (limits && savedKey !== shownKey) {
    setShownKey(savedKey);
    setDraft(toDownloadLimitsDraft(limits));
  }

  const parsed = draft ? parseDownloadLimits(draft) : null;
  const changed = Boolean(
    parsed && limits && FIELDS.some(({ key }) => parsed[key] !== limits[key]),
  );

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!parsed || !changed) {
      return;
    }
    setSaved(false);
    try {
      await onSave(parsed);
      setSaved(true);
    } catch {
      // saveError shows the reason.
    }
  };

  return (
    <article className="network-pool-card network-download-limits">
      {isLoading ? <p>Loading download limits…</p> : null}
      {loadError ? (
        <p className="network-download-limits__error" role="alert">
          Could not load download limits: {loadError.message}
        </p>
      ) : null}
      {draft ? (
        <form className="network-download-limits__form" onSubmit={handleSubmit}>
          <div className="network-download-limits__fields">
            {FIELDS.map(({ key, label, help }) => (
              <label key={key} className="network-download-limits__field">
                <span>{label}</span>
                <input
                  type="number"
                  min={1}
                  step={1}
                  inputMode="numeric"
                  value={draft[key]}
                  onChange={(event) => {
                    setSaved(false);
                    setDraft({ ...draft, [key]: event.target.value });
                  }}
                />
                <small>{help}</small>
              </label>
            ))}
          </div>
          <div className="network-download-limits__footer">
            <p>New downloads use these; ones already running keep their limits.</p>
            <button
              type="submit"
              className="network-button network-button--primary"
              disabled={!parsed || !changed || isSaving}
            >
              {isSaving ? 'Saving…' : 'Save limits'}
            </button>
          </div>
          {!parsed ? (
            <p className="network-download-limits__error" role="alert">
              Each limit must be a whole number of at least 1.
            </p>
          ) : null}
          {saveError ? (
            <p className="network-download-limits__error" role="alert">
              Could not save: {saveError.message}
            </p>
          ) : null}
          {saved && !changed ? (
            <p className="network-download-limits__saved" role="status">Saved.</p>
          ) : null}
        </form>
      ) : null}
    </article>
  );
}
