import { useMemo, useRef, useState, type PointerEvent } from 'react';

import { Segmented, Switch, WarningList } from './controls';
import {
  MOCK_SITES,
  SITE_PROFILES,
  bucketize,
  compact,
  fmt,
  formatMinutes,
  jobLabel,
  type ConceptProps,
} from './mpsMockModel';

const BUCKETS = 72;

/** Concept 03 — the ID space is the interface: brush a region of the density map to scope the run. */
export function IdSpaceMapConcept({ model, onLaunch }: ConceptProps) {
  const { config, derived, update, setSite } = model;
  const bounds = SITE_PROFILES[config.site];
  const [view, setView] = useState<{ site: string; start: number; end: number }>({ site: config.site, start: bounds.minId, end: bounds.maxId });
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);

  // A site switch resets the viewport to the full ID space of the new site.
  const activeView = view.site === config.site ? view : { site: config.site, start: bounds.minId, end: bounds.maxId };
  const viewSpan = Math.max(1, activeView.end - activeView.start);

  const buckets = useMemo(() => bucketize(config, activeView.start, activeView.end, BUCKETS), [config, activeView.start, activeView.end]);
  const peak = Math.max(1, ...buckets.map((bucket) => bucket.total));

  const toPercent = (id: number) => ((id - activeView.start) / viewSpan) * 100;
  const idFromPointer = (event: PointerEvent<HTMLDivElement>) => {
    const rect = plotRef.current?.getBoundingClientRect();
    if (!rect) return activeView.start;
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    return Math.round(activeView.start + ratio * viewSpan);
  };

  const selectionStart = drag ? Math.min(drag.from, drag.to) : config.startId;
  const selectionEnd = drag ? Math.max(drag.from, drag.to) : config.endId;
  const selectionLeft = Math.max(0, toPercent(selectionStart));
  const selectionRight = Math.min(100, toPercent(selectionEnd));

  const sourceKeys = [
    { key: 'missing' as const, on: config.includeMissing },
    { key: 'invalid' as const, on: config.includeInvalid },
    { key: 'existing' as const, on: config.includeExisting },
  ];

  return (
    <div className="mps-lab-map">
      <header className="mps-lab-map__toolbar">
        <Segmented label="Site" value={config.site} options={MOCK_SITES.map((site) => ({ value: site, label: site }))} onChange={setSite} />
        <div className="mps-lab-map__viewport">
          <span>Viewing {compact(activeView.start)} – {compact(activeView.end)}</span>
          <button type="button" className="mps-lab-chip" onClick={() => setView({ site: config.site, start: config.startId, end: config.endId })}>Zoom to selection</button>
          <button type="button" className="mps-lab-chip" onClick={() => setView({ site: config.site, start: bounds.minId, end: bounds.maxId })}>Full range</button>
        </div>
      </header>

      <div className="mps-lab-map__canvas">
        <div
          ref={plotRef}
          className="mps-lab-map__plot"
          role="slider"
          aria-label="Drag to select an ID range"
          aria-valuemin={activeView.start}
          aria-valuemax={activeView.end}
          aria-valuenow={config.startId}
          tabIndex={0}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            const id = idFromPointer(event);
            setDrag({ from: id, to: id });
          }}
          onPointerMove={(event) => {
            if (drag) setDrag({ ...drag, to: idFromPointer(event) });
          }}
          onPointerUp={() => {
            if (drag && Math.abs(drag.to - drag.from) > viewSpan / 400) {
              update({ startId: Math.min(drag.from, drag.to), endId: Math.max(drag.from, drag.to) });
            }
            setDrag(null);
          }}
        >
          {buckets.map((bucket) => (
            <div
              key={bucket.startId}
              className={`mps-lab-map__bar ${bucket.endId < selectionStart || bucket.startId > selectionEnd ? 'outside' : ''}`}
              title={`${fmt(bucket.startId)}–${fmt(bucket.endId)}: ${fmt(bucket.total)} candidates`}>
              {sourceKeys.map(({ key, on }) => (
                <span key={key} className={`seg ${key} ${on ? '' : 'off'}`} style={{ height: `${(bucket[key] / peak) * 100}%` }} />
              ))}
            </div>
          ))}
          {selectionRight > selectionLeft && (
            <div className="mps-lab-map__brush" style={{ left: `${selectionLeft}%`, width: `${selectionRight - selectionLeft}%` }}>
              <span>{compact(selectionStart)}</span>
              <span>{compact(selectionEnd)}</span>
            </div>
          )}
        </div>
        <div className="mps-lab-map__axis" aria-hidden="true">
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
            <span key={tick}>{compact(activeView.start + tick * viewSpan)}</span>
          ))}
        </div>
      </div>

      <div className="mps-lab-map__lower">
        <section className="mps-lab-map__legend" aria-label="Sources">
          <Switch checked={config.includeMissing} onChange={(includeMissing) => update({ includeMissing })} label="New / missing" detail={`${fmt(derived.missing)} in selection`} />
          <Switch checked={config.includeInvalid} onChange={(includeInvalid) => update({ includeInvalid })} label="Previously not found" detail={`${fmt(derived.invalidEligible)} eligible`} />
          <Switch checked={config.includeExisting} onChange={(includeExisting) => update({ includeExisting })} label="Existing profiles" detail={`${fmt(derived.existingEligible)} eligible`} />
        </section>

        <section className="mps-lab-map__ranges" aria-label="Densest candidate ranges">
          <h4>Dense pockets</h4>
          <ul>
            {derived.ranges.map((range) => (
              <li key={range.startId}>
                <button type="button" onClick={() => update({ startId: range.startId, endId: range.endId })}>
                  <code>{fmt(range.startId)}</code>
                  <i style={{ width: `${Math.min(100, (range.count / Math.max(...derived.ranges.map((r) => r.count))) * 100)}%` }} />
                  <small>{fmt(range.count)}</small>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="mps-lab-map__inspector" aria-label="Selection">
          <h4>Selection</h4>
          <dl>
            <dt>IDs</dt><dd>{fmt(derived.rangeSize)}</dd>
            <dt>Candidates</dt><dd className="accent">{fmt(derived.candidates)}</dd>
            <dt>Batches of {fmt(config.batchSize)}</dt><dd>{fmt(derived.batches)}</dd>
            <dt>Routes</dt><dd>{derived.routeCount}</dd>
            <dt>All batches</dt><dd>{formatMinutes(derived.minutesTotal)}</dd>
          </dl>
          <WarningList warnings={derived.warnings} />
          <button
            type="button"
            className="mps-lab-btn primary block"
            disabled={derived.selected === 0}
            onClick={() => onLaunch(`${jobLabel(config)}: ${fmt(derived.selected)} profiles from the brushed range`)}
          >
            Queue {fmt(derived.selected)} from selection
          </button>
        </section>
      </div>
    </div>
  );
}
