import './MediaRatioBar.css';

export interface MediaRatioBarProps {
  imageCount: number;
  videoCount: number;
  totalMediaCount?: number;
  showCounts?: boolean;
  className?: string;
  formatNumber?: (num: number) => string;
}

/**
 * Reusable MediaRatioBar component extracted from the Visual Showcase mock.
 * Visualizes the balance of photos vs videos with an accessible meter track and counts.
 */
export function MediaRatioBar({
  imageCount = 0,
  videoCount = 0,
  totalMediaCount,
  showCounts = true,
  className = '',
  formatNumber = (n) => n.toLocaleString(),
}: MediaRatioBarProps) {
  const safeImages = Math.max(0, imageCount);
  const safeVideos = Math.max(0, videoCount);
  const total =
    totalMediaCount !== undefined && totalMediaCount > 0
      ? totalMediaCount
      : safeImages + safeVideos;

  const photoPercent = total > 0 ? (safeImages / total) * 100 : 0;
  const videoPercent = total > 0 ? (safeVideos / total) * 100 : 0;

  return (
    <div
      className={`media-ratio-breakdown ${className}`.trim()}
      data-testid="media-ratio-bar"
    >
      <div
        className="media-ratio-track"
        role="meter"
        aria-label="Media asset composition"
        aria-valuenow={Math.round(photoPercent)}
        aria-valuemin={0}
        aria-valuemax={100}
        title={`${formatNumber(safeImages)} photos (${Math.round(photoPercent)}%) · ${formatNumber(safeVideos)} videos (${Math.round(videoPercent)}%)`}
      >
        <div
          className="media-ratio-fill media-ratio-fill--photo"
          style={{ width: `${photoPercent}%` }}
        />
        <div
          className="media-ratio-fill media-ratio-fill--video"
          style={{ width: `${videoPercent}%` }}
        />
      </div>
      {showCounts && (
        <div className="media-ratio-counts">
          <span className="count-photo" title={`${formatNumber(safeImages)} photos`}>
            <span aria-hidden="true">📷</span> {formatNumber(safeImages)} photos
          </span>
          <span className="count-video" title={`${formatNumber(safeVideos)} videos`}>
            <span aria-hidden="true">🎬</span> {formatNumber(safeVideos)} videos
          </span>
        </div>
      )}
    </div>
  );
}
