import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

interface ScrapeSplitButtonProps {
  primaryLabel: string;
  onPrimaryClick: () => void;
  onDelegateClick: () => void;
  disabled?: boolean;
  delegatePending?: boolean;
}

export function ScrapeSplitButton({
  primaryLabel,
  onPrimaryClick,
  onDelegateClick,
  disabled = false,
  delegatePending = false,
}: ScrapeSplitButtonProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0, minWidth: 0 });
  const wrapperRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;

    const updatePosition = () => {
      if (wrapperRef.current) {
        const rect = wrapperRef.current.getBoundingClientRect();
        setMenuPosition({
          top: rect.bottom + 4,
          left: rect.left,
          minWidth: rect.width,
        });
      }
    };

    updatePosition();
    window.addEventListener('scroll', updatePosition, true);
    window.addEventListener('resize', updatePosition);
    return () => {
      window.removeEventListener('scroll', updatePosition, true);
      window.removeEventListener('resize', updatePosition);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (wrapperRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setMenuOpen(false);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenuOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [menuOpen]);

  const handleToggleClick = () => {
    if (disabled) return;
    setMenuOpen((previous) => !previous);
  };

  const handlePrimaryClick = () => {
    setMenuOpen(false);
    onPrimaryClick();
  };

  const handleDelegate = () => {
    setMenuOpen(false);
    onDelegateClick();
  };

  return (
    <div className="split-action" ref={wrapperRef}>
      <button
        type="button"
        className="btn-primary split-action__primary"
        onClick={handlePrimaryClick}
        disabled={disabled}
      >
        {primaryLabel}
      </button>
      <button
        type="button"
        className="btn-primary split-action__toggle"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        aria-label="More scrape actions"
        title="More scrape actions"
        onClick={handleToggleClick}
        disabled={disabled}
      >
        <span aria-hidden="true">▾</span>
      </button>
      {menuOpen
        ? createPortal(
            <div
              ref={menuRef}
              className="split-action__menu"
              role="menu"
              aria-label="Scrape actions"
              style={{
                position: 'fixed',
                top: menuPosition.top,
                left: menuPosition.left,
                minWidth: menuPosition.minWidth,
              }}
            >
              <button
                type="button"
                className="split-action__menu-item"
                role="menuitem"
                onClick={handleDelegate}
                disabled={delegatePending || disabled}
              >
                {delegatePending ? 'Delegating...' : 'Delegate'}
              </button>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
