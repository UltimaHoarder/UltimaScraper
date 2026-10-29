import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { ConfirmDialogProps } from '../../../app/theme/types';

export function ConfirmDialog({
  isOpen, title, description, progress, confirmLabel = 'Confirm', cancelLabel = 'Cancel',
  tone = 'danger', isPending = false, onConfirm, onClose,
}: ConfirmDialogProps) {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  const pending = useRef(isPending);
  useEffect(() => { close.current = onClose; pending.current = isPending; }, [onClose, isPending]);

  useEffect(() => {
    if (!isOpen) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const initial = dialog.current?.querySelector<HTMLButtonElement>('button:not(:disabled)');
    (initial ?? dialog.current)?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        if (!pending.current) close.current();
      }
      if (event.key !== 'Tab') return;
      const buttons = dialog.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
      if (!buttons?.length) { event.preventDefault(); dialog.current?.focus(); return; }
      const first = buttons[0];
      const last = buttons[buttons.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener('keydown', keydown, true);
    return () => {
      document.removeEventListener('keydown', keydown, true);
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [isOpen]);

  if (!isOpen) return null;
  return createPortal(
    <div className="confirm-dialog__overlay atlas-confirm-overlay" onClick={() => { if (!isPending) onClose(); }}>
      <div ref={dialog} className="confirm-dialog atlas-confirm" role="dialog" aria-modal="true"
        aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} tabIndex={-1}
        aria-busy={isPending} onClick={(event) => event.stopPropagation()}>
        <div className={`atlas-confirm__classification atlas-confirm__classification--${tone}`}>SYSTEM CONTROL / CONFIRMATION</div>
        <h2 id={`${id}-title`} className="confirm-dialog__title">{title}</h2>
        <p id={`${id}-description`} className="confirm-dialog__description">{description}</p>
        {isPending && progress && (
          <div role="status" aria-live="polite" style={{ margin: '16px 0' }}>
            <progress aria-label="Job deletion progress" max={Math.max(progress.total, 1)}
              value={progress.total > 0 && progress.completed >= progress.total ? progress.completed : undefined}
              style={{ width: '100%' }} />
            <div>{progress.total > 0
              ? `${progress.completed} of ${progress.total} jobs finished${progress.failed ? `; ${progress.failed} failed` : ''}. Cleaning up job history…`
              : 'Finding jobs to delete…'}</div>
            {progress.rows !== undefined && <div>{progress.rows.toLocaleString()} history rows removed; cleaning {progress.table}.</div>}
          </div>
        )}
        <div className="confirm-dialog__actions">
          <button type="button" className="confirm-dialog__button confirm-dialog__button--secondary"
            disabled={isPending} onClick={onClose}>{cancelLabel}</button>
          <button type="button" className={`confirm-dialog__button confirm-dialog__button--${tone}`}
            disabled={isPending} onClick={onConfirm}>{isPending ? 'Working...' : confirmLabel}</button>
        </div>
      </div>
    </div>, document.body,
  );
}
