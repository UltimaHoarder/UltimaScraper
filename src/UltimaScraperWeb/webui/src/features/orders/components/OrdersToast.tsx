interface OrdersToastProps {
  toast: { message: string; type: 'success' | 'error' } | null;
  onDismiss: () => void;
}

export function OrdersToast({ toast, onDismiss }: OrdersToastProps) {
  if (!toast) {
    return null;
  }

  return (
    <div className={`toast toast-${toast.type}`}>
      <span className="toast-icon">{toast.type === 'success' ? '✓' : '✗'}</span>
      <span className="toast-message">{toast.message}</span>
      <button className="toast-close" onClick={onDismiss}>
        ×
      </button>
    </div>
  );
}
