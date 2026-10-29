/** A part of the architecture a download passes through. */
export type FlowTarget = 'webui' | 'backend' | 'redis' | 'workers' | 'ram' | 'disk' | 'drive' | 'postgres';

/** A box or decision in the download flowchart. */
export type ChartNode =
  | 'queued'
  | 'fitsRam'
  | 'ram'
  | 'fitsDisk'
  | 'disk'
  | 'direct'
  | 'isDrm'
  | 'decrypt'
  | 'join'
  | 'move'
  | 'record';

export interface FlowStep {
  targets: FlowTarget[];
  /** Where this step is in the flowchart. */
  chart: ChartNode[];
  caption: string;
}

export interface DownloadFlow {
  id: string;
  label: string;
  steps: FlowStep[];
}

const QUEUE: FlowStep[] = [
  { targets: ['webui'], chart: ['queued'], caption: 'You start a download job in a WebUI.' },
  {
    targets: ['backend', 'redis'],
    chart: ['queued'],
    caption: 'The backend plans the job and hands its tasks to workers through Redis.',
  },
];

const RECORD: FlowStep = {
  targets: ['drive', 'postgres'],
  chart: ['move', 'record'],
  caption: "The file lands in the performer's folder on a download drive (their existing folder, else the drive with the most room), and PostgreSQL records it as downloaded.",
};

/** The paths one item can take, matching DownloadManager and the DRM pipeline. */
export const DOWNLOAD_FLOWS: DownloadFlow[] = [
  {
    id: 'regular',
    label: 'Regular file',
    steps: [
      ...QUEUE,
      {
        targets: ['workers'],
        chart: ['fitsRam'],
        caption: 'A worker fetches the file from the site CDN in parallel byte ranges, reserving staging space for it.',
      },
      { targets: ['ram'], chart: ['ram'], caption: 'It fits, so the parts land in RAM staging.' },
      { targets: ['workers'], chart: ['isDrm', 'join'], caption: 'Not DRM: the worker joins the parts into one file.' },
      RECORD,
    ],
  },
  {
    id: 'drm',
    label: 'DRM video',
    steps: [
      ...QUEUE,
      {
        targets: ['workers'],
        chart: ['fitsRam'],
        caption: 'A worker fetches the encrypted video and audio streams, reserving twice their size for the decrypted copies.',
      },
      { targets: ['ram'], chart: ['ram'], caption: 'It fits, so both streams stage in RAM.' },
      {
        targets: ['workers'],
        chart: ['isDrm', 'decrypt'],
        caption: 'DRM: as soon as they land, mp4decrypt decrypts video and audio at once and ffmpeg muxes them, while other items keep downloading.',
      },
      RECORD,
    ],
  },
  {
    id: 'overflow',
    label: 'RAM full',
    steps: [
      ...QUEUE,
      { targets: ['workers'], chart: ['fitsRam'], caption: 'A worker fetches a large encrypted video.' },
      {
        targets: ['disk'],
        chart: ['fitsDisk', 'disk'],
        caption: 'RAM headroom is below what the item needs, so the next staging directory takes it. RAM is used again once reservations are released.',
      },
      { targets: ['workers'], chart: ['isDrm', 'decrypt'], caption: 'Decryption and muxing run on the disk staging copy.' },
      RECORD,
    ],
  },
  {
    id: 'direct',
    label: 'No staging space',
    steps: [
      ...QUEUE,
      { targets: ['workers'], chart: ['fitsRam'], caption: 'A worker fetches the file.' },
      {
        targets: ['drive'],
        chart: ['fitsDisk', 'direct'],
        caption: 'No staging directory can hold it, so parts are written beside the final file on the download drive.',
      },
      { targets: ['workers'], chart: ['isDrm', 'join'], caption: 'The parts are joined in place.' },
      {
        targets: ['postgres'],
        chart: ['move', 'record'],
        caption: 'It is already on the drive, so nothing moves; PostgreSQL records it as downloaded.',
      },
    ],
  },
];

/** The flowchart boxes a flow has reached by a step, in order, and the one being played. */
export function chartProgress(flow: DownloadFlow, step: number): { path: ChartNode[]; current: ChartNode[] } {
  const path: ChartNode[] = [];
  for (const entry of flow.steps.slice(0, step + 1)) {
    for (const node of entry.chart) if (path[path.length - 1] !== node) path.push(node);
  }
  return { path, current: flow.steps[step].chart };
}

const ANSWERS: Partial<Record<`${ChartNode}>${ChartNode}`, 'yes' | 'no'>> = {
  'fitsRam>ram': 'yes',
  'fitsRam>fitsDisk': 'no',
  'fitsDisk>disk': 'yes',
  'fitsDisk>direct': 'no',
  'isDrm>decrypt': 'yes',
  'isDrm>join': 'no',
};

export interface TrailEntry {
  node: ChartNode;
  /** For a decision, the answer this flow takes. */
  answer: 'yes' | 'no' | null;
}

/** A flow's whole route through the flowchart, one box after another. */
export function chartTrail(flow: DownloadFlow): TrailEntry[] {
  const { path } = chartProgress(flow, flow.steps.length - 1);
  return path.map((node, index) => ({ node, answer: ANSWERS[`${node}>${path[index + 1]}` as const] ?? null }));
}
