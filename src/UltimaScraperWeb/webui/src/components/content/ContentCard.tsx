import { memo, useState, useRef, useEffect, useCallback, type ReactNode } from 'react';
import DOMPurify from 'dompurify';
import { Link } from 'react-router-dom';
import { backendResourceUrl } from '../../api/http';
import { getMediaFileUrl } from '../../api/media';
import type { ContentLibraryItem, ContentMediaInfo } from '../../api/types/content';
import { LazyVideoPlayer } from '../LazyVideoPlayer';
import { formatPrice } from '../../shared/lib/format';
import { FavouriteButton } from '../../features/favourites/FavouriteButton';
import { copyText } from '../../utils/clipboard';

interface ContentCardProps {
  item: ContentLibraryItem;
  highlightText?: string;
  onBuyLocked?: (item: ContentLibraryItem) => void;
  buyPending?: boolean;
  onHideUser?: (userId: number, username?: string | null) => void;
}

const CONTENT_TYPE_LABELS: Record<string, string> = {
  post: 'Post',
  story: 'Story',
  message: 'Message',
  mass_message: 'Mass Message',
};

const CONTENT_TYPE_ICONS: Record<string, string> = {
  post: '📝',
  story: '📖',
  message: '✉️',
  mass_message: '📢',
};

function stripHtml(html: string): string {
  let text = html.replace(/<br\s*\/?>/gi, '\n');
  text = text.replace(/<[^>]*>/g, '');
  text = text.replace(/&amp;/g, '&');
  text = text.replace(/&lt;/g, '<');
  text = text.replace(/&gt;/g, '>');
  text = text.replace(/&quot;/g, '"');
  text = text.replace(/&#039;/g, "'");
  text = text.replace(/&nbsp;/g, ' ');
  text = text.replace(/\n{3,}/g, '\n\n');
  return text.trim();
}

function prefers24HourTime(): boolean {
  try {
    const resolved = new Intl.DateTimeFormat(undefined, { hour: 'numeric' }).resolvedOptions();
    if (typeof resolved.hour12 === 'boolean') {
      return !resolved.hour12;
    }
    return resolved.hourCycle === 'h23' || resolved.hourCycle === 'h24';
  } catch {
    return false;
  }
}

function formatDateTime(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: '', time: '' };
  const date = new Date(iso);
  const use24Hour = prefers24HourTime();
  return {
    date: date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }),
    time: date.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
      hour12: use24Hour ? false : true,
    }),
  };
}

function formatExpiry(iso: string | null): string | null {
  if (!iso) return null;
  const expires = new Date(iso);
  const now = new Date();
  const diffMs = expires.getTime() - now.getTime();
  if (diffMs <= 0) return 'Expired';
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays > 0) return `${diffDays}d ${diffHours % 24}h`;
  if (diffHours > 0) return `${diffHours}h`;
  const diffMins = Math.floor(diffMs / (1000 * 60));
  return `${diffMins}m`;
}

function formatDuration(seconds: number | undefined): string {
  if (!Number.isFinite(seconds) || !seconds || seconds <= 0) return '';
  const totalSeconds = Math.floor(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const mins = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function normalizeMediaCategory(category: string | null | undefined): string {
  return (category ?? '').trim().toLowerCase();
}

function isVideoCategory(category: string | null | undefined): boolean {
  const normalized = normalizeMediaCategory(category);
  return (
    normalized === 'video' ||
    normalized === 'videos' ||
    normalized === 'stream' ||
    normalized.startsWith('video/') ||
    normalized === 'mp4' ||
    normalized === 'webm' ||
    normalized === 'mov'
  );
}

function isLikelyVideo(media: ContentMediaInfo): boolean {
  if (isVideoCategory(media.category)) return true;
  if (typeof media.duration === 'number' && media.duration > 0) return true;

  // Older database rows may have no reliable category. Treat only explicit
  // image/photo/gif/audio values as non-video; this lets an unknown media row
  // reach the Video.js player instead of silently rendering an empty <img>.
  const normalized = normalizeMediaCategory(media.category);
  return !['image', 'images', 'photo', 'photos', 'gif', 'audio'].includes(normalized);
}

function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['a', 'br'],
    ALLOWED_ATTR: ['href'],
  });
}

