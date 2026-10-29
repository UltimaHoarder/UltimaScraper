import type { NetworkProxy } from '../../../api/types/network';

interface DirectConnectionCardProps {
  proxy: NetworkProxy;
  isAnalyzing: boolean;
  onOpenAnalyzer: (proxy: NetworkProxy) => void;
}

export function DirectConnectionCard({
  proxy,
  isAnalyzing,
  onOpenAnalyzer,
}: DirectConnectionCardProps) {
  return (
    <article className="network-route-card network-route-card--direct">
      <div className="network-route-card__signal" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div className="network-route-card__body">
        <div className="network-route-card__eyebrow">Baseline route</div>
        <h3>Direct connection</h3>
        <p>No proxy. Traffic leaves through the server&apos;s public IP.</p>
      </div>
      <div className="network-route-card__status">
        <span className="network-status-dot network-status-dot--ready" />
        Available
      </div>
      <button
        type="button"
        className="network-button network-button--primary"
        onClick={() => onOpenAnalyzer(proxy)}
      >
        {isAnalyzing ? 'View live run' : 'Analyze baseline'}
      </button>
    </article>
  );
}
