import {
  SystemPulseDashboard,
  type AtlasDashboardParts,
} from '../../../../features/dashboard/SystemPulseDashboard';
import { AtlasOverview } from './AtlasOverview';
import { AtlasPipeline } from './AtlasPipeline';
import { WorkerArray } from './WorkerArray';
import './dashboard.css';

const atlasParts: AtlasDashboardParts = {
  Overview: AtlasOverview,
  Pipeline: AtlasPipeline,
  WorkerArray,
};

export function Dashboard() {
  return <SystemPulseDashboard atlasParts={atlasParts} />;
}
