import { useEffect, useRef, useState, type RefObject } from 'react';

import { getClusterHosts, listClusters, type BackendCluster, type ClusterHosts, type NodeRole } from '../../api/webui';
import { DownloadFlowFooter } from '../system/components/DownloadFlowFooter';
import type { ActiveMount, StorageRow } from '../system/lib/architectureStorage';
import { DOWNLOAD_FLOWS, type FlowStep, type FlowTarget } from '../system/lib/downloadFlows';
import { buildDiagram, buildTiers, type PlannedInstall, type TierCard } from './lib/architecturePlan';
import { usePanZoom } from './lib/usePanZoom';
import './ArchitectureDiagram.css';

const ROLE_LABELS: Record<NodeRole, string> = {
  backend: 'Backend',
  workers: 'Workers',
  webui: 'WebUI',
  postgres: 'PostgreSQL',
  redis: 'Redis',
};

const KIND_LABELS: Record<StorageRow['kind'], string> = {
  'ram-staging': 'RAM',
  staging: 'Staging',
  drive: 'Drive',
  mount: 'Mount',
};

const STEP_MS = 1600;
const NO_CLUSTER = 'Not in a cluster';

type FlowState = 'active' | 'done' | 'off' | null;

function cardTarget(card: TierCard): FlowTarget | null {
  if (card.role === 'webui') return card.isSelf ? 'webui' : null;
  return card.role;
}

