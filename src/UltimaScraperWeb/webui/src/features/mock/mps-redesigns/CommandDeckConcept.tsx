import { useEffect, useState } from 'react';

import { NumberField, Segmented } from './controls';
import {
  MOCK_SITES,
  PROXY_MODE_LABELS,
  fmt,
  formatMinutes,
  jobLabel,
  type ConceptProps,
  type MockProxyMode,
} from './mpsMockModel';

type CheckState = 'pass' | 'warn' | 'fail';

/** Concept 02 — dense single screen: inputs, a live command string, and preflight checks. */
export function CommandDeckConcept({ model, onLaunch }: ConceptProps) {
  const { config, derived, update, setSite } = model;
  const [copied, setCopied] = useState(false);

  const sources = [
    config.includeMissing ? 'missing' : null,
    config.includeInvalid ? `notfound@${config.recheckDays}d` : null,
    config.includeExisting ? `existing@${config.recheckDays}d` : null,
  ].filter(Boolean);
  const routeSpec =
    config.proxyMode === 'none'
      ? 'direct'
      : `${config.proxyMode}(${derived.routeCount - (config.includeDirect ? 1 : 0)})${config.includeDirect ? '+direct' : ''}`;
  const command = [
    'mps run',
    `--site ${config.site}`,
    `--ids ${config.startId}..${config.endId}`,
    `--sources ${sources.join(',') || '∅'}`,
    `--batch ${config.batchSize}`,
    `--routes ${routeSpec}`,
    `--hops ${config.maxRouteHops}`,
    `--miss ${config.missThreshold}`,
    config.jobName.trim() ? `--name "${config.jobName.trim()}"` : null,
  ]
    .filter(Boolean)
    .join(' ');

  const checks: Array<{ label: string; detail: string; state: CheckState }> = [
    {
      label: 'Range',
      detail: derived.rangeSize > 0 ? `${fmt(derived.rangeSize)} IDs` : 'End is before start',
      state: derived.rangeSize > 0 ? 'pass' : 'fail',
    },
    {
      label: 'Sources',
      detail: derived.sourceCount > 0 ? `${derived.sourceCount} selected` : 'Select at least one',
      state: derived.sourceCount > 0 ? 'pass' : 'fail',
    },
    {
      label: 'Candidates',
      detail: `${fmt(derived.candidates)} resolved`,
      state: derived.candidates > 0 ? 'pass' : 'fail',
    },
    {
      label: 'Route load',
      detail: `${fmt(derived.profilesPerRoute)} / route`,
      state: derived.profilesPerRoute >= 1_000 ? 'warn' : 'pass',
    },
    {
      label: 'Cooldown',
      detail: config.includeExisting || config.includeInvalid ? `${config.recheckDays}d` : 'n/a',
      state: (config.includeExisting || config.includeInvalid) && config.recheckDays < 1 ? 'warn' : 'pass',
    },
  ];
  const blocked = checks.some((check) => check.state === 'fail');

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1_500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !blocked) {
        event.preventDefault();
        onLaunch(`${jobLabel(config)} via ⌘/Ctrl+Enter: ${fmt(derived.selected)} profiles`);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [blocked, config, derived.selected, onLaunch]);

  return (
    <div className="mps-lab-deck">
      <aside className="mps-lab-deck__inputs" aria-label="Inputs">
        <h4>Scope</h4>
        <Segmented label="Site" value={config.site} options={MOCK_SITES.map((site) => ({ value: site, label: site }))} onChange={setSite} />
        <div className="mps-lab-grid-2 tight">
          <NumberField label="From" value={config.startId} onChange={(startId) => update({ startId })} />
          <NumberField label="To" value={config.endId} onChange={(endId) => update({ endId })} />
        </div>

        <h4>Sources</h4>
        <div className="mps-lab-tokens">
          {(
            [
              ['includeMissing', 'missing', derived.missing],
              ['includeInvalid', 'not-found', derived.invalidEligible],
              ['includeExisting', 'existing', derived.existingEligible],
            ] as const
          ).map(([key, label, count]) => (
            <button key={key} type="button" aria-pressed={config[key]} className={config[key] ? 'on' : ''} onClick={() => update({ [key]: !config[key] })}>
              {label}
              <small>{fmt(count)}</small>
            </button>
          ))}
        </div>
        <NumberField label="Recheck cooldown (days)" value={config.recheckDays} min={0} onChange={(recheckDays) => update({ recheckDays: Math.max(0, recheckDays) })} />

        <h4>Execution</h4>
        <NumberField label="Batch size" value={config.batchSize} min={1} step={500} onChange={(batchSize) => update({ batchSize: Math.max(1, batchSize) })} />
        <label className="mps-lab-field">
          <span>Routes</span>
          <select value={config.proxyMode} onChange={(event) => update({ proxyMode: event.target.value as MockProxyMode })}>
            {(Object.keys(PROXY_MODE_LABELS) as MockProxyMode[]).map((mode) => (
              <option key={mode} value={mode}>{PROXY_MODE_LABELS[mode]}</option>
            ))}
          </select>
        </label>
        <div className="mps-lab-grid-2 tight">
          <NumberField label="Hops" value={config.maxRouteHops} min={1} max={5} onChange={(maxRouteHops) => update({ maxRouteHops: Math.min(5, Math.max(1, maxRouteHops)) })} />
          <NumberField label="Miss ×" value={config.missThreshold} min={1} max={5} onChange={(missThreshold) => update({ missThreshold: Math.min(5, Math.max(1, missThreshold)) })} />
        </div>
        <label className="mps-lab-check">
          <input type="checkbox" checked={config.includeDirect} onChange={(event) => update({ includeDirect: event.target.checked })} /> include direct
        </label>
      </aside>

      <section className="mps-lab-deck__plan" aria-label="Plan">
        <div className="mps-lab-equation">
          <div className={config.includeMissing ? '' : 'off'}><span>missing</span><strong>{fmt(derived.missing)}</strong></div>
          <b>+</b>
          <div className={config.includeInvalid ? '' : 'off'}><span>not-found</span><strong>{fmt(derived.invalidEligible)}</strong></div>
          <b>+</b>
          <div className={config.includeExisting ? '' : 'off'}><span>existing</span><strong>{fmt(derived.existingEligible)}</strong></div>
          <b>=</b>
          <div className="total"><span>candidates</span><strong>{fmt(derived.candidates)}</strong></div>
        </div>

        <div className="mps-lab-terminal">
          <header>
            <span>equivalent command</span>
            <button
              type="button"
              onClick={() => {
                void navigator.clipboard?.writeText(command);
                setCopied(true);
              }}
            >
              {copied ? 'copied' : 'copy'}
            </button>
          </header>
          <pre><span className="prompt">$</span> {command}</pre>
        </div>

        <table className="mps-lab-table">
          <tbody>
            <tr><th>This job</th><td>{fmt(derived.selected)}</td><th>Batches</th><td>{fmt(derived.batches)}</td></tr>
            <tr><th>Routes</th><td>{derived.routeCount}</td><th>Per route</th><td>{fmt(derived.profilesPerRoute)}</td></tr>
            <tr><th>Ranges</th><td>{fmt(derived.rangeCount)}</td><th>Avg range</th><td>{fmt(derived.averageRange)}</td></tr>
            <tr><th>ETA batch</th><td>{formatMinutes(derived.minutesPerBatch)}</td><th>ETA all</th><td>{formatMinutes(derived.minutesTotal)}</td></tr>
          </tbody>
        </table>

        <div className="mps-lab-deck__ranges">
          {derived.ranges.slice(0, 6).map((range) => (
            <button key={range.startId} type="button" onClick={() => update({ startId: range.startId, endId: range.endId })}>
              <code>{fmt(range.startId)}–{fmt(range.endId)}</code>
              <small>{fmt(range.count)}</small>
            </button>
          ))}
        </div>
      </section>

      <aside className="mps-lab-deck__checks" aria-label="Preflight">
        <h4>Preflight</h4>
        <ul>
          {checks.map((check) => (
            <li key={check.label} className={check.state}>
              <span className="mps-lab-dot" aria-hidden="true" />
              <strong>{check.label}</strong>
              <small>{check.detail}</small>
            </li>
          ))}
        </ul>
        <input
          className="mps-lab-deck__name"
          value={config.jobName}
          placeholder={jobLabel(config)}
          aria-label="Job name"
          onChange={(event) => update({ jobName: event.target.value })}
        />
        <button
          type="button"
          className="mps-lab-btn primary block"
          disabled={blocked}
          onClick={() => onLaunch(`${jobLabel(config)}: ${fmt(derived.selected)} profiles`)}
        >
          Run batch 1
        </button>
        <small className="mps-lab-kbd"><kbd>Ctrl</kbd> + <kbd>Enter</kbd> to run</small>
      </aside>
    </div>
  );
}
