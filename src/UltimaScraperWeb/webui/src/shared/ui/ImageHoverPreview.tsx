import { createPortal } from 'react-dom';
import type { HoverPreviewState } from './useImageHoverPreview';
import './ImageHoverPreview.css';

export type { HoverPreviewState };

interface ImageHoverPreviewProps {
  preview: HoverPreviewState | null;
  onEnter: () => void;
  onLeave: () => void;
  onClick?: (imageUrl: string, alt: string) => void;
}

export function ImageHoverPreview({
  preview,
  onEnter,
  onLeave,
  onClick,
}: ImageHoverPreviewProps) {
  if (!preview || typeof document === 'undefined') {
    return null;
  }

  const { imageUrl, alt, kind, targetRect } = preview;
  const position = computePopoverPosition(targetRect, kind);

  return createPortal(
    <div
      className={`image-hover-popover image-hover-popover--${kind}`}
      style={position}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.(imageUrl, alt);
      }}
      role="tooltip"
      aria-label={`${alt} preview`}
    >
      <div className="image-hover-popover__media-wrap">
        <img src={imageUrl} alt={alt} className="image-hover-popover__img" />
      </div>
      <div className="image-hover-popover__footer">
        <span className="image-hover-popover__caption">{alt}</span>
        <span className="image-hover-popover__hint">Click to enlarge ↗</span>
      </div>
    </div>,
    document.body
  );
}

function computePopoverPosition(rect: DOMRect, kind: 'avatar' | 'header'): React.CSSProperties {
  const margin = 12;
  const vw = typeof window !== 'undefined' ? window.innerWidth : 1200;
  const vh = typeof window !== 'undefined' ? window.innerHeight : 800;

  if (kind === 'avatar') {
    const width = 260;
    const estimatedHeight = 290;

    let left: number;
    if (rect.right + margin + width <= vw - 16) {
      left = rect.right + margin;
    } else if (rect.left - margin - width >= 16) {
      left = rect.left - margin - width;
    } else {
      left = Math.max(16, Math.min(vw - width - 16, rect.left + rect.width / 2 - width / 2));
    }

    let top = rect.top - 16;
    top = Math.max(16, Math.min(vh - estimatedHeight - 16, top));

    return {
      top: `${Math.round(top)}px`,
      left: `${Math.round(left)}px`,
      width: `${width}px`,
    };
  }

  const width = Math.min(500, vw - 32);
  const estimatedHeight = 270;

  let left = rect.left + (rect.width - width) / 2;
  left = Math.max(16, Math.min(vw - width - 16, left));

  let top: number;
  if (rect.bottom + margin + estimatedHeight <= vh - 16) {
    top = rect.bottom + margin;
  } else if (rect.top - margin - estimatedHeight >= 16) {
    top = rect.top - margin - estimatedHeight;
  } else {
    top = Math.max(16, Math.min(vh - estimatedHeight - 16, rect.bottom + margin));
  }

  return {
    top: `${Math.round(top)}px`,
    left: `${Math.round(left)}px`,
    width: `${Math.round(width)}px`,
  };
}
