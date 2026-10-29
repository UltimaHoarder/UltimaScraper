import { useEffect, useRef } from 'react';
import videojs from 'video.js';
import type Player from 'video.js/dist/types/player';
// @ts-expect-error - videojs-contrib-eme has no bundled types
import eme from 'videojs-contrib-eme';
import 'video.js/dist/video-js.css';
import './VideoPlayer.css';
import {
  getPersistedMuted,
  getPersistedVolume,
  setPersistedMuted,
  setPersistedVolume,
} from './videoPlayerStorage';

export interface VideoPlayerDRMConfig {
  /** URL of the DASH manifest (served by our backend's DRM proxy). */
  manifestUrl: string;
  /** URL that the browser CDM will POST Widevine challenges to. */
  licenseUrl: string;
}

export interface VideoPlayerProps {
  /** Video source URL (ignored when ``drm`` is provided). */
  src?: string;
  /** MIME type, when it is known by the caller. */
  type?: string;
  /** Show player controls. */
  controls?: boolean;
  /** Autoplay on mount. */
  autoplay?: boolean;
  /** Start muted. */
  muted?: boolean;
  /** Poster / thumbnail image URL. */
  poster?: string;
  /** Fluid layout (scales with parent). */
  fluid?: boolean;
  /** Responsive layout. */
  responsive?: boolean;
  /** Preload strategy. */
  preload?: 'auto' | 'metadata' | 'none';
  /** Additional CSS class on the wrapper div. */
  className?: string;
  /** DRM configuration — when set, the player uses DASH+Widevine via EME. */
  drm?: VideoPlayerDRMConfig | null;
  /** Callback when player is ready. */
  onReady?: (player: Player) => void;
  /** Callback on playback error. */
  onError?: (error: unknown) => void;
  /** Enable player-surface arrow fallback and Ctrl+Arrow navigation callbacks. */
  /** Enable player-surface arrow fallback, number scrubbing, and Ctrl+Arrow navigation callbacks. Defaults to true. */
  keyboardShortcuts?: boolean;
  /** Move to the previous video from the surrounding media collection. */
  onPrevious?: () => void;
  /** Move to the next video from the surrounding media collection. */
  onNext?: () => void;
}

// Register the EME plugin once on module load. videojs.registerPlugin tolerates
// repeat registration with the same function reference.
let emeRegistered = false;
function registerEmePlugin(): void {
  if (emeRegistered) return;
  try {
    (videojs as unknown as { registerPlugin: (name: string, plugin: unknown) => void })
      .registerPlugin?.('eme', eme);
  } catch {
    // Already registered — ignore.
  }
  emeRegistered = true;
}

