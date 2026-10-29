interface JobCreatorScheduleSectionProps {
  scheduleEnabled: boolean;
  onScheduleEnabledChange: (value: boolean) => void;
  scheduleType: 'once' | 'interval' | 'cron';
  onScheduleTypeChange: (value: 'once' | 'interval' | 'cron') => void;
  scheduleAt: string;
  onScheduleAtChange: (value: string) => void;
  intervalValue: number;
  onIntervalValueChange: (value: number) => void;
  intervalUnit: 'minutes' | 'hours' | 'days';
  onIntervalUnitChange: (value: 'minutes' | 'hours' | 'days') => void;
  startImmediately: boolean;
  onStartImmediatelyChange: (value: boolean) => void;
  cronExpression: string;
  onCronExpressionChange: (value: string) => void;
}

export function JobCreatorScheduleSection({
  scheduleEnabled,
  onScheduleEnabledChange,
  scheduleType,
  onScheduleTypeChange,
  scheduleAt,
  onScheduleAtChange,
  intervalValue,
  onIntervalValueChange,
  intervalUnit,
  onIntervalUnitChange,
  startImmediately,
  onStartImmediatelyChange,
  cronExpression,
  onCronExpressionChange,
}: JobCreatorScheduleSectionProps) {
  return (
    <div className="creator-section">
      <h3 className="section-title">
        <span className="section-icon">⏰</span>
        Schedule
      </h3>
      <div className="form-field">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={scheduleEnabled}
            onChange={(event) => onScheduleEnabledChange(event.target.checked)}
            className="field-checkbox"
          />
          <span>Enable scheduling</span>
        </label>
        <span className="field-hint">
          Run this job at a specific time or on a recurring interval.
        </span>
      </div>

      {scheduleEnabled && (
        <>
          <div className="form-field">
            <label className="field-label">Schedule Type</label>
            <select
              value={scheduleType}
              onChange={(event) =>
                onScheduleTypeChange(event.target.value as 'once' | 'interval' | 'cron')
              }
              className="field-select"
            >
              <option value="interval">Run every...</option>
              <option value="once">Run once at...</option>
              <option value="cron">Cron expression</option>
            </select>
          </div>

          {scheduleType === 'once' ? (
            <div className="form-field">
              <label className="field-label">Run at</label>
              <input
                type="datetime-local"
                value={scheduleAt}
                onChange={(event) => onScheduleAtChange(event.target.value)}
                className="field-input"
              />
              <span className="field-hint">Local time; will be converted to UTC on save.</span>
            </div>
          ) : scheduleType === 'interval' ? (
            <div className="form-field">
              <label className="field-label">Run every</label>
              <div className="schedule-row">
                <input
                  type="number"
                  min={1}
                  value={intervalValue}
                  onChange={(event) => onIntervalValueChange(Number(event.target.value))}
                  className="field-input"
                />
                <select
                  value={intervalUnit}
                  onChange={(event) =>
                    onIntervalUnitChange(event.target.value as 'minutes' | 'hours' | 'days')
                  }
                  className="field-select"
                >
                  <option value="minutes">Minutes</option>
                  <option value="hours">Hours</option>
                  <option value="days">Days</option>
                </select>
              </div>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={startImmediately}
                  onChange={(event) => onStartImmediatelyChange(event.target.checked)}
                  className="field-checkbox"
                />
                <span>Start immediately, then repeat</span>
              </label>
              <span className="field-hint">
                Minimum 1 minute. Starts immediately if enabled, then repeats on this interval.
              </span>
            </div>
          ) : (
            <div className="form-field">
              <label className="field-label">Cron expression</label>
              <input
                type="text"
                value={cronExpression}
                onChange={(event) => onCronExpressionChange(event.target.value)}
                placeholder="e.g., */15 * * * *"
                className="field-input"
              />
              <span className="field-hint">
                Standard 5-field cron (minute hour day month weekday).
              </span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