interface HighlightSegment {
  highlighted: boolean;
  value: string;
}

function getHighlightSegments(text: string, query: string): HighlightSegment[] {
  const term = query.trim();
  if (!term) return [{ highlighted: false, value: text }];

  const escapedTerm = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const matcher = new RegExp(escapedTerm, 'gi');
  const segments: HighlightSegment[] = [];
  let cursor = 0;
  let match = matcher.exec(text);

  while (match) {
    if (match.index > cursor) {
      segments.push({ highlighted: false, value: text.slice(cursor, match.index) });
    }
    segments.push({ highlighted: true, value: match[0] });
    cursor = match.index + match[0].length;
    match = matcher.exec(text);
  }

  if (cursor < text.length) {
    segments.push({ highlighted: false, value: text.slice(cursor) });
  }
  return segments.length ? segments : [{ highlighted: false, value: text }];
}

function renderHighlightedText(text: string, query: string): ReactNode {
  return getHighlightSegments(text, query).map((segment, index) =>
    segment.highlighted ? (
      <mark className="content-card-search-highlight" key={`${index}-${segment.value}`}>
        {segment.value}
      </mark>
    ) : segment.value
  );
}

function highlightSanitizedHtml(html: string, query: string): string {
  if (!query.trim() || typeof document === 'undefined') return html;

  const container = document.createElement('div');
  container.innerHTML = html;
  const walker = document.createTreeWalker(container, 4);
  const textNodes: Text[] = [];
  let current = walker.nextNode();
  while (current) {
    textNodes.push(current as Text);
    current = walker.nextNode();
  }

  for (const textNode of textNodes) {
    const segments = getHighlightSegments(textNode.data, query);
    if (!segments.some((segment) => segment.highlighted)) continue;

    const fragment = document.createDocumentFragment();
    for (const segment of segments) {
      if (segment.highlighted) {
        const mark = document.createElement('mark');
        mark.className = 'content-card-search-highlight';
        mark.textContent = segment.value;
        fragment.appendChild(mark);
      } else {
        fragment.appendChild(document.createTextNode(segment.value));
      }
    }
    textNode.replaceWith(fragment);
  }

  return container.innerHTML;
}

/** Max media items to render inline (rest shown as "+N more") */
const MAX_VISIBLE_MEDIA = 4;
const EMPTY_THUMBNAIL_DATA_URL =
  'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';

interface ContentThumbnailProps {
  src: string;
  fallbackSrc: string | null;
  alt: string;
  onFinalError: () => void;
}