function formatSize(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** Long ids keep both ends, enough to tell them apart. */
function shortId(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

/* ------------------------------------------------------------------ nodes */

/** What a clicked box or mount shows in its details card. */
interface Picked {
  key: string;
  title: string;
  rows: [string, string][];
  /** Where it sits on the canvas, so the card follows it while panning and zooming. */
  anchor: NodeRect;
  /** The viewport's width when it was clicked, to keep the card inside it. */
  maxLeft: number;
}

type PickHandler = (key: string, title: string, rows: [string, string | null | false | undefined][], element: HTMLElement) => void;

function NodeChip({ card, flowState, onPick }: { card: TierCard; flowState: FlowState; onPick: PickHandler }) {
  const isData = card.role === 'postgres' || card.role === 'redis';
  const title = isData ? ROLE_LABELS[card.role] : card.host;
  const secondary = isData
    ? card.identifier ?? card.host
    : [card.identifier && card.identifier !== card.host ? shortId(card.identifier) : null, card.address]
        .filter(Boolean)
        .join(' · ');
  const rows: [string, string | null | undefined][] = [
    [isData ? 'Address' : 'ID', card.identifier],
    ['Host', card.address ?? (isData ? card.host : null)],
    [card.clusters.length > 1 ? 'Clusters' : 'Cluster', card.clusters.join(', ') || NO_CLUSTER],
    ['State', card.state],
  ];
  return (
    <button
      type="button"
      className={['arch-node', `arch-node--${card.role}`, card.isNew && 'is-new', card.isSelf && 'is-self', flowState && `flow-${flowState}`]
        .filter(Boolean)
        .join(' ')}
      data-node={card.key}
      data-role={card.role}
      data-flow-active={flowState === 'active' || undefined}
      onClick={(event) => onPick(card.key, `${ROLE_LABELS[card.role]} · ${card.host}`, rows, event.currentTarget)}
    >
      <span className="arch-node-role">
        {card.state && <span className={`arch-state arch-state--${card.state}`} />}
        {ROLE_LABELS[card.role]}
        {card.isNew && <span className="arch-badge">This install</span>}
        {card.isSelf && !card.isNew && <span className="arch-badge">You are here</span>}
      </span>
      <strong className="arch-node-name">{title}</strong>
      {secondary && <span className="arch-node-sub mono">{secondary}</span>}
    </button>
  );
}

function StorageNode({
  backendId,
  host,
  mounts,
  flowStateOf,
  onPick,
}: {
  backendId: string;
  host: string;
  mounts: ActiveMount[];
  flowStateOf: (target: FlowTarget | null) => FlowState;
  onPick: PickHandler;
}) {
  return (
    <section className="arch-node arch-node--storage" data-node={`mounts:${backendId}`} aria-label={`${host} storage`}>
      <span className="arch-node-role">Storage in use</span>
      <strong className="arch-node-name">{host}</strong>
      <ul className="arch-mount-list">
        {mounts.map((mount) => {
          const flowState = flowStateOf(mount.flowTarget);
          const rows: [string, string | null | false][] = [
            ['Used for', mount.note ?? KIND_LABELS[mount.kind]],
            ['Mount', mount.path],
            ['Device', mount.device],
            ['Also at', mount.alsoAt.length > 0 && mount.alsoAt.join(', ')],
            [
              'Size',
              mount.totalBytes !== null &&
                mount.percentUsed !== null &&
                `${formatSize(mount.totalBytes)}, ${mount.percentUsed.toFixed(1)}% used`,
            ],
            ['Backend', mount.backendId],
          ];
          return (
            <li key={mount.key}>
              <button
                type="button"
                className={['arch-mount', `arch-mount--${mount.kind}`, flowState && `flow-${flowState}`].filter(Boolean).join(' ')}
                data-flow-active={flowState === 'active' || undefined}
                onClick={(event) => onPick(mount.key, mount.stagingPath ?? mount.path, rows, event.currentTarget)}
              >
              <span className="arch-mount-tag">{KIND_LABELS[mount.kind]}</span>
              <span className="arch-mount-path mono">{mount.stagingPath ?? mount.path}</span>
              {mount.percentUsed !== null ? (
                <span className="arch-mount-usage">
                  <span className="arch-mount-bar">
                    <span
                      className={mount.percentUsed >= 95 ? 'is-full' : undefined}
                      style={{ width: `${Math.min(100, mount.percentUsed)}%` }}
                    />
                  </span>
                  {mount.percentUsed.toFixed(0)}%
                </span>
              ) : (
                <span className="arch-mount-usage">RAM</span>
              )}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ------------------------------------------------------------------ edges */

interface MountGroup {
  backendId: string;
  host: string;
  clusterId: string | null;
  mounts: ActiveMount[];
}

/** Each backend's mounts together, so one arrow ties them to it. */
function mountGroups(mounts: ActiveMount[]): MountGroup[] {
  const groups: MountGroup[] = [];
  for (const mount of mounts) {
    const group = groups.find((entry) => entry.backendId === mount.backendId);
    if (group) group.mounts.push(mount);
    else groups.push({ backendId: mount.backendId, host: mount.host, clusterId: mount.clusterId, mounts: [mount] });
  }
  return groups;
}

interface ArchEdge {
  key: string;
  from: string;
  to: string;
  label: string;
  fromTargets: FlowTarget[];
  toTargets: FlowTarget[];
  quiet?: boolean;
}

const shareCluster = (a: TierCard, b: TierCard) => a.clusters.some((name) => b.clusters.includes(name));

/** WebUIs drive backends, backends queue in Redis and record in PostgreSQL, workers write to the storage their backend owns. */
function buildEdges(tiers: ReturnType<typeof buildTiers>, mounts: ActiveMount[] | null): ArchEdge[] {
  const edges: ArchEdge[] = [];
  const add = (from: string, to: string, label: string, fromTargets: FlowTarget[], toTargets: FlowTarget[], quiet = false) =>
    edges.push({ key: `${from}>${to}`, from, to, label, fromTargets, toTargets, quiet });
  const targetsOf = (card: TierCard) => {
    const target = cardTarget(card);
    return target ? [target] : [];
  };
  const redis = tiers.data.filter((card) => card.role === 'redis');
  const postgres = tiers.data.filter((card) => card.role === 'postgres');

  for (const backend of tiers.backends) {
    for (const webui of tiers.webuis) {
      if (shareCluster(webui, backend)) add(webui.key, backend.key, 'manages', targetsOf(webui), ['backend']);
    }
    for (const queue of redis) if (shareCluster(queue, backend)) add(backend.key, queue.key, 'queues tasks', ['backend'], ['redis']);
    for (const database of postgres) {
      if (shareCluster(database, backend)) add(backend.key, database.key, 'records', ['backend'], ['postgres']);
    }
  }
  for (const queue of redis) {
    for (const workers of tiers.workers) if (shareCluster(queue, workers)) add(queue.key, workers.key, 'hands out tasks', ['redis'], ['workers']);
  }
  for (const group of mountGroups(mounts ?? [])) {
    const node = `mounts:${group.backendId}`;
    const targets = group.mounts.flatMap((mount) => (mount.flowTarget ? [mount.flowTarget] : []));
    const backend = tiers.backends.find(
      (card) => card.identifier === group.backendId || card.host === group.backendId || card.host === group.host,
    );
    if (backend) add(backend.key, node, 'owns', [], [], true);
    for (const workers of tiers.workers.filter((card) => card.host === group.host)) {
      add(workers.key, node, 'writes', ['workers'], targets);
    }
  }
  return edges;
}

type EdgeState = 'active' | 'off' | null;

/** An edge lights up when a step moves the flow across it. */
function edgeState(edge: ArchEdge, previous: FlowStep | null, current: FlowStep | null): EdgeState {
  if (!current) return null;
  const now = new Set(current.targets);
  const before = new Set(previous?.targets ?? []);
  const touches = (targets: FlowTarget[], set: Set<FlowTarget>) => targets.some((target) => set.has(target));
  const crossed =
    (touches(edge.fromTargets, before) && touches(edge.toTargets, now)) ||
    (touches(edge.fromTargets, now) && touches(edge.toTargets, before)) ||
    (touches(edge.fromTargets, now) && touches(edge.toTargets, now));
  return crossed ? 'active' : 'off';
}

interface NodeRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Where each [data-node] box sits inside the canvas, in the canvas's own (unzoomed) units. */
function useNodeRects(canvasRef: RefObject<HTMLDivElement | null>, layoutKey: string): Record<string, NodeRect> {
  const [rects, setRects] = useState<Record<string, NodeRect>>({});
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const next: Record<string, NodeRect> = {};
      canvas.querySelectorAll<HTMLElement>('[data-node]').forEach((element) => {
        let x = 0;
        let y = 0;
        let node: HTMLElement | null = element;
        while (node && node !== canvas) {
          x += node.offsetLeft;
          y += node.offsetTop;
          node = node.offsetParent as HTMLElement | null;
        }
        next[element.dataset.node!] = { x, y, w: element.offsetWidth, h: element.offsetHeight };
      });
      setRects((previous) => (JSON.stringify(previous) === JSON.stringify(next) ? previous : next));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    canvas.querySelectorAll('[data-node]').forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [canvasRef, layoutKey]);
  return rects;
}

/** A curve between two boxes: down or up between rows, sideways within one. */
function connect(a: NodeRect, b: NodeRect): { d: string; mid: { x: number; y: number } } {
  const ax = a.x + a.w / 2;
  const bx = b.x + b.w / 2;
  if (b.y >= a.y + a.h - 2) {
    const y1 = a.y + a.h;
    const y2 = b.y;
    const bend = Math.max(18, (y2 - y1) / 2);
    return { d: `M ${ax} ${y1} C ${ax} ${y1 + bend}, ${bx} ${y2 - bend}, ${bx} ${y2}`, mid: { x: (ax + bx) / 2, y: (y1 + y2) / 2 } };
  }
  if (b.y + b.h <= a.y + 2) {
    // Stacked on a narrow screen: up from the top edge.
    const y1 = a.y;
    const y2 = b.y + b.h;
    const bend = Math.max(18, (y1 - y2) / 2);
    return { d: `M ${ax} ${y1} C ${ax} ${y1 - bend}, ${bx} ${y2 + bend}, ${bx} ${y2}`, mid: { x: (ax + bx) / 2, y: (y1 + y2) / 2 } };
  }
  const ay = a.y + a.h / 2;
  const by = b.y + b.h / 2;
  const rightward = bx > ax;
  const x1 = rightward ? a.x + a.w : a.x;
  const x2 = rightward ? b.x : b.x + b.w;
  const bend = Math.max(18, Math.abs(x2 - x1) / 2) * (rightward ? 1 : -1);
  return { d: `M ${x1} ${ay} C ${x1 + bend} ${ay}, ${x2 - bend} ${by}, ${x2} ${by}`, mid: { x: (x1 + x2) / 2, y: (ay + by) / 2 } };
}

function EdgeLayer({ edges, rects, states }: { edges: ArchEdge[]; rects: Record<string, NodeRect>; states: Map<string, EdgeState> }) {
  return (
    <svg className="arch-edges" aria-hidden="true">
      <defs>
        <marker id="arch-edge-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
      </defs>
      {edges.map((edge) => {
        const a = rects[edge.from];
        const b = rects[edge.to];
        if (!a || !b) return null;
        const { d, mid } = connect(a, b);
        const state = states.get(edge.key);
        return (
          <g
            key={edge.key}
            className={['arch-edge', state && `is-${state}`, edge.quiet && 'is-quiet'].filter(Boolean).join(' ')}
            data-edge={edge.key}
          >
            <title>{edge.label}</title>
            <path d={d} markerEnd="url(#arch-edge-arrow)" />
            {state === 'active' && (
              <text x={mid.x} y={mid.y} textAnchor="middle" dy="-4">
                {edge.label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/* --------------------------------------------------------------- diagram */

/**
 * The system as a flowchart: every WebUI on top; below, each cluster in one
 * frame with its backend, PostgreSQL and Redis, workers and the storage they
 * write to, joined by arrows, on a canvas dragged to pan and wheeled or
 * pinched to zoom. Clicking a box or mount opens its details beside it. Given storage, a
 * download flow plays across the diagram, its route through the flowchart in
 * a footer while it runs. What an install adds is highlighted.
 */
export function ArchitectureDiagram({
  plan = null,
  storage = null,
}: {
  plan?: PlannedInstall | null;
  storage?: ActiveMount[] | null;
}) {
  const [clusters, setClusters] = useState<BackendCluster[]>([]);
  const [hosts, setHosts] = useState<Record<string, ClusterHosts | null>>({});
  const [flowId, setFlowId] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const panZoom = usePanZoom(viewportRef, canvasRef);
  const [picked, setPicked] = useState<Picked | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPicked(null);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const pick: PickHandler = (key, title, rows, element) => {
    if (picked?.key === key) {
      setPicked(null);
      return;
    }
    // Its place on the canvas, before pan and zoom, so the card can follow it.
    let x = 0;
    let y = 0;
    let node: HTMLElement | null = element;
    while (node && node !== canvasRef.current) {
      x += node.offsetLeft;
      y += node.offsetTop;
      node = node.offsetParent as HTMLElement | null;
    }
    setPicked({
      key,
      title,
      rows: rows.filter((row): row is [string, string] => Boolean(row[1])),
      anchor: { x, y, w: element.offsetWidth, h: element.offsetHeight },
      maxLeft: (viewportRef.current?.clientWidth ?? 0) - 296,
    });
  };

  useEffect(() => {
    let active = true;
    listClusters()
      .then(async (loaded) => {
        if (!active) return;
        const listed = loaded.clusters ?? [];
        setClusters(listed);
        const described = await Promise.all(
          listed.map((cluster) =>
            getClusterHosts(cluster.cluster_id).then(
              (value) => [cluster.cluster_id, value] as const,
              () => [cluster.cluster_id, null] as const,
            ),
          ),
        );
        if (active) setHosts(Object.fromEntries(described));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const flow = DOWNLOAD_FLOWS.find((candidate) => candidate.id === flowId) ?? null;
  const lastStep = flow ? flow.steps.length - 1 : 0;
  const shown = Math.min(step, lastStep);
  const atEnd = shown >= lastStep;

  useEffect(() => {
    if (!flow || !playing || atEnd) return;
    const timer = window.setTimeout(() => setStep((current) => current + 1), STEP_MS);
    return () => window.clearTimeout(timer);
  }, [flow, playing, atEnd, shown]);

  const currentStep = flow?.steps[shown] ?? null;
  const previousStep = flow && shown > 0 ? flow.steps[shown - 1] : null;
  const activeTargets = new Set(currentStep?.targets ?? []);
  const doneTargets = new Set(flow?.steps.slice(0, shown).flatMap((entry) => entry.targets) ?? []);
  const flowStateOf = (target: FlowTarget | null): FlowState => {
    if (!flow) return null;
    if (target && activeTargets.has(target)) return 'active';
    if (target && doneTargets.has(target)) return 'done';
    return 'off';
  };

  const { clusters: drawn, standalone } = buildDiagram(plan, clusters, hosts);
  const tiers = buildTiers(drawn, standalone, plan);
  const clusterName = (clusterId: string | null) =>
    drawn.find((cluster) => cluster.key === clusterId)?.name ?? (clusterId ? clusterId.slice(0, 8) : NO_CLUSTER);
  const groups = mountGroups(storage ?? []);

  // One frame per cluster; a service in several clusters is drawn in its first.
  const frameNames = [...new Set(drawn.map((cluster) => cluster.name))];
  const homeOf = (card: TierCard) => card.clusters[0] ?? NO_CLUSTER;
  const services = [...tiers.backends, ...tiers.data, ...tiers.workers];
  if (services.some((card) => !card.clusters.length)) frameNames.push(NO_CLUSTER);
  const frames = frameNames
    .map((name) => ({
      name,
      key: drawn.find((cluster) => cluster.name === name)?.key ?? null,
      backends: tiers.backends.filter((card) => homeOf(card) === name),
      data: tiers.data.filter((card) => homeOf(card) === name),
      workers: tiers.workers.filter((card) => homeOf(card) === name),
      storage: groups.filter((group) => {
        const groupName = clusterName(group.clusterId);
        return groupName === name || (name === frameNames[0] && !frameNames.includes(groupName));
      }),
    }))
    .filter((frame) => frame.backends.length + frame.data.length + frame.workers.length + frame.storage.length > 0);

  const edges = buildEdges(tiers, storage);
  const rects = useNodeRects(
    canvasRef,
    `${edges.map((edge) => edge.key).join()}|${storage?.length ?? 0}|${frames.length}`,
  );
  const edgeStates = new Map(edges.map((edge) => [edge.key, edgeState(edge, previousStep, currentStep)] as const));
  const stagingPath = (target: FlowTarget) => storage?.find((mount) => mount.flowTarget === target)?.stagingPath ?? null;

  const choose = (id: string) => {
    setFlowId(id);
    setStep(0);
    setPlaying(true);
  };
  const chip = (card: TierCard) => (
    <NodeChip key={card.key} card={card} flowState={flowStateOf(cardTarget(card))} onPick={pick} />
  );

  return (
    <figure className="arch" aria-label={plan ? 'The system after this install' : 'The system'}>
      <div className="arch-toolbar">
        {storage && (
          <div className="arch-player" role="group" aria-label="Simulate a download">
            <div className="arch-segmented">
              {DOWNLOAD_FLOWS.map((candidate) => (
                <button
                  key={candidate.id}
                  type="button"
                  className={candidate.id === flowId ? 'is-selected' : undefined}
                  aria-pressed={candidate.id === flowId}
                  onClick={() => choose(candidate.id)}
                >
                  {candidate.label}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="arch-zoom" role="group" aria-label="Zoom">
          <button type="button" className="arch-tool" aria-label="Zoom out" disabled={!panZoom.canZoomOut} onClick={panZoom.zoomOut}>
            −
          </button>
          <button type="button" className="arch-tool" aria-label="Fit to view" title="Fit to view" onClick={panZoom.fit}>
            {Math.round(panZoom.view.scale * 100)}%
          </button>
          <button type="button" className="arch-tool" aria-label="Zoom in" disabled={!panZoom.canZoomIn} onClick={panZoom.zoomIn}>
            +
          </button>
        </div>
      </div>

      <div
        className="arch-viewport"
        ref={viewportRef}
        {...panZoom.handlers}
        onPointerDown={(event) => {
          // A press on empty canvas closes the details card and starts a drag.
          if (!(event.target as Element).closest('button, .arch-popover')) setPicked(null);
          panZoom.handlers.onPointerDown(event);
        }}
      >
          <div
            className="arch-canvas"
            ref={canvasRef}
            style={{ transform: `translate(${Math.round(panZoom.view.x)}px, ${Math.round(panZoom.view.y)}px) scale(${panZoom.view.scale})` }}
          >
            <EdgeLayer edges={edges} rects={rects} states={edgeStates} />
            <section className="arch-row arch-row--webuis" aria-label="WebUIs">
              <span className="arch-row-label">WebUIs</span>
              <div className="arch-row-nodes">{tiers.webuis.map(chip)}</div>
            </section>
            {frames.map((frame) => (
              <section key={frame.name} className="arch-cluster" aria-label={`Cluster ${frame.name}`}>
                <header className="arch-cluster-header">
                  <span className="arch-row-label">Cluster</span>
                  <strong>{frame.name}</strong>
                  {frame.key && frame.key !== frame.name && <span className="mono arch-muted">{shortId(frame.key)}</span>}
                </header>
                <div className="arch-row" aria-label="Backends and data">
                  {/* PostgreSQL left, Redis right: each arrow from the backend has a clear side. */}
                  <div className="arch-row-nodes">
                    {frame.data.filter((card) => card.role === 'postgres').map(chip)}
                    {frame.backends.map(chip)}
                    {frame.data.filter((card) => card.role !== 'postgres').map(chip)}
                  </div>
                </div>
                {frame.workers.length > 0 && (
                  <div className="arch-row" aria-label="Workers">
                    <div className="arch-row-nodes">{frame.workers.map(chip)}</div>
                  </div>
                )}
                {frame.storage.length > 0 && (
                  <div className="arch-row" aria-label="Storage">
                    <div className="arch-row-nodes">
                      {frame.storage.map((group) => (
                        <StorageNode
                          key={group.backendId}
                          backendId={group.backendId}
                          host={group.host}
                          mounts={group.mounts}
                          flowStateOf={flowStateOf}
                          onPick={pick}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </section>
            ))}
            {frames.length === 0 && <span className="arch-hint">No clusters reported yet.</span>}
          </div>
        {picked && (
          <div
            className="arch-popover"
            role="dialog"
            aria-label={picked.title}
            style={{
              left: Math.max(
                8,
                Math.min(
                  (picked.anchor.x + picked.anchor.w) * panZoom.view.scale + panZoom.view.x + 8,
                  picked.maxLeft,
                ),
              ),
              top: Math.max(8, picked.anchor.y * panZoom.view.scale + panZoom.view.y),
            }}
          >
            <header>
              <strong>{picked.title}</strong>
              <button type="button" className="arch-tool" aria-label="Close details" onClick={() => setPicked(null)}>
                ✕
              </button>
            </header>
            <dl>
              {picked.rows.map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd className="mono">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      <figcaption>
        {plan
          ? 'Highlighted: what this install adds.'
          : `${drawn.length} cluster${drawn.length === 1 ? '' : 's'} · ${tiers.webuis.length} WebUI${tiers.webuis.length === 1 ? '' : 's'} · drag to move, scroll or pinch to zoom, click a box for details`}
      </figcaption>

      {flow && (
        <DownloadFlowFooter
          flow={flow}
          step={shown}
          playing={playing}
          ramPath={stagingPath('ram')}
          diskPath={stagingPath('disk')}
          onStep={(next) => {
            setPlaying(false);
            setStep(next);
          }}
          onTogglePlay={() => {
            if (atEnd) setStep(0);
            setPlaying(!(playing && !atEnd));
          }}
          onStop={() => {
            setFlowId(null);
            setPlaying(false);
          }}
        />
      )}
    </figure>
  );
}
