import type { TaskPayload } from '../../../../api/types/jobs';

interface JobCreatorTaskQueueSidebarProps {
  tasks: TaskPayload[];
  onRemoveTask: (index: number) => void;
}

export function JobCreatorTaskQueueSidebar({
  tasks,
  onRemoveTask,
}: JobCreatorTaskQueueSidebarProps) {
  return (
    <div className="creator-sidebar">
      <div className="creator-section">
        <h3 className="section-title">
          <span className="section-icon">📋</span>
          Task Queue
          <span className="task-count-badge">{tasks.length}</span>
        </h3>

        {tasks.length === 0 ? (
          <div className="empty-queue">
            <span className="empty-icon">📭</span>
            <p className="empty-title">No tasks added</p>
            <p className="empty-hint">Add at least one task to create a job</p>
          </div>
        ) : (
          <div className="task-queue">
            {tasks.map((task, index) => (
              <div key={index} className="queue-task-card">
                <div className="queue-task-header">
                  <span className="queue-task-number">#{index + 1}</span>
                  <span className="queue-task-type">{task.task_type}</span>
                  <button
                    className="queue-task-remove"
                    onClick={() => onRemoveTask(index)}
                    title="Remove task"
                  >
                    ×
                  </button>
                </div>
                <div className="queue-task-params">
                  {Object.entries(task.params)
                    .filter(([, value]) => value !== null && value !== undefined && value !== '')
                    .map(([key, value]) => (
                      <div key={key} className="queue-param">
                        <span className="queue-param-key">{key}:</span>
                        <span className="queue-param-value">
                          {Array.isArray(value) ? value.join(', ') : String(value)}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
