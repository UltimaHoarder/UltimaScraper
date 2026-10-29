import { useState, useCallback, useEffect } from 'react';
import type { MediaItemInfo } from '../api/types/chats';
import './MediaCarousel.css';

/** Format seconds into M:SS or H:MM:SS */
function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Summarize total duration across media items */
function totalDuration(items: MediaItemInfo[]): number {
  return items.reduce((sum, m) => sum + (m.duration ?? 0), 0);
}

interface MediaCarouselProps {
  media: MediaItemInfo[];
  price?: number | null;
  isOpened?: boolean | null;
  hasRebundledMedia?: boolean;
  onBuyClick?: () => void;
  onMediaClick?: (media: MediaItemInfo) => void;
}

export function MediaCarousel({ 
  media, 
  price, 
  isOpened,
  hasRebundledMedia,
  onBuyClick, 
  onMediaClick 
}: MediaCarouselProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [showInfoModal, setShowInfoModal] = useState(false);

  // Close modal on Escape key
  useEffect(() => {
    if (!showInfoModal) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowInfoModal(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showInfoModal]);
  
  // Pricing and access logic:
  const isPaid = price !== null && price !== undefined && price > 0;
  const allMediaViewable = media.every(m => m.can_view);
  const anyMediaViewable = media.some(m => m.can_view);
  
  // Show buy button if:
  // 1. Content is paid AND
  // 2. Not fully unlocked (isOpened false OR some media still locked)
  const showBuyButton = isPaid && !isOpened && !allMediaViewable;
  
  const goToPrevious = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setCurrentIndex((prev) => (prev === 0 ? media.length - 1 : prev - 1));
  }, [media.length]);
  
  const goToNext = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setCurrentIndex((prev) => (prev === media.length - 1 ? 0 : prev + 1));
  }, [media.length]);
  
  const goToIndex = useCallback((index: number) => {
    setCurrentIndex(index);
  }, []);

  if (media.length === 0) return null;

  const currentMedia = media[currentIndex];
  const displayUrl = currentMedia.thumb_url || currentMedia.preview_url || currentMedia.url;
  
  // Treat lock as a paywall indicator only (not generic missing-media state)
  const currentMediaPaywalled = isPaid && !isOpened && !currentMedia.can_view;
  
  // For fully locked message (no media viewable), lock everything
  const fullyLocked = isPaid && !isOpened && !anyMediaViewable;

  // Count media types for the info display
  const photoCount = media.filter(m => m.media_type === 'image' || m.media_type === 'photo').length;
  const videoCount = media.filter(m => m.media_type === 'video').length;

  const renderMediaItem = () => {
    // If paywalled/locked, show blurred preview with lock
    if (fullyLocked || currentMediaPaywalled) {
      return (
        <div className="carousel-locked">
          {displayUrl ? (
            <img 
              src={displayUrl} 
              alt="Paywalled content"
              className="carousel-locked-preview"
            />
          ) : (
            <div className="carousel-locked-placeholder">
              <span className="lock-icon">🔒</span>
            </div>
          )}
          <div className="carousel-locked-overlay">
            <span className="play-icon-locked">▶</span>
          </div>
        </div>
      );
    }

    // No URL available
    if (!displayUrl) {
      return (
        <div className="carousel-unavailable">
          <span>Media unavailable</span>
        </div>
      );
    }

    // DRM-protected content without local decrypted file
    if (currentMedia.has_drm && !currentMedia.local_url) {
      return (
        <div className="carousel-drm">
          <span className="drm-icon">🔐</span>
          <span className="drm-text">DRM media unavailable</span>
        </div>
      );
    }

    // Video
    if (currentMedia.media_type === 'video') {
      return (
        <div 
          className="carousel-video"
          onClick={() => onMediaClick?.(currentMedia)}
        >
          <img 
            src={displayUrl} 
            alt="Video thumbnail"
            loading="lazy"
          />
          <div className="video-overlay">
            <span className="play-icon">▶</span>
            {currentMedia.duration != null && currentMedia.duration > 0 && (
              <span className="video-duration">
                {formatDuration(currentMedia.duration)}
              </span>
            )}
          </div>
        </div>
      );
    }

    // Audio
    if (currentMedia.media_type === 'audio') {
      return (
        <div className="carousel-audio">
          <span className="audio-icon">🎵</span>
          {currentMedia.duration != null && currentMedia.duration > 0 && (
            <span className="audio-duration">
              {formatDuration(currentMedia.duration)}
            </span>
          )}
        </div>
      );
    }

    // Photo/Image/GIF
    return (
      <div 
        className="carousel-image"
        onClick={() => onMediaClick?.(currentMedia)}
      >
        <img 
          src={displayUrl} 
          alt={currentMedia.media_type === 'gif' ? 'GIF' : 'Photo'}
          loading="lazy"
        />
        {currentMedia.media_type === 'gif' && (
          <span className="gif-badge">GIF</span>
        )}
      </div>
    );
  };

  return (
    <div className="media-carousel">
      <div className="carousel-container">
        {renderMediaItem()}
        
        {/* Navigation arrows - show if multiple items and not fully locked */}
        {media.length > 1 && !fullyLocked && (
          <>
            <button 
              className="carousel-nav carousel-prev" 
              onClick={goToPrevious}
              aria-label="Previous"
            >
              ‹
            </button>
            <button 
              className="carousel-nav carousel-next" 
              onClick={goToNext}
              aria-label="Next"
            >
              ›
            </button>
          </>
        )}
        
        {/* Counter badge - show if not fully locked */}
        {media.length > 1 && !fullyLocked && (
          <div className="carousel-counter">
            {currentIndex + 1} / {media.length}
          </div>
        )}

        {/* Media info button — always visible, even on locked content */}
        <div className="carousel-info-buttons">
          {hasRebundledMedia && (
            <button
              className="carousel-warn-btn"
              onClick={(e) => {
                e.stopPropagation();
                setShowInfoModal(true);
              }}
              aria-label="Rebundled media warning"
              title="Contains media you already own"
            >
              ⚠
            </button>
          )}
          <button
            className="carousel-info-btn"
            onClick={(e) => {
              e.stopPropagation();
              setShowInfoModal(true);
            }}
            aria-label="Media info"
            title="Media info"
          >
            ℹ
          </button>
        </div>

        {/* Media info modal */}
        {showInfoModal && (
          <div className="media-info-modal-overlay" onClick={() => setShowInfoModal(false)}>
            <div className="media-info-modal" onClick={(e) => e.stopPropagation()}>
              <div className="media-info-modal-header">
                <span className="media-info-modal-title">Media Details</span>
                {hasRebundledMedia && (
                  <span className="media-info-rebundle-badge">
                    ⚠ Contains already owned media
                  </span>
                )}
                <button
                  className="media-info-modal-close"
                  onClick={() => setShowInfoModal(false)}
                >
                  ×
                </button>
              </div>
              <div className="media-info-modal-body">
                {media.map((m, i) => (
                  <div
                    key={m.id}
                    className={`media-info-modal-item ${i === currentIndex ? 'active' : ''}`}
                    onClick={() => { setCurrentIndex(i); setShowInfoModal(false); }}
                  >
                    <span className="info-item-icon">
                      {m.media_type === 'video' ? '🎬' : m.media_type === 'audio' ? '🎵' : m.media_type === 'gif' ? 'GIF' : '📷'}
                    </span>
                    <span className="info-item-label">
                      {m.media_type === 'photo' || m.media_type === 'image' ? 'Photo' : m.media_type === 'video' ? 'Video' : m.media_type === 'audio' ? 'Audio' : 'GIF'}
                      {' '}#{i + 1}
                    </span>
                    {(m.media_type === 'video' || m.media_type === 'audio') && m.duration != null && m.duration > 0 && (
                      <span className="info-item-duration">{formatDuration(m.duration)}</span>
                    )}
                    {m.width != null && m.height != null && (
                      <span className="info-item-resolution">{m.width}×{m.height}</span>
                    )}
                    {m.has_drm && <span className="info-item-drm">DRM</span>}
                    {m.already_owned && <span className="info-item-owned">OWNED</span>}
                  </div>
                ))}
                {(() => {
                  const total = totalDuration(media);
                  const vCount = media.filter(m => m.media_type === 'video').length;
                  const aCount = media.filter(m => m.media_type === 'audio').length;
                  if (total > 0 && (vCount + aCount) > 1) {
                    return (
                      <div className="media-info-modal-total">
                        Total duration: {formatDuration(total)}
                      </div>
                    );
                  }
                  return null;
                })()}
                {hasRebundledMedia && (
                  <div className="media-info-modal-warning">
                    ⚠ Some media in this PPV already appears in content you've previously purchased or received for free.
                    You may be paying again for media you already own.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
      
      {/* Locked content info bar and buy button - shown for paywalled content */}
      {showBuyButton && (
        <div className="carousel-locked-footer">
          <div className="locked-info-bar">
            <div className="locked-media-counts">
              {photoCount > 0 && <span>📷 {photoCount}</span>}
              {photoCount > 0 && videoCount > 0 && <span className="separator">·</span>}
              {videoCount > 0 && <span>🎬 {videoCount}</span>}
            </div>
            <div className="locked-price">
              ${price?.toFixed(2)} 🔒
            </div>
          </div>
          <button 
            className="unlock-button"
            onClick={(e) => {
              e.stopPropagation();
              onBuyClick?.();
            }}
          >
            UNLOCK FOR ${price?.toFixed(2)}
          </button>
        </div>
      )}
      
      {/* Dot indicators - show if multiple items and not fully locked */}
      {media.length > 1 && media.length <= 10 && !fullyLocked && (
        <div className="carousel-dots">
          {media.map((_, index) => (
            <button
              key={index}
              className={`carousel-dot ${index === currentIndex ? 'active' : ''}`}
              onClick={() => goToIndex(index)}
              aria-label={`Go to slide ${index + 1}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
