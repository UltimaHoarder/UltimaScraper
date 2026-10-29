import type { ReactNode } from 'react';

import type { AuthCredential } from '../../../../api/types/auths';
import type { TaskDefinition } from '../../../../api/types/jobs';

interface JobCreatorTaskBuilderSectionProps {
  taskTypes: TaskDefinition[];
  selectedTaskType: string;
  onTaskTypeChange: (taskId: string) => void;
  selectedTaskDef?: TaskDefinition;
  taskSupportsAuth: boolean;
  selectedAuthId: number | 'all';
  onSelectedAuthIdChange: (value: number | 'all') => void;
  activeAuths: AuthCredential[];
  loadingAuths: boolean;
  currentSite: string;
  renderParamInput: (
    param: TaskDefinition['parameters'][0],
    paramValues?: Record<string, unknown>,
    onChangeParam?: (name: string, value: unknown) => void
  ) => ReactNode;
  onAddTask: () => void;
}

export function JobCreatorTaskBuilderSection({
  taskTypes,
  selectedTaskType,
  onTaskTypeChange,
  selectedTaskDef,
  taskSupportsAuth,
  selectedAuthId,
  onSelectedAuthIdChange,
  activeAuths,
  loadingAuths,
  currentSite,
  renderParamInput,
  onAddTask,
}: JobCreatorTaskBuilderSectionProps) {
  return (
    <div className="creator-section">
      <h3 className="section-title">
        <span className="section-icon">⚙️</span>
        Task Builder
      </h3>

      <div className="form-field">
        <label className="field-label">Task Type</label>
        <select
          value={selectedTaskType}
          onChange={(event) => onTaskTypeChange(event.target.value)}
          className="field-select"
        >
          {taskTypes.map((task) => (
            <option key={task.task_id} value={task.task_id}>
              {task.name} — {task.category}
            </option>
          ))}
        </select>
      </div>

      {selectedTaskDef && (
        <>
          <div className="task-description-box">
            <span className="description-icon">ℹ️</span>
            {selectedTaskDef.description}
          </div>

          {taskSupportsAuth && (
            <div className="form-field">
              <label className="field-label">Auth Account</label>
              <select
                value={String(selectedAuthId)}
                onChange={(event) => {
                  const value = event.target.value;
                  onSelectedAuthIdChange(value === 'all' ? 'all' : Number(value));
                }}
                className="field-select"
                disabled={loadingAuths}
              >
                <option value="all">All active auths ({activeAuths.length})</option>
                {activeAuths.map((auth) => (
                  <option key={`${auth.site}-${auth.id}`} value={auth.id}>
                    {auth.username || `Auth ${auth.user_id}`} (ID {auth.user_id})
                  </option>
                ))}
              </select>
              <span className="field-hint">
                {loadingAuths
                  ? 'Loading active auth accounts...'
                  : activeAuths.length === 0
                    ? `No active auths found for ${currentSite}.`
                    : selectedAuthId === 'all'
                      ? `Tasks will be duplicated for each of the ${activeAuths.length} active auths.`
                      : 'Username search is filtered to show only users linked to this auth.'}
              </span>
            </div>
          )}

          <div className="task-params-grid">
            {selectedTaskDef.parameters.map((param) => (
              <div key={param.name} className="form-field">
                {param.param_type !== 'boolean' && (
                  <label className="field-label">
                    {param.label}
                    {param.required && <span className="field-required">*</span>}
                  </label>
                )}
                {renderParamInput(param)}
                {param.description && param.param_type !== 'boolean' && (
                  <span className="field-hint">{param.description}</span>
                )}
              </div>
            ))}
          </div>

          <button className="btn btn-secondary btn-add-task" onClick={onAddTask}>
            <span>➕</span>
            Add Task to Queue
          </button>
        </>
      )}
    </div>
  );
}
