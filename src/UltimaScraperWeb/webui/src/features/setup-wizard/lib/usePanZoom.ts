import { useCallback, useEffect, useRef, useState, type PointerEvent, type RefObject } from 'react';

export interface View {
  x: number;
  y: number;
  scale: number;
}

const MIN_SCALE = 0.2;
const MAX_SCALE = 3;
const BUTTON_STEP = 1.25;

const clamp = (scale: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));

/**
 * Drag to pan and wheel, pinch or buttons to zoom a canvas inside a fixed
 * viewport, so the page around it never scrolls. Until the person moves it,
 * the canvas stays fitted to the viewport as either changes size.
 */
export function usePanZoom(viewportRef: RefObject<HTMLElement | null>, canvasRef: RefObject<HTMLElement | null>) {
  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const moved = useRef(false);
  const pointers = useRef(new Map<number, { x: number; y: number }>());

  const fitted = useCallback((): View | null => {
    const viewport = viewportRef.current;
    const canvas = canvasRef.current;
    if (!viewport || !canvas) return null;
    const { clientWidth: vw, clientHeight: vh } = viewport;
    const { offsetWidth: cw, offsetHeight: ch } = canvas;
    if (!vw || !vh || !cw || !ch) return null;
    const scale = clamp(Math.min(vw / cw, vh / ch, 1));
    return { scale, x: (vw - cw * scale) / 2, y: Math.max(0, (vh - ch * scale) / 2) };
  }, [viewportRef, canvasRef]);

  useEffect(() => {
    const viewport = viewportRef.current;
    const canvas = canvasRef.current;
    if (!viewport || !canvas || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (moved.current) return;
      const next = fitted();
      if (next) setView(next);
    });
    observer.observe(viewport);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [viewportRef, canvasRef, fitted]);

  /** Zoom by a factor, keeping the point (px, py) of the viewport still. */
  const zoomAt = useCallback((factor: number, px: number, py: number) => {
    setView((current) => {
      const scale = clamp(current.scale * factor);
      const ratio = scale / current.scale;
      return { scale, x: px - (px - current.x) * ratio, y: py - (py - current.y) * ratio };
    });
  }, []);

  // The wheel zooms at the pointer; a non-passive listener keeps the page still.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      moved.current = true;
      const box = viewport.getBoundingClientRect();
      zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX - box.left, event.clientY - box.top);
    };
    viewport.addEventListener('wheel', onWheel, { passive: false });
    return () => viewport.removeEventListener('wheel', onWheel);
  }, [viewportRef, zoomAt]);

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if ((event.target as Element).closest('button, a, input')) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
  };

  const onPointerMove = (event: PointerEvent<HTMLElement>) => {
    const previous = pointers.current.get(event.pointerId);
    if (!previous) return;
    const next = { x: event.clientX, y: event.clientY };
    moved.current = true;
    if (pointers.current.size === 1) {
      pointers.current.set(event.pointerId, next);
      setView((current) => ({ ...current, x: current.x + next.x - previous.x, y: current.y + next.y - previous.y }));
      return;
    }
    // Two fingers: zoom by how far apart they moved, about their midpoint.
    const other = [...pointers.current.entries()].find(([id]) => id !== event.pointerId)?.[1];
    pointers.current.set(event.pointerId, next);
    if (!other) return;
    const before = Math.hypot(previous.x - other.x, previous.y - other.y);
    const after = Math.hypot(next.x - other.x, next.y - other.y);
    if (!before) return;
    const box = event.currentTarget.getBoundingClientRect();
    zoomAt(after / before, (next.x + other.x) / 2 - box.left, (next.y + other.y) / 2 - box.top);
  };

  const onPointerEnd = (event: PointerEvent<HTMLElement>) => {
    pointers.current.delete(event.pointerId);
  };

  const zoomBy = (factor: number) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    moved.current = true;
    zoomAt(factor, viewport.clientWidth / 2, viewport.clientHeight / 2);
  };

  return {
    view,
    handlers: { onPointerDown, onPointerMove, onPointerUp: onPointerEnd, onPointerCancel: onPointerEnd },
    zoomIn: () => zoomBy(BUTTON_STEP),
    zoomOut: () => zoomBy(1 / BUTTON_STEP),
    canZoomIn: view.scale < MAX_SCALE,
    canZoomOut: view.scale > MIN_SCALE,
    fit: () => {
      moved.current = false;
      const next = fitted();
      if (next) setView(next);
    },
  };
}
