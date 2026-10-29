import { useEffect, useRef } from 'react';

import { chartProgress, chartTrail, type ChartNode, type DownloadFlow } from '../lib/downloadFlows';

const DECISIONS = new Set<ChartNode>(['fitsRam', 'fitsDisk', 'isDrm']);

function labels(ramPath: string | null, diskPath: string | null): Record<ChartNode, [string, string | null]> {
  return {
    queued: ['Queued', null],
    fitsRam: ['Fits in RAM?', null],
    ram: ['Stage in RAM', ramPath],
    fitsDisk: ['Fits on disk staging?', null],
    disk: ['Stage on disk', diskPath],
    direct: ['Write on the drive', null],
    isDrm: ['DRM?', null],
    decrypt: ['Decrypt + mux', 'mp4decrypt, ffmpeg'],
    join: ['Join parts', null],
    move: ['Move to drive', null],
    record: ['Recorded', 'PostgreSQL'],
  };
}

/**
 * The flow being played, pinned to the bottom: its controls, what is
 * happening now, and its route through the flowchart as one scrolling line,
 * decisions showing the answer this flow takes.
 */
export function DownloadFlowFooter({
  flow,
  step,
  playing,
  ramPath,
  diskPath,
  onStep,
  onTogglePlay,
  onStop,
}: {
  flow: DownloadFlow;
  step: number;
  playing: boolean;
  ramPath: string | null;
  diskPath: string | null;
  onStep: (step: number) => void;
  onTogglePlay: () => void;
  onStop: () => void;
}) {
  const trailRef = useRef<HTMLOListElement>(null);
  const atEnd = step >= flow.steps.length - 1;
  const { path, current } = chartProgress(flow, step);
  const reached = new Set(path);
  const text = labels(ramPath, diskPath);

  // Keep the box being played centred in the line, without moving anything around it.
  useEffect(() => {
    const trail = trailRef.current;
    const active = trail?.querySelector<HTMLElement>('.is-active');
    if (!trail || !active) return;
    trail.scrollTo?.({ left: active.offsetLeft - (trail.clientWidth - active.offsetWidth) / 2, behavior: 'smooth' });
  }, [step, flow]);

  return (
    <footer className="arch-footer" role="region" aria-label="Flow progress">
      <div className="arch-footer-bar">
        <div className="arch-transport">
          <button
            type="button"
            className="arch-tool"
            aria-label="Previous step"
            disabled={step === 0}
            onClick={() => onStep(step - 1)}
          >
            ‹
          </button>
          <button
            type="button"
            className="arch-tool arch-tool--primary"
            aria-label={playing && !atEnd ? 'Pause' : atEnd ? 'Replay' : 'Play'}
            onClick={onTogglePlay}
          >
            {playing && !atEnd ? '❚❚' : atEnd ? '↺' : '▶'}
          </button>
          <button
            type="button"
            className="arch-tool"
            aria-label="Next step"
            disabled={atEnd}
            onClick={() => onStep(step + 1)}
          >
            ›
          </button>
        </div>
        <span className="arch-caption-step">
          {flow.label} · step {step + 1} of {flow.steps.length}
        </span>
        <button type="button" className="arch-tool arch-footer-stop" aria-label="Stop" title="Stop" onClick={onStop}>
          ✕
        </button>
      </div>
      <p className="arch-footer-caption" aria-live="polite">
        {flow.steps[step].caption}
      </p>
      <ol className="arch-trail" ref={trailRef} aria-label="Route through the flowchart">
        {chartTrail(flow).map(({ node, answer }) => {
          const [label, detail] = text[node];
          const state = current.includes(node) ? 'is-active' : reached.has(node) ? 'is-done' : 'is-ahead';
          return (
            <li key={node} className={`arch-trail-item ${state}${DECISIONS.has(node) ? ' is-decision' : ''}`} data-chart-node={node}>
              <span className="arch-trail-box">
                <strong>{label}</strong>
                {detail && <small className="mono">{detail}</small>}
              </span>
              {answer && <span className="arch-trail-answer">{answer}</span>}
            </li>
          );
        })}
      </ol>
    </footer>
  );
}
