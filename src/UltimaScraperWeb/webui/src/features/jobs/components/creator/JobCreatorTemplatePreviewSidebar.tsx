import type { AuthCredential } from '../../../../api/types/auths';
import type { JobTemplateResponse } from '../../../../api/types/jobs';

interface JobCreatorTemplatePreviewSidebarProps {
  selectedTemplate: JobTemplateResponse;
  templateUsesUsernameParam: boolean;
  templateUsernames: string[];
  checkingSubData: boolean;
  previewTaskCount: number;
  selectedAuthId: number | 'all';
  authsPerUsername?: Record<string, number[]>;
  activeAuths: AuthCredential[];
  templateParams: Record<string, unknown>;
}

export function JobCreatorTemplatePreviewSidebar({
  selectedTemplate,
  templateUsesUsernameParam,
  templateUsernames,
  checkingSubData,
  previewTaskCount,
  selectedAuthId,
  authsPerUsername,
  activeAuths,
  templateParams,
}: JobCreatorTemplatePreviewSidebarProps) {
  const usernames = templateUsesUsernameParam ? templateUsernames : ['__all__'];
  const selectedContentTypes = Array.isArray(templateParams.content_types)
    ? (templateParams.content_types as string[])
    : null;
  const visibleTasks = selectedContentTypes
    ? selectedTemplate.tasks.filter((task) =>
        selectedContentTypes.includes(task.content_type_template)
      )
    : selectedTemplate.tasks;
  const site = (templateParams.site as string | undefined) || 'OnlyFans';

  return (
    <div className="creator-sidebar">
      <div className="creator-section">
        <h3 className="section-title">
          <span className="section-icon">📋</span>
          Task Preview
          {(templateUsesUsernameParam ? templateUsernames.length > 0 : true) && (
            <span className="task-count-badge">{checkingSubData ? '…' : previewTaskCount}</span>
          )}
        </h3>

        {templateUsesUsernameParam && templateUsernames.length === 0 ? (
          <div className="empty-queue">
            <span className="empty-icon">👤</span>
            <p className="empty-title">No usernames yet</p>
            <p className="empty-hint">Add usernames on the left to preview tasks</p>
          </div>
        ) : (
          <div className="template-preview">
            {usernames.map((username) => {
              const qualifyingIds = authsPerUsername?.[username];
              const qualifyingAuths =
                qualifyingIds && selectedAuthId === 'all'
                  ? activeAuths.filter((auth) => qualifyingIds.includes(auth.id))
                  : [];
              const skippedCount =
                qualifyingIds && selectedAuthId === 'all'
                  ? activeAuths.length - qualifyingAuths.length
                  : 0;

              return (
                <div key={username} className="tp-user-group">
                  {templateUsesUsernameParam && templateUsernames.length > 1 && (
                    <div className="tp-user-header">
                      <span className="tp-user-chip">@{username}</span>
                    </div>
                  )}

                  {templateUsesUsernameParam && selectedAuthId === 'all' && qualifyingIds && (
                    <div className="queue-param" style={{ marginBottom: '0.5rem', fontSize: '0.75rem' }}>
                      <span className="queue-param-key">auths:</span>
                      <span className="queue-param-value">
                        {qualifyingAuths.length === 0 ? (
                          <span style={{ color: 'var(--color-error, #f85149)' }}>
                            no sub data on any auth — skipped
                          </span>
                        ) : (
                          <>
                            {qualifyingAuths
                              .map((auth) => auth.username || `#${auth.user_id}`)
                              .join(', ')}
                            {skippedCount > 0 && (
                              <span
                                style={{
                                  color: 'var(--color-text-tertiary, #6e7681)',
                                  marginLeft: '0.375rem',
                                }}
                              >
                                (+{skippedCount} skipped)
                              </span>
                            )}
                          </>
                        )}
                      </span>
                    </div>
                  )}

                  <div className="task-queue">
                    {visibleTasks.map((task, index) => {
                      const resolvedContent =
                        task.content_type_template
                          .replace(/\{site\}/gi, site)
                          .replace(/\{username\}/gi, templateUsesUsernameParam ? username : '') ||
                        task.content_type_template;

                      return (
                        <div key={`${username}-${index}`} className="queue-task-card">
                          <div className="queue-task-header">
                            <span className="queue-task-number">#{index + 1}</span>
                            <span className={`queue-task-type tp-task-type--${task.task_type}`}>
                              {task.task_type}
                            </span>
                          </div>
                          <div className="queue-task-params">
                            {resolvedContent && (
                              <div className="queue-param">
                                <span className="queue-param-key">content:</span>
                                <span className="queue-param-value">{resolvedContent}</span>
                              </div>
                            )}
                            {task.depends_on.length > 0 && (
                              <div className="queue-param">
                                <span className="queue-param-key">after:</span>
                                <span className="queue-param-value tp-dep">
                                  {task.depends_on.join(', ')}
                                </span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
