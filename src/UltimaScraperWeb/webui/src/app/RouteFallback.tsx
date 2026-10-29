import { StartupBrand } from '../components/StartupBrand';

export function RouteFallback() {
  return (
    <div className="route-loading" role="status" aria-live="polite" aria-busy="true">
      <div className="route-loading__inner">
        <div className="route-loading__identity" aria-hidden="true"><StartupBrand /></div>
        <span className="route-loading__label">Loading workspace...</span>
        <div className="route-loading__pulse" aria-hidden="true" />
      </div>
    </div>
  );
}
