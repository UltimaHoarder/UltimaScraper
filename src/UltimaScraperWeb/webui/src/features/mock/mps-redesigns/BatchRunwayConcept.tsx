import { useState } from 'react';

import { Segmented } from './controls';
import {
  PROXY_MODE_LABELS,
  describeSources,
  fmt,
  formatMinutes,
  jobLabel,
  type ConceptProps,
  type MockProxyMode,
} from './mpsMockModel';

const PRESETS = [
  { label: 'Cautious', perRoute: 250 },
  { label: 'Balanced', perRoute: 500 },
  { label: 'Aggressive', perRoute: 900 },
] as const;

const VISIBLE_BATCHES = 8;

/** Concept 04 — plan the whole run as a runway of batches and see per-route load before launching. */
export function BatchRunwayConcept({ model, onLaunch }: ConceptProps) {
  const { config, derived, update } = model;
  const [launched, setLaunched] = useState(0);
  const routeCount = Math.max(1, derived.routeCount);
  const loadClass = (perRoute: number) => (perRoute >= 1_000 ? 'hot' : perRoute >= 600 ? 'warm' : 'cool');
  const launchedClamped = Math.min(launched, derived.batches);
  const launchedProfiles = Math.min(derived.candidates, launchedClamped * config.batchSize);

  const launchNext = (count: number) => {
    const remaining = derived.batches - launchedClamped;
    const take = Math.min(count, remaining);
    if (take <= 0) return;
    setLaunched(launchedClamped + take);
    onLaunch(`${take} batch${take === 1 ? '' : 'es'} of ${jobLabel(config)} (${fmt(Math.min(take * config.batchSize, derived.candidates - launchedProfiles))} profiles)`);
  };

  const batchRows = Array.from({ length: Math.min(VISIBLE_BATCHES, derived.batches) }, (_, index) => {
    const number = launchedClamped + index;
    const offset = number * config.batchSize;
    return { number, offset, size: Math.min(config.batchSize, derived.candidates - offset) };
  }).filter((row) => row.size > 0);

  return (
    <div className="mps-lab-runway">
      <header className="mps-lab-runway__summary">
        <div>
          <span>Run</span>
          <strong>{jobLabel(config)}</strong>
          <small>{describeSources(config)}</small>
        </div>
        <div className="mps-lab-runway__progress" aria-label={`${launchedClamped} of ${derived.batches} batches queued`}>
          <div className="bar"><i style={{ width: `${derived.candidates ? (launchedProfiles / derived.candidates) * 100 : 0}%` }} /></div>
          <small>{fmt(launchedProfiles)} / {fmt(derived.candidates)} candidates queued · {launchedClamped} / {fmt(derived.batches)} batches</small>
        </div>
        <button type="button" className="mps-lab-btn ghost" onClick={() => setLaunched(0)} disabled={launchedClamped === 0}>Reset</button>
      </header>

      <section className="mps-lab-runway__sizing" aria-label="Batch sizing">
        <div className="mps-lab-runway__presets">
          {PRESETS.map((preset) => {
            const size = preset.perRoute * routeCount;
            return (
              <button
                key={preset.label}
                type="button"
                className={config.batchSize === size ? 'active' : ''}
                onClick={() => update({ batchSize: size })}
              >
                <strong>{preset.label}</strong>
                <span>{fmt(size)} / batch</span>
                <small>{preset.perRoute} per route · {fmt(Math.ceil(derived.candidates / size))} batches</small>
              </button>
            );
          })}
          <label className="mps-lab-runway__custom">
            <strong>Custom</strong>
            <input type="number" min={1} value={config.batchSize} onChange={(event) => update({ batchSize: Math.max(1, Number(event.target.value) || 1) })} aria-label="Custom batch size" />
          </label>
        </div>
        <Segmented
          label="Proxy mode"
          value={config.proxyMode}
          options={(Object.keys(PROXY_MODE_LABELS) as MockProxyMode[]).map((mode) => ({ value: mode, label: PROXY_MODE_LABELS[mode] }))}
          onChange={(proxyMode) => update({ proxyMode })}
        />
      </section>

      <div className="mps-lab-runway__body">
        <section className="mps-lab-runway__lanes" aria-label="Per-route load for one batch">
          <h4>Route load · one batch <small>{fmt(derived.profilesPerRoute)} each</small></h4>
          <ul>
            {derived.routes.map((route) => {
              const share = derived.profilesPerRoute;
              return (
                <li key={route.id} className={loadClass(share)}>
                  <code>{route.label}</code>
                  <div className="lane"><i style={{ width: `${Math.min(100, (share / 1_200) * 100)}%` }} /></div>
                  <small>{fmt(share)}</small>
                  <small className="muted">{formatMinutes(share / 42)}</small>
                </li>
              );
            })}
            {derived.routes.length === 0 && <li className="empty">No lookup routes for this mode.</li>}
          </ul>
          <p className="mps-lab-legend">
            <span className="cool">under 600</span>
            <span className="warm">600–999</span>
            <span className="hot">1,000+ per route</span>
          </p>
        </section>

        <section className="mps-lab-runway__queue" aria-label="Upcoming batches">
          <h4>Runway <small>next {batchRows.length} of {fmt(Math.max(0, derived.batches - launchedClamped))}</small></h4>
          <ol>
            {batchRows.map((row, index) => (
              <li key={row.number} className={index === 0 ? 'next' : ''}>
                <span className="num">#{row.number + 1}</span>
                <span className="span">offset {fmt(row.offset)} → {fmt(row.offset + row.size)}</span>
                <span className="size">{fmt(row.size)}</span>
                <span className="eta">{formatMinutes(row.size / (routeCount * 42))}</span>
              </li>
            ))}
            {batchRows.length === 0 && <li className="empty">Every batch is queued.</li>}
          </ol>
          <div className="mps-lab-runway__actions">
            <button type="button" className="mps-lab-btn primary" disabled={batchRows.length === 0} onClick={() => launchNext(1)}>Launch next</button>
            <button type="button" className="mps-lab-btn" disabled={batchRows.length === 0} onClick={() => launchNext(5)}>Launch 5</button>
            <button type="button" className="mps-lab-btn ghost" disabled={batchRows.length === 0} onClick={() => launchNext(derived.batches)}>Launch all ({fmt(derived.batches - launchedClamped)})</button>
          </div>
        </section>
      </div>
    </div>
  );
}
