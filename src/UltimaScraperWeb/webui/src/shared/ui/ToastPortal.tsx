import { createPortal } from 'react-dom';

export interface ToastPortalState {
  id?: string;
  title?: string;
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
}

export interface ToastPortalProps {
  toast?: ToastPortalState | null;
  toasts?: ToastPortalState[];
  onDismiss?: (itemOrId?: ToastPortalState | string) => void;
}

export function ToastPortal({ toast, toasts, onDismiss }: ToastPortalProps) {
  if (typeof document === 'undefined') {
    return null;
  }

  const items = toasts ?? (toast ? [toast] : []);
  if (items.length === 0) {
    return null;
  }

  const getIcon = (type: ToastPortalState['type']) => {
    switch (type) {
      case 'success':
        return '✓';
      case 'warning':
        return '⚠';
      case 'info':
        return 'ℹ';
      case 'error':
      default:
        return '✗';
    }
  };

  return createPortal(
    <div className="toast-container" role="region" aria-label="Notifications">
      {items.map((item, index) => {
        const key = item.id || `toast-${index}-${item.title || ''}-${item.message}`;
        return (
          <div
            key={key}
            className={`toast ${item.type} toast-${item.type}`}
            role={item.type === 'error' ? 'alert' : 'status'}
            aria-live={item.type === 'error' ? 'assertive' : 'polite'}
            aria-atomic="true"
          >
            <span className="toast-icon">{getIcon(item.type)}</span>
            <div className="toast-body">
              {item.title && <strong className="toast-title">{item.title}</strong>}
              <span className="toast-message">{item.message}</span>
            </div>
            <button
              type="button"
              className="toast-close"
              onClick={() => onDismiss?.(item.id || item)}
              aria-label="Close notification"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
