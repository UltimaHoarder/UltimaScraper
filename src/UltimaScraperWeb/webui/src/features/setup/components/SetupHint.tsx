import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const VIEWPORT_MARGIN = 8;
const ANCHOR_GAP = 6;

/**
 * A "?" beside a setup label whose explanation shows on hover or focus.
 *
 * The explanation is rendered on document.body, because the setup card
 * clips its overflow, and is kept inside the window.
 */
export function SetupHint({ text }: { text: string }) {
  const anchor = useRef<HTMLSpanElement>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const id = useId();

  useLayoutEffect(() => {
    const anchorBox = anchor.current?.getBoundingClientRect();
    const element = bubble.current;
    if (!open || !anchorBox || !element) return;
    const { width, height } = element.getBoundingClientRect();
    // Below the "?" when it fits, otherwise above it.
    const below = anchorBox.bottom + ANCHOR_GAP;
    const top =
      below + height <= window.innerHeight - VIEWPORT_MARGIN
        ? below
        : Math.max(VIEWPORT_MARGIN, anchorBox.top - ANCHOR_GAP - height);
    const centred = anchorBox.left + anchorBox.width / 2 - width / 2;
    const left = Math.min(
      Math.max(centred, VIEWPORT_MARGIN),
      window.innerWidth - width - VIEWPORT_MARGIN,
    );
    element.style.top = `${top}px`;
    element.style.left = `${left}px`;
    element.style.visibility = 'visible';
  }, [open]);

  useEffect(() => {
    if (!open) return;
    // A fixed bubble would drift away from its label while the page moves.
    const close = () => setOpen(false);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  return (
    <>
      <span
        ref={anchor}
        className="setup-hint"
        tabIndex={0}
        role="img"
        aria-label="More information"
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        ?
      </span>
      {open &&
        createPortal(
          <div ref={bubble} id={id} role="tooltip" className="setup-hint-bubble">
            {text}
          </div>,
          document.body,
        )}
    </>
  );
}
