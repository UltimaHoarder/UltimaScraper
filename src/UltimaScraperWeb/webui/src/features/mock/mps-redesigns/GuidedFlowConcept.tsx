import { useState } from 'react';

import { Kicker, NumberField, Segmented, Switch, WarningList } from './controls';
import {
  MOCK_SITES,
  PROXY_MODE_LABELS,
  SITE_PROFILES,
  compact,
  describeSources,
  fmt,
  formatMinutes,
  jobLabel,
  type ConceptProps,
  type MockProxyMode,
} from './mpsMockModel';

const STEPS = ['Scope', 'Sources', 'Batch', 'Routes', 'Review'] as const;

/** Concept 01 — one decision per screen, with a running receipt of earlier answers. */
export function GuidedFlowConcept({ model, onLaunch }: ConceptProps) {
  const { config, derived, update, setSite } = model;
  const [step, setStep] = useState(0);
  const bounds = SITE_PROFILES[config.site];

  const stepSummary = [
    `${config.site} · ${compact(config.startId)}–${compact(config.endId)}`,
    `${derived.sourceCount} source${derived.sourceCount === 1 ? '' : 's'} · ${fmt(derived.candidates)} candidates`,
    `${fmt(config.batchSize)} per batch · ${fmt(derived.batches)} batches`,
    `${derived.routeCount} routes · ${config.maxRouteHops} hops`,
    'Confirm and queue',
  ];

  return (
    <div className="mps-lab-wizard">
      <ol className="mps-lab-wizard__rail" aria-label="Steps">
        {STEPS.map((label, index) => (
          <li key={label}>
            <button
              type="button"
              className={`${index === step ? 'current' : ''} ${index < step ? 'done' : ''}`}
              aria-current={index === step ? 'step' : undefined}
              onClick={() => setStep(index)}
            >
              <span className="mps-lab-wizard__index">{index < step ? '✓' : index + 1}</span>
              <span className="mps-lab-wizard__label">
                <strong>{label}</strong>
                <small>{stepSummary[index]}</small>
              </span>
            </button>
          </li>
        ))}
      </ol>

      <section className="mps-lab-wizard__stage" aria-live="polite">
        {step === 0 && (
          <>
            <Kicker>Step 1 of 5</Kicker>
            <h3>Where should MPS look?</h3>
            <p className="mps-lab-lede">Pick a site and the slice of its provider ID space to analyze.</p>
            <Segmented label="Site" value={config.site} options={MOCK_SITES.map((site) => ({ value: site, label: site }))} onChange={setSite} />
            <div className="mps-lab-grid-2">
              <NumberField label="First profile ID" value={config.startId} min={bounds.minId} onChange={(startId) => update({ startId })} hint={`Database minimum ${fmt(bounds.minId)}`} />
              <NumberField label="Last profile ID" value={config.endId} max={bounds.maxId} onChange={(endId) => update({ endId })} hint={`Database maximum ${fmt(bounds.maxId)}`} />
            </div>
            <div className="mps-lab-chiprow">
              {[0.01, 0.03, 0.1, 1].map((fraction) => (
                <button
                  key={fraction}
                  type="button"
                  className="mps-lab-chip"
                  onClick={() => update({ startId: Math.max(bounds.minId, Math.round(bounds.maxId * (1 - fraction))), endId: bounds.maxId })}
                >
                  Newest {fraction === 1 ? 'everything' : `${fraction * 100}%`}
                </button>
              ))}
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <Kicker>Step 2 of 5</Kicker>
            <h3>Which profiles count as candidates?</h3>
            <p className="mps-lab-lede">Sources combine. Each card shows what it adds to this range.</p>
            <div className="mps-lab-sourcecards">
              <Switch checked={config.includeMissing} onChange={(includeMissing) => update({ includeMissing })} label={`New / missing · ${fmt(derived.missing)}`} detail="IDs never stored in the database." />
              <Switch checked={config.includeInvalid} onChange={(includeInvalid) => update({ includeInvalid })} label={`Previously not found · ${fmt(derived.invalidEligible)}`} detail={`${fmt(derived.invalidTotal)} total, outside cooldown shown.`} />
              <Switch checked={config.includeExisting} onChange={(includeExisting) => update({ includeExisting })} label={`Existing profiles · ${fmt(derived.existingEligible)}`} detail={`${fmt(derived.existingTotal)} stored, outside cooldown shown.`} />
            </div>
            {(config.includeInvalid || config.includeExisting) && (
              <div className="mps-lab-inline">
                <span>Skip anything checked in the last</span>
                <Segmented
                  label="Recheck cooldown"
                  value={config.recheckDays}
                  options={[0, 1, 7, 30, 90].map((days) => ({ value: days, label: days === 0 ? 'none' : `${days}d` }))}
                  onChange={(recheckDays) => update({ recheckDays })}
                />
              </div>
            )}
          </>
        )}

        {step === 2 && (
          <>
            <Kicker>Step 3 of 5</Kicker>
            <h3>How much per job?</h3>
            <p className="mps-lab-lede">Large sets are split into batches. Each batch becomes one job you can launch later.</p>
            <div className="mps-lab-bigslider">
              <input
                type="range"
                min={500}
                max={25_000}
                step={500}
                value={config.batchSize}
                aria-label="Batch size"
                onChange={(event) => update({ batchSize: Number(event.target.value) })}
              />
              <output>{fmt(config.batchSize)}</output>
            </div>
            <div className="mps-lab-statrow">
              <div><span>Batches</span><strong>{fmt(derived.batches)}</strong></div>
              <div><span>Per route</span><strong>{fmt(derived.profilesPerRoute)}</strong></div>
              <div><span>Per batch</span><strong>{formatMinutes(derived.minutesPerBatch)}</strong></div>
            </div>
            <button type="button" className="mps-lab-linkbtn" onClick={() => update({ batchSize: Math.max(500, Math.round(derived.averageRange * 100 / 500) * 500) })}>
              Use recommended ({fmt(Math.max(500, Math.round(derived.averageRange * 100 / 500) * 500))}, ≈100 average ranges)
            </button>
          </>
        )}

        {step === 3 && (
          <>
            <Kicker>Step 4 of 5</Kicker>
            <h3>Which routes perform lookups?</h3>
            <p className="mps-lab-lede">Profiles are spread across every selected route.</p>
            <Segmented
              label="Proxy mode"
              value={config.proxyMode}
              options={(Object.keys(PROXY_MODE_LABELS) as MockProxyMode[]).map((mode) => ({ value: mode, label: PROXY_MODE_LABELS[mode] }))}
              onChange={(proxyMode) => update({ proxyMode })}
            />
            <Switch checked={config.includeDirect} onChange={(includeDirect) => update({ includeDirect })} label="Also use the direct connection" />
            <div className="mps-lab-grid-2">
              <NumberField label="Max route hops" value={config.maxRouteHops} min={1} max={5} onChange={(maxRouteHops) => update({ maxRouteHops: Math.min(5, Math.max(1, maxRouteHops)) })} />
              <NumberField label="Conclusive miss threshold" value={config.missThreshold} min={1} max={5} onChange={(missThreshold) => update({ missThreshold: Math.min(5, Math.max(1, missThreshold)) })} />
            </div>
            <ul className="mps-lab-routechips">
              {derived.routes.map((route) => (
                <li key={route.id}><code>{route.label}</code><small>{route.region} · {route.latencyMs}ms</small></li>
              ))}
            </ul>
          </>
        )}

        {step === 4 && (
          <>
            <Kicker>Step 5 of 5</Kicker>
            <h3>Review</h3>
            <dl className="mps-lab-receipt">
              <dt>Job</dt>
              <dd>
                <input value={config.jobName} placeholder={jobLabel(config)} onChange={(event) => update({ jobName: event.target.value })} aria-label="Job name" />
              </dd>
              <dt>Scope</dt><dd>{config.site}, IDs {fmt(config.startId)} – {fmt(config.endId)} ({fmt(derived.rangeSize)})</dd>
              <dt>Sources</dt><dd>{describeSources(config)}</dd>
              <dt>Candidates</dt><dd>{fmt(derived.candidates)} in {fmt(derived.rangeCount)} ranges</dd>
              <dt>This job</dt><dd>{fmt(derived.selected)} profiles · first of {fmt(derived.batches)} batches</dd>
              <dt>Routes</dt><dd>{derived.routeCount} ({PROXY_MODE_LABELS[config.proxyMode]}{config.includeDirect ? ' + direct' : ''}) · {config.maxRouteHops} hops · miss ×{config.missThreshold}</dd>
              <dt>Estimate</dt><dd>{formatMinutes(derived.minutesPerBatch)} this batch · {formatMinutes(derived.minutesTotal)} all batches</dd>
            </dl>
            <WarningList warnings={derived.warnings} />
          </>
        )}

        <footer className="mps-lab-wizard__nav">
          <button type="button" className="mps-lab-btn ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</button>
          {step < STEPS.length - 1 ? (
            <button type="button" className="mps-lab-btn" onClick={() => setStep(step + 1)}>Continue</button>
          ) : (
            <button
              type="button"
              className="mps-lab-btn primary"
              disabled={derived.selected === 0}
              onClick={() => onLaunch(`${jobLabel(config)}: ${fmt(derived.selected)} profiles over ${derived.routeCount} routes`)}
            >
              Create job · {fmt(derived.selected)} profiles
            </button>
          )}
        </footer>
      </section>
    </div>
  );
}
