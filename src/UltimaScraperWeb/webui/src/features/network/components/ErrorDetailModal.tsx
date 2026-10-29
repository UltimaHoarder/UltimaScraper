import type { AnalyzerErrorDetail } from '../../../api/types/network';

interface ErrorDetailModalProps {
  detail: AnalyzerErrorDetail | null;
  onClose: () => void;
}

export function ErrorDetailModal({ detail, onClose }: ErrorDetailModalProps) {
  if (!detail) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="error-detail-modal" onClick={(event) => event.stopPropagation()}>
        <div className="error-detail-header">
          <h3>{detail.endpoint} Request Errors</h3>
          <button className="modal-close-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="error-detail-content">
          <table className="error-detail-table">
            <thead>
              <tr>
                <th>Error Type</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(detail.errors)
                .sort(([, leftCount], [, rightCount]) => rightCount - leftCount)
                .map(([errorType, count]) => {
                  const displayError = errorType.startsWith('error:')
                    ? errorType.substring(6)
                    : errorType;

                  return (
                    <tr key={errorType}>
                      <td className="error-type-cell">{displayError}</td>
                      <td className="error-count-cell">{count}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
          <div className="error-detail-total">
            Total: {Object.values(detail.errors).reduce((sum, count) => sum + count, 0)} errors
          </div>
        </div>
      </div>
    </div>
  );
}
