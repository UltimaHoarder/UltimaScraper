import { useCallback, useEffect, useRef, useState } from 'react';

export interface HoverPreviewState {
  imageUrl: string;
  alt: string;
  kind: 'avatar' | 'header';
  targetRect: DOMRect;
}

export function useImageHoverPreview(delayMs = 1000) {
  const [preview, setPreview] = useState<HoverPreviewState | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const graceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeTargetRef = useRef<HTMLElement | null>(null);

  const startHover = useCallback(
    (
      target: HTMLElement,
      imageUrl: string | null | undefined,
      alt: string,
      kind: 'avatar' | 'header'
    ) => {
      if (graceTimerRef.current) {
        clearTimeout(graceTimerRef.current);
        graceTimerRef.current = null;
      }
      if (!imageUrl || imageUrl.startsWith('data:image/svg')) {
        return;
      }
      if (activeTargetRef.current === target && (timerRef.current !== null || preview !== null)) {
        return;
      }
      activeTargetRef.current = target;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => {
        const rect = target.getBoundingClientRect();
        setPreview({
          imageUrl,
          alt,
          kind,
          targetRect: rect,
        });
        timerRef.current = null;
      }, delayMs);
    },
    [delayMs, preview]
  );

  const endHover = useCallback(() => {
    activeTargetRef.current = null;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (preview) {
      if (graceTimerRef.current) {
        clearTimeout(graceTimerRef.current);
      }
      graceTimerRef.current = setTimeout(() => {
        setPreview(null);
      }, 180);
    }
  }, [preview]);

  const enterPreview = useCallback(() => {
    if (graceTimerRef.current) {
      clearTimeout(graceTimerRef.current);
      graceTimerRef.current = null;
    }
  }, []);

  const leavePreview = useCallback(() => {
    activeTargetRef.current = null;
    setPreview(null);
  }, []);

  const closeImmediate = useCallback(() => {
    activeTargetRef.current = null;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (graceTimerRef.current) {
      clearTimeout(graceTimerRef.current);
      graceTimerRef.current = null;
    }
    setPreview(null);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (graceTimerRef.current) clearTimeout(graceTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!preview) return;

    const handleScroll = () => {
      closeImmediate();
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeImmediate();
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true, capture: true });
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('scroll', handleScroll, { capture: true });
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [preview, closeImmediate]);

  return {
    preview,
    startHover,
    endHover,
    enterPreview,
    leavePreview,
    closeImmediate,
  };
}