export function VideoPlayer({
  src,
  type = 'video/mp4',
  controls = true,
  autoplay = false,
  muted = false,
  poster,
  fluid = true,
  responsive = true,
  preload = 'metadata',
  className,
  drm,
  onReady,
  onError,
  keyboardShortcuts = true,
  onPrevious,
  onNext,
}: VideoPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<Player | null>(null);

  const wrapperClassName = [
    'video-player-shell',
    fluid ? 'is-fluid' : '',
    responsive ? 'is-responsive' : '',
  ]
    .filter(Boolean)
    .join(' ');

  // Create the video.js instance once per mount inside a dedicated container element.
  useEffect(() => {
    const containerEl = containerRef.current;
    if (!containerEl) return;

    registerEmePlugin();

    // Create a video element dynamically so React virtual DOM doesn't conflict
    // with Video.js DOM transformations.
    const videoEl = document.createElement('video-js');
    videoEl.className = 'video-js vjs-big-play-button-centered';
    if (poster) {
      videoEl.setAttribute('poster', poster);
    }
    videoEl.setAttribute('playsinline', '');

    containerEl.appendChild(videoEl);

    const savedVolume = getPersistedVolume();
    const savedMuted = getPersistedMuted();
    const initialMuted = savedMuted !== null ? savedMuted : muted;

    const player = videojs(videoEl, {
      controls,
      autoplay,
      muted: initialMuted,
      preload,
      fluid,
      responsive,
      poster,
      userActions: { hotkeys: true },
    });
    playerRef.current = player;

    if (savedVolume !== null) {
      try {
        player.volume(savedVolume);
      } catch {
        // Ignored
      }
    }

    player.on('volumechange', () => {
      if (player.isDisposed()) return;
      const currentVol = player.volume();
      const currentMuted = player.muted();
      if (typeof currentVol === 'number' && !isNaN(currentVol)) {
        setPersistedVolume(currentVol);
      }
      if (typeof currentMuted === 'boolean') {
        setPersistedMuted(currentMuted);
      }
    });

    const playerElement = player.el() as HTMLElement;
    const focusPlayerFromVideo = (event: Event) => {
      const target = event.target;
      if (
        target instanceof Element &&
        (target.closest('.vjs-tech') ||
          target.closest('.video-js') ||
          target.closest('.vjs-poster') ||
          target.closest('.vjs-big-play-button'))
      ) {
        playerElement.focus({ preventScroll: true });
      }
    };
    if (playerElement) {
      playerElement.style.width = '100%';
      playerElement.style.height = '100%';
      playerElement.style.minHeight = '240px';
      playerElement.tabIndex = 0;
      playerElement.addEventListener('click', focusPlayerFromVideo, true);
    }

    try {
      (player as unknown as { eme?: () => void }).eme?.();
    } catch (err) {
      if (drm) onError?.(err);
    }

    player.on('error', () => onError?.(player.error()));
    player.ready(() => {
      if (player.isDisposed()) return;

      if (savedVolume !== null) {
        try {
          player.volume(savedVolume);
        } catch {
          // Ignored
        }
      }
      if (savedMuted !== null) {
        try {
          player.muted(savedMuted);
        } catch {
          // Ignored
        }
      }

      const readyElement = player.el() as HTMLElement;
      if (readyElement) {
        readyElement.style.width = '100%';
        readyElement.style.height = '100%';
        readyElement.style.minHeight = '240px';
        readyElement.tabIndex = 0;
        if (keyboardShortcuts) {
          readyElement.focus({ preventScroll: true });
        }
      }
      onReady?.(player);
    });

    return () => {
      if (playerRef.current && !playerRef.current.isDisposed()) {
        try {
          playerRef.current.dispose();
        } catch {
          // Ignored
        }
        playerRef.current = null;
      }
      if (containerEl) {
        containerEl.innerHTML = '';
      }
      playerElement.removeEventListener('click', focusPlayerFromVideo, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Apply / refresh the source whenever inputs change.
  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;

    player.ready(() => {
      if (player.isDisposed()) return;

      if (drm) {
        player.src({
          src: drm.manifestUrl,
          type: 'application/dash+xml',
          keySystems: {
            'com.widevine.alpha': {
              url: drm.licenseUrl,
              videoRobustness: 'SW_SECURE_CRYPTO',
              audioRobustness: 'SW_SECURE_CRYPTO',
              persistentState: 'optional',
            },
          },
        });
      } else if (src) {
        // Content stream URLs end in an ID rather than a file extension.
        // Video.js selects a playback tech before it fetches that URL, so it
        // needs an explicit MIME type instead of relying on the response
        // Content-Type. Callers can override the MP4 default when known.
        player.src({ src, type });
      }

      if (poster !== undefined) {
        player.poster(poster);
      }

      if (autoplay) {
        const playAttempt = player.play();
        if (playAttempt && typeof (playAttempt as Promise<void>).catch === 'function') {
          (playAttempt as Promise<void>).catch(() => {
            // Autoplay may be blocked by browser policy — this is expected.
          });
        }
      }
    });
  }, [src, type, drm, poster, autoplay]);

  useEffect(() => {
    if (!keyboardShortcuts) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target?.matches('input, select, textarea, [contenteditable="true"]')
      ) {
        return;
      }

      const player = playerRef.current;
      if (!player || player.isDisposed()) return;

      if (event.ctrlKey && event.key === 'ArrowLeft') {
        event.preventDefault();
        event.stopImmediatePropagation();
        onPrevious?.();
        return;
      }
      if (event.ctrlKey && event.key === 'ArrowRight') {
        event.preventDefault();
        event.stopImmediatePropagation();
        onNext?.();
        return;
      }

      // Check if target is player element, inside player element, or player currently has active focus.
      const eventTarget = event.target as Node | null;
      const playerElement = player.el();
      if (!playerElement || !eventTarget) {
        return;
      }

      const isPlayerTarget =
        eventTarget === playerElement ||
        playerElement.contains(eventTarget) ||
        (eventTarget instanceof Element && Boolean(eventTarget.closest('.vjs-tech, .video-js'))) ||
        Boolean(document.activeElement && playerElement.contains(document.activeElement));

      if (!isPlayerTarget) {
        return;
      }

      // Number keys 0-9 for percentage scrubbing (0% to 90% of duration)
      if (!event.ctrlKey && !event.altKey && !event.metaKey && /^[0-9]$/.test(event.key)) {
        const duration = player.duration();
        if (typeof duration === 'number' && Number.isFinite(duration) && duration > 0) {
          const num = Number(event.key);
          const targetTime = (num / 10) * duration;
          event.preventDefault();
          event.stopImmediatePropagation();
          player.currentTime(targetTime);
          return;
        }
      }

      if (!event.ctrlKey && !event.altKey && !event.metaKey) {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          const currentTime = player.currentTime() ?? 0;
          const duration = player.duration();
          const delta = event.key === 'ArrowLeft' ? -5 : 5;
          const maxTime =
            typeof duration === 'number' && Number.isFinite(duration)
              ? duration
              : Number.POSITIVE_INFINITY;
          event.preventDefault();
          event.stopImmediatePropagation();
          player.currentTime(Math.max(0, Math.min(maxTime, currentTime + delta)));
        } else if (
          event.key === 'j' ||
          event.key === 'J' ||
          event.key === 'l' ||
          event.key === 'L'
        ) {
          const currentTime = player.currentTime() ?? 0;
          const duration = player.duration();
          const delta = event.key === 'j' || event.key === 'J' ? -10 : 10;
          const maxTime =
            typeof duration === 'number' && Number.isFinite(duration)
              ? duration
              : Number.POSITIVE_INFINITY;
          event.preventDefault();
          event.stopImmediatePropagation();
          player.currentTime(Math.max(0, Math.min(maxTime, currentTime + delta)));
        } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
          const currentVolume = player.volume() ?? 1;
          const delta = event.key === 'ArrowUp' ? 0.1 : -0.1;
          event.preventDefault();
          event.stopImmediatePropagation();
          player.volume(Math.max(0, Math.min(1, currentVolume + delta)));
        } else if (event.key === ' ' || event.key === 'k' || event.key === 'K') {
          event.preventDefault();
          event.stopImmediatePropagation();
          if (player.paused()) {
            void player.play();
          } else {
            player.pause();
          }
        } else if (event.key === 'm' || event.key === 'M') {
          event.preventDefault();
          event.stopImmediatePropagation();
          player.muted(!player.muted());
        } else if (event.key === 'f' || event.key === 'F') {
          event.preventDefault();
          event.stopImmediatePropagation();
          if (player.isFullscreen()) {
            void player.exitFullscreen();
          } else {
            void player.requestFullscreen();
          }
        } else if (event.key === 'Home') {
          event.preventDefault();
          event.stopImmediatePropagation();
          player.currentTime(0);
        } else if (event.key === 'End') {
          const duration = player.duration();
          if (typeof duration === 'number' && Number.isFinite(duration)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            player.currentTime(duration);
          }
        }
      }
    };

    // Capture before Video.js stops propagation on player key events.
    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [keyboardShortcuts, onNext, onPrevious]);

  return (
    <div data-vjs-player className={className}>
      <div ref={containerRef} className={wrapperClassName} />
    </div>
  );
}