function ContentThumbnail({
  src,
  fallbackSrc,
  alt,
  onFinalError,
}: ContentThumbnailProps) {
  const [displaySrc, setDisplaySrc] = useState(src);
  const remoteStartedRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => () => {
    abortControllerRef.current?.abort();
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  const waitForRetry = (milliseconds: number) => new Promise<void>((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });

  const pollRemoteThumbnail = async () => {
    if (!fallbackSrc) {
      onFinalError();
      return;
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    for (let attempt = 0; attempt < 24 && !controller.signal.aborted; attempt += 1) {
      try {
        const response = await fetch(fallbackSrc, {
          cache: 'no-store',
          credentials: 'same-origin',
          signal: controller.signal,
        });
        if (response.status === 202) {
          const retryAfterSeconds = Number(response.headers.get('Retry-After') || '1');
          const serverDelay = Number.isFinite(retryAfterSeconds)
            ? Math.max(0, retryAfterSeconds * 1000)
            : 1000;
          const backoffDelay = Math.min(5000, 500 * (2 ** Math.min(attempt, 4)));
          await waitForRetry(Math.max(serverDelay, backoffDelay));
          continue;
        }
        if (!response.ok) {
          onFinalError();
          return;
        }

        const blob = await response.blob();
        if (controller.signal.aborted) return;
        const objectUrl = URL.createObjectURL(blob);
        objectUrlRef.current = objectUrl;
        setDisplaySrc(objectUrl);
        return;
      } catch {
        if (controller.signal.aborted) return;
        if (attempt >= 2) {
          onFinalError();
          return;
        }
        await waitForRetry(500 * (attempt + 1));
      }
    }

    if (!controller.signal.aborted) onFinalError();
  };

  const handleError = () => {
    if (remoteStartedRef.current) {
      onFinalError();
      return;
    }
    remoteStartedRef.current = true;
    setDisplaySrc(EMPTY_THUMBNAIL_DATA_URL);
    void pollRemoteThumbnail();
  };

  return (
    <img
      src={displaySrc}
      alt={alt}
      loading="lazy"
      onError={handleError}
    />
  );
}

export const ContentCard = memo(function ContentCard({
  item,
  highlightText = '',
  onBuyLocked,
  buyPending = false,
  onHideUser,
}: ContentCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [failedMedia, setFailedMedia] = useState<Set<number>>(new Set());
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [showShortcutHelp, setShowShortcutHelp] = useState(false);
  const [textExpanded, setTextExpanded] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLParagraphElement>(null);
  const [textHasOverflow, setTextHasOverflow] = useState(false);

  const mediaItems = item.media ?? [];
  const isLockedPaid = item.price > 0 && !item.paid;
  const lightboxMediaItems = isLockedPaid
    ? mediaItems.filter((m) => !m.preview)
    : mediaItems;

  useEffect(() => {
    if (!menuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [menuOpen]);

  // Plain left/right navigation is available for images. Video keyboard
  // shortcuts are handled by VideoPlayer so those arrow keys scrub instead.
  const goNext = useCallback(() => {
    if (lightboxIndex === null) return;
    setLightboxIndex((lightboxIndex + 1) % lightboxMediaItems.length);
  }, [lightboxIndex, lightboxMediaItems.length]);

  const goPrev = useCallback(() => {
    if (lightboxIndex === null) return;
    setLightboxIndex(
      (lightboxIndex - 1 + lightboxMediaItems.length) % lightboxMediaItems.length
    );
  }, [lightboxIndex, lightboxMediaItems.length]);

  const goToAdjacentVideo = useCallback(
    (direction: 1 | -1) => {
      if (lightboxIndex === null || lightboxMediaItems.length < 2) return;
      for (let offset = 1; offset < lightboxMediaItems.length; offset += 1) {
        const candidateIndex =
          (lightboxIndex + direction * offset + lightboxMediaItems.length) %
          lightboxMediaItems.length;
        if (isLikelyVideo(lightboxMediaItems[candidateIndex])) {
          setLightboxIndex(candidateIndex);
          return;
        }
      }
    },
    [lightboxIndex, lightboxMediaItems],
  );

  const goNextVideo = useCallback(
    () => goToAdjacentVideo(1),
    [goToAdjacentVideo],
  );

  const goPrevVideo = useCallback(
    () => goToAdjacentVideo(-1),
    [goToAdjacentVideo],
  );

  const closeLightbox = useCallback(() => {
    setLightboxIndex(null);
    setShowShortcutHelp(false);
  }, []);

  useEffect(() => {
    if (lightboxIndex === null) return;
    const handleKey = (e: KeyboardEvent) => {
      const currentMedia = lightboxMediaItems[lightboxIndex];
      const isImage = currentMedia
        && !isLikelyVideo(currentMedia)
        && normalizeMediaCategory(currentMedia.category) !== 'audio';

      if (isImage && e.key === 'ArrowRight') {
        e.preventDefault();
        goNext();
      } else if (isImage && e.key === 'ArrowLeft') {
        e.preventDefault();
        goPrev();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeLightbox();
      } else if (e.key === '?') {
        e.preventDefault();
        setShowShortcutHelp((visible) => !visible);
      }
    };
    // Capture before Video.js stops propagation on player key events.
    document.addEventListener('keydown', handleKey, true);
    return () => document.removeEventListener('keydown', handleKey, true);
  }, [lightboxIndex, lightboxMediaItems, closeLightbox, goNext, goPrev]);

  const openLightbox = (mediaItem: ContentMediaInfo) => {
    const idx = lightboxMediaItems.findIndex((m) => m.id === mediaItem.id);
    if (idx >= 0) setLightboxIndex(idx);
  };

  const withProtectedAuth = useCallback(
    (url: string | null | undefined): string | null => backendResourceUrl(url),
    [],
  );

  const getStreamUrl = useCallback(
    (mediaItem: ContentMediaInfo): string =>
      withProtectedAuth(mediaItem.local_url) || getMediaFileUrl(item.site, mediaItem.id),
    [item.site, withProtectedAuth],
  );

  const getThumbnailUrl = useCallback(
    (mediaItem: ContentMediaInfo): string | null => withProtectedAuth(mediaItem.thumb_url),
    [withProtectedAuth],
  );

  const getFallbackThumbnailUrl = useCallback(
    (mediaItem: ContentMediaInfo): string | null => withProtectedAuth(
      mediaItem.fallback_thumb_url,
    ),
    [withProtectedAuth],
  );

  /** Resolve the best playback URL for a media item */
  const getPlayUrl = (m: ContentMediaInfo): string => getStreamUrl(m);

  const expiry = formatExpiry(item.expires_at);
  const typeLabel = CONTENT_TYPE_LABELS[item.content_type] ?? item.content_type;
  const typeIcon = CONTENT_TYPE_ICONS[item.content_type] ?? '📄';
  const createdAt = formatDateTime(item.created_at);

  const rawText = item.text ?? '';
  const plainText = stripHtml(rawText);

  const hasRichContent = rawText.includes('<a ');
  const sanitizedHtml = hasRichContent
    ? sanitizeHtml(rawText)
    : '';
  const highlightedHtml = hasRichContent
    ? highlightSanitizedHtml(sanitizedHtml, highlightText)
    : '';

  const visibleMedia = mediaItems.slice(0, MAX_VISIBLE_MEDIA);
  const extraCount = mediaItems.length - MAX_VISIBLE_MEDIA;
  const canCopyLink = item.content_type !== 'message' && item.content_type !== 'story';
  const hasMedia = mediaItems.length > 0;

  const handleMediaError = (mediaId: number) => {
    setFailedMedia((prev) => new Set(prev).add(mediaId));
  };

  useEffect(() => {
    const el = textRef.current;
    if (!el || textExpanded) return;
    const checkOverflow = () => {
      setTextHasOverflow(el.scrollHeight - el.clientHeight > 1);
    };
    checkOverflow();
    const ro = new ResizeObserver(checkOverflow);
    ro.observe(el);
    return () => ro.disconnect();
  }, [highlightText, rawText, textExpanded]);

  const profilePath = `/users/${item.user_id}?site=${encodeURIComponent(item.site)}&source=content`;
  const linkIdentifier = String(item.user_id);
  const siteKey = item.site.toLowerCase();
  const contentLink = siteKey === 'onlyfans'
    ? `https://onlyfans.com/${encodeURIComponent(linkIdentifier)}/${item.id}`
    : siteKey === 'fansly'
      ? `https://fansly.com/${encodeURIComponent(linkIdentifier)}/${item.id}`
      : `${window.location.origin}${profilePath}`;
  const siteProfileLink = siteKey === 'onlyfans'
    ? `https://onlyfans.com/${encodeURIComponent(linkIdentifier)}`
    : siteKey === 'fansly'
      ? `https://fansly.com/${encodeURIComponent(linkIdentifier)}`
      : `${window.location.origin}${profilePath}`;

  const copyToClipboard = useCallback(async (value: string) => {
    try {
      await copyText(value);
      return true;
    } catch {
      try {
        const ta = document.createElement('textarea');
        ta.value = value;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
      } catch {
        return false;
      }
    }
  }, []);

  const handleViewProfile = () => {
    setMenuOpen(false);
    window.open(siteProfileLink, '_blank', 'noopener,noreferrer');
  };

  const handleCopyId = async () => {
    await copyToClipboard(String(item.id));
    setMenuOpen(false);
  };

  const handleCopyLink = async () => {
    await copyToClipboard(contentLink);
    setMenuOpen(false);
  };

  const handleDownload = () => {
    if (!hasMedia) {
      setMenuOpen(false);
      return;
    }

    const defaultExtByCategory: Record<string, string> = {
      image: '.jpg',
      video: '.mp4',
      videos: '.mp4',
      audio: '.mp3',
      gif: '.gif',
    };

    mediaItems.forEach((m, idx) => {
      const url = getStreamUrl(m);
      const path = (() => {
        try {
          return new URL(url, window.location.origin).pathname;
        } catch {
          return '';
        }
      })();
      const basename = path.split('/').pop() || '';
      const hasExt = basename.includes('.');
      const fallbackExt = defaultExtByCategory[normalizeMediaCategory(m.category)] || '';
      const fallbackName = `${item.site}-${item.content_type}-${item.id}-${m.id}-${idx + 1}${fallbackExt}`;
      const filename = hasExt ? basename : fallbackName;

      // Slight staggering reduces browser drop-off when queuing multiple downloads.
      window.setTimeout(() => {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        anchor.rel = 'noopener';
        anchor.style.display = 'none';
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
      }, idx * 80);
    });

    setMenuOpen(false);
  };

  const handleHideUser = () => {
    setMenuOpen(false);
    onHideUser?.(item.user_id, item.username);
  };

  return (
    <div className="content-card">
      {/* Header */}
      <div className="content-card-header">
        <div className="content-card-avatar">
          <span>{typeIcon}</span>
        </div>
        <div className="content-card-identity">
          <span className="content-card-username">
            {item.username ?? `User ${item.user_id}`}
          </span>
          <Link className="content-card-handle" to={profilePath}>
            @{item.username ?? item.user_id}
          </Link>
        </div>
        <div className="content-card-meta">
          {['post', 'story', 'message'].includes(item.content_type) && <FavouriteButton entity={{ site: item.site, entity_type: item.content_type as 'post' | 'story' | 'message', entity_id: item.id }} initialFavorite={item.favorite} />}
          {item.price > 0 && (
            <span className="content-card-price">{formatPrice(item.price)}</span>
          )}
          <span className="content-card-date">
            {createdAt.date}
            {createdAt.time && (
              <>
                <br />
                <small className="content-card-time">{createdAt.time}</small>
              </>
            )}
          </span>
          {expiry && (
            <span className="content-card-expiry" title="Time until expiry">
              ⏱ {expiry}
            </span>
          )}
          <div className="content-card-menu-wrapper" ref={menuRef}>
            <button
              className="content-card-menu-btn"
              onClick={() => setMenuOpen(!menuOpen)}
              title="Options"
            >
              ⋯
            </button>
            {menuOpen && (
              <div className="content-card-dropdown">
                <button className="content-card-dropdown-item" onClick={handleViewProfile}>
                  👤 View Profile
                </button>
                <button className="content-card-dropdown-item" onClick={handleCopyId}>
                  📋 Copy ID
                </button>
                {canCopyLink && (
                  <button className="content-card-dropdown-item" onClick={handleCopyLink}>
                    🔗 Copy Link
                  </button>
                )}
                {hasMedia && (
                  <button className="content-card-dropdown-item" onClick={handleDownload}>
                    ⬇️ Download
                  </button>
                )}
                <hr className="content-card-dropdown-divider" />
                <button
                  className="content-card-dropdown-item content-card-dropdown-danger"
                  onClick={handleHideUser}
                >
                  🚫 Hide user from results
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Text body */}
      {plainText && (
        <div className="content-card-text">
          {hasRichContent ? (
            <p
              ref={textRef}
              className={`content-card-text-body ${!textExpanded ? 'is-clamped' : ''}`}
              dangerouslySetInnerHTML={{ __html: highlightedHtml }}
            />
          ) : (
            <p
              ref={textRef}
              className={`content-card-text-body ${!textExpanded ? 'is-clamped' : ''}`}
            >
              {renderHighlightedText(plainText, highlightText)}
            </p>
          )}
          {(textHasOverflow || textExpanded) && (
            <button
              className="content-card-see-more"
              onClick={() => setTextExpanded((prev) => !prev)}
            >
              {textExpanded ? 'See less' : 'See more'}
            </button>
          )}
        </div>
      )}

      {/* Media gallery */}
      {visibleMedia.length > 0 && (
        <div className="content-card-media">
          <div
            className={`content-card-media-grid media-count-${Math.min(visibleMedia.length, 4)}`}
          >
            {visibleMedia.map((m, idx) => {
              const streamUrl = getStreamUrl(m);
              const thumbUrl = getThumbnailUrl(m);
              const fallbackThumbUrl = getFallbackThumbnailUrl(m);
              const isLast = idx === visibleMedia.length - 1 && extraCount > 0;

              if (failedMedia.has(m.id)) {
                return (
                  <div key={m.id} className="content-card-media-item media-fallback" onClick={() => openLightbox(m)} role="button" tabIndex={0}>
                    <span className="media-fallback-icon">
                      {isLikelyVideo(m) ? '🎬' : normalizeMediaCategory(m.category) === 'audio' ? '🎵' : '🖼️'}
                    </span>
                    <span className="media-fallback-label">
                      {isLikelyVideo(m) ? 'Video' : m.category}
                    </span>
                  </div>
                );
              }

              if (isLikelyVideo(m)) {
                // Never use the full stream as a card preview. If a thumbnail
                // was not generated, loading <video preload="metadata"> here
                // makes every visible card resolve the stream (including DRM /
                // remote fallback work) during page refresh.
                const hasThumbnail = !!thumbUrl;
                return (
                  <div key={m.id} className="content-card-media-item" onClick={() => openLightbox(m)} role="button" tabIndex={0}>
                    {hasThumbnail ? (
                      <ContentThumbnail
                        src={thumbUrl}
                        fallbackSrc={fallbackThumbUrl}
                        alt=""
                        onFinalError={() => handleMediaError(m.id)}
                      />
                    ) : (
                      <div className="media-fallback" aria-label="Video preview unavailable">
                        <span className="media-fallback-icon">🎬</span>
                        <span className="media-fallback-label">Video</span>
                      </div>
                    )}
                    <div className="content-card-media-play-overlay">
                      <span className="content-card-play-icon">▶</span>
                    </div>
                    {isLast && (
                      <div className="content-card-media-overlay">
                        +{extraCount}
                      </div>
                    )}
                    {m.duration && (
                      <div className="content-card-media-duration">
                        🎬 {formatDuration(m.duration)}
                      </div>
                    )}
                  </div>
                );
              }

              if (normalizeMediaCategory(m.category) === 'audio') {
                return (
                  <div key={m.id} className="content-card-media-item media-audio" onClick={() => openLightbox(m)} role="button" tabIndex={0}>
                    <span className="media-audio-icon">🎵</span>
                    {/* Duration is already in the payload; loading metadata
                        here would open stream requests while paging. */}
                    <audio
                      src={streamUrl}
                      preload="none"
                      controls
                      onClick={(e) => e.stopPropagation()}
                      onError={() => handleMediaError(m.id)}
                    />
                    {m.duration && (
                      <div className="content-card-media-duration">
                        🎵 {formatDuration(m.duration)}
                      </div>
                    )}
                  </div>
                );
              }

              // Default: images. A thumbnail must never fall back to the full
              // stream URL: that would make a missing thumbnail trigger the
              // expensive stream endpoint during initial page rendering.
              if (!thumbUrl) {
                return (
                  <div key={m.id} className="content-card-media-item media-fallback" onClick={() => openLightbox(m)} role="button" tabIndex={0}>
                    <span className="media-fallback-icon">🖼️</span>
                    <span className="media-fallback-label">Image preview unavailable</span>
                    {isLast && (
                      <div className="content-card-media-overlay">
                        +{extraCount}
                      </div>
                    )}
                  </div>
                );
              }

              // Default: images
              return (
                <div key={m.id} className="content-card-media-item" onClick={() => openLightbox(m)} role="button" tabIndex={0}>
                  <ContentThumbnail
                    src={thumbUrl}
                    fallbackSrc={fallbackThumbUrl}
                    alt=""
                    onFinalError={() => handleMediaError(m.id)}
                  />
                  {isLast && (
                    <div className="content-card-media-overlay">
                      +{extraCount}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="content-card-footer">
        <div className="content-card-badges">
          <span className={`content-card-type-badge content-card-type-${item.content_type}`}>
            {typeLabel}
          </span>
          {item.price > 0 && (
            <span className={`content-card-paid-badge ${item.paid ? 'paid' : 'locked'}`}>
              {item.paid ? '✓ Paid' : '🔒 Locked'}
            </span>
          )}
          {item.archived && <span className="content-card-badge-archived">📦 Archived</span>}
          {item.deleted && <span className="content-card-badge-deleted">🗑️ Deleted</span>}
        </div>
        <div className="content-card-actions">
          {isLockedPaid && onBuyLocked && (
            <button
              className="content-card-buy-btn"
              title="Add to orders"
              onClick={() => onBuyLocked(item)}
              disabled={buyPending}
            >
              {buyPending ? 'Adding…' : 'Buy'}
            </button>
          )}
          <button className="content-card-action-btn" title="Save content">❤️</button>
          <button className="content-card-action-btn" title="Share content">↗️</button>
        </div>
      </div>

      {/* Lightbox */}
      {lightboxIndex !== null && lightboxMediaItems[lightboxIndex] && (() => {
        const current = lightboxMediaItems[lightboxIndex];
        const isVideo = isLikelyVideo(current);
        const isAudio = normalizeMediaCategory(current.category) === 'audio';
        const playUrl = getPlayUrl(current);

        return (
          <div className="cc-lightbox-overlay" onClick={closeLightbox}>
            <div className="cc-lightbox-content" onClick={(e) => e.stopPropagation()}>
              <button className="cc-lightbox-close" onClick={closeLightbox}>×</button>

              {/* Counter */}
              {lightboxMediaItems.length > 1 && (
                <div className="cc-lightbox-counter">
                  {lightboxIndex + 1} / {lightboxMediaItems.length}
                </div>
              )}

              {showShortcutHelp && isVideo && (
                <div className="cc-lightbox-shortcut-help" role="status">
                  <strong>Keyboard shortcuts</strong>
                  <span>Space/K play or pause</span>
                  <span>←/→ seek · ↑/↓ volume</span>
                  <span>0-9 seek 0%-90%</span>
                  <span>M mute · F fullscreen</span>
                  <span>Ctrl+←/→ previous/next video</span>
                </div>
              )}

              {/* Media */}
              <div className="cc-lightbox-media" data-media-category={current.category}>
                {isVideo ? (
                  <LazyVideoPlayer
                    key={current.id}
                    src={playUrl}
                    controls
                    autoplay
                    fluid={false}
                    className="vjs-lightbox"
                    keyboardShortcuts
                    onPrevious={goPrevVideo}
                    onNext={goNextVideo}
                  />
                ) : isAudio ? (
                  <div className="cc-lightbox-audio">
                    <span className="cc-lightbox-audio-icon">🎵</span>
                    <audio src={playUrl} controls autoPlay />
                  </div>
                ) : (
                  <img
                    src={playUrl}
                    alt=""
                    className="cc-lightbox-image"
                  />
                )}
              </div>

              {/* Prev / Next arrows */}
              {lightboxMediaItems.length > 1 && (
                <>
                  <button className="cc-lightbox-nav cc-lightbox-prev" onClick={goPrev} aria-label="Previous">‹</button>
                  <button className="cc-lightbox-nav cc-lightbox-next" onClick={goNext} aria-label="Next">›</button>
                </>
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
});
