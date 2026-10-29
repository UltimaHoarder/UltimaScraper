import { lazy, Suspense, useState } from 'react';
import type { DashboardPipelineProps } from '../../../../features/dashboard/SystemPulseDashboard';

const InfrastructureScene = lazy(() => import('./InfrastructureScene'));

export function AtlasPipeline(props: DashboardPipelineProps) {
  const [motion, setMotion] = useState(true);
  const number = (value?: number) => value == null ? '--' : value.toLocaleString();
  return (
    <section className="system-pulse__panel atlas-infrastructure" aria-label="Acquisition pipeline">
      <div className="atlas-infrastructure-heading"><span>ACQUISITION PIPELINE // SCHEMATIC</span><button type="button" onClick={() => setMotion(!motion)} aria-pressed={!motion}>{motion ? 'Pause motion' : 'Resume motion'}</button></div>
      <Suspense fallback={<div className="atlas-scene-fallback" aria-hidden="true">ACQUIRE / ROUTE / PROCESS / PRESERVE</div>}>
        <InfrastructureScene motion={motion} active={Boolean(props.activeWorkers)} />
      </Suspense>
      <div className="atlas-pipeline-labels"><span>WORKER POOL<b>{number(props.workers)} units</b></span><span>ROUTE NETWORK<b>{number(props.routes)} proxies</b></span><span>DATA VAULT<b>Storage pipeline</b></span></div>
      <div className="atlas-backend-strip">
        <span>NODE <b>{props.backendId || '--'}</b></span>
        <span>MODE <b>{props.distributed == null ? '--' : props.distributed ? 'DISTRIBUTED' : 'LOCAL'}</b></span>
        <span>REDIS <b className={props.redisConnected === false && props.distributed ? 'is-warning' : ''}>{props.distributed === false ? 'NOT REQUIRED' : props.redisConnected == null ? '--' : props.redisConnected ? 'CONNECTED' : 'DISCONNECTED'}</b></span>
      </div>
    </section>
  );
}
