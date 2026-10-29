import { SETUP_STEP_LABELS } from '../lib/setupUtils';

interface SetupStepIndicatorProps {
  current: number;
  labels?: readonly string[];
}

export function SetupStepIndicator({ current, labels = SETUP_STEP_LABELS }: SetupStepIndicatorProps) {
  return (
    <div className="setup-steps">
      {labels.map((label, index) => {
        const stepNum = index + 1;
        const isActive = stepNum === current;
        const isDone = stepNum < current;
        const cls = isDone ? 'done' : isActive ? 'active' : 'pending';

        return (
          <div
            key={stepNum}
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
          >
            <div className={`setup-step-label ${cls}`}>
              <div className={`setup-step-dot ${cls}`}>{isDone ? '✓' : stepNum}</div>
              <span>{label}</span>
            </div>
            {index < labels.length - 1 && (
              <div className={`setup-step-line ${isDone ? 'done' : 'pending'}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

