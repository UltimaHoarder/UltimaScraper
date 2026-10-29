import { describe, expect, it } from 'vitest';

import { chartProgress, chartTrail, DOWNLOAD_FLOWS } from '../../src/features/system/lib/downloadFlows';

const flow = (id: string) => DOWNLOAD_FLOWS.find((candidate) => candidate.id === id)!;

describe('chartProgress', () => {
  it('walks each flow down the flowchart along real branches', () => {
    const last = (id: string) => chartProgress(flow(id), flow(id).steps.length - 1).path;

    expect(last('regular')).toEqual(['queued', 'fitsRam', 'ram', 'isDrm', 'join', 'move', 'record']);
    expect(last('drm')).toEqual(['queued', 'fitsRam', 'ram', 'isDrm', 'decrypt', 'move', 'record']);
    expect(last('overflow')).toEqual(['queued', 'fitsRam', 'fitsDisk', 'disk', 'isDrm', 'decrypt', 'move', 'record']);
    expect(last('direct')).toEqual(['queued', 'fitsRam', 'fitsDisk', 'direct', 'isDrm', 'join', 'move', 'record']);
  });

  it('reports only what a step has reached', () => {
    expect(chartProgress(flow('drm'), 3)).toEqual({ path: ['queued', 'fitsRam', 'ram'], current: ['ram'] });
  });
});

describe('chartTrail', () => {
  it('gives each decision the answer the flow takes', () => {
    const trail = (id: string) => chartTrail(DOWNLOAD_FLOWS.find((candidate) => candidate.id === id)!);

    expect(trail('overflow').filter((entry) => entry.answer)).toEqual([
      { node: 'fitsRam', answer: 'no' },
      { node: 'fitsDisk', answer: 'yes' },
      { node: 'isDrm', answer: 'yes' },
    ]);
    expect(trail('regular').find((entry) => entry.node === 'isDrm')?.answer).toBe('no');
  });
});
