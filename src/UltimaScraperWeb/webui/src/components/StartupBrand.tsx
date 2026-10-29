import { AtlasMark } from '../themes/ultima-atlas/layout/AtlasMark';
import './StartupBrand.css';

export function StartupBrand() {
  return (
    <div className="startup-brand">
      <AtlasMark className="startup-atlas-mark" />
      <div>
        <div className="startup-logo-text">
          <span className="logo-main">Ultima</span>
          <span className="logo-sub">Scraper</span>
        </div>
        <span className="startup-subtitle">DISTRIBUTED ACQUISITION NETWORK</span>
      </div>
    </div>
  );
}
