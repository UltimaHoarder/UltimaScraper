import type { JobCreatorMockModel, IntervalUnit, ScheduleType, SupportedSite } from './jobCreatorMockModel';
import { MOCK_SUBSCRIPTIONS } from './jobCreatorMockModel';

export function DualModeStudioConcept({ model }: { model: JobCreatorMockModel }) {
  const {
    creatorMode,
    setCreatorMode,
    jobName,
    setJobName,
    site,
    setSite,
    selectedAuthId,
    setSelectedAuthId,
    activeAuths,
    taskTypes,
    selectedTaskType,
    selectedTaskDef,
    taskParams,
    setTaskParams,
    handleTaskTypeChange,
    tasks,
    addTask,
    removeTask,
    clearTasks,
    saveAsTemplate,
    setSaveAsTemplate,
    templateName,
    setTemplateName,
    templateDescription,
    setTemplateDescription,
    templates,
    selectedTemplateId,
    selectedTemplate,
    selectTemplate,
    templateParams,
    setTemplateParams,
    templateUsernames,
    addTemplateUsername,
    removeTemplateUsername,
    authoringTemplateName,
    setAuthoringTemplateName,
    authoringTemplateDesc,
    setAuthoringTemplateDesc,
    createNewTemplate,
    previewTaskCount,
    authsPerUsername,
    scheduleEnabled,
    setScheduleEnabled,
    scheduleType,
    setScheduleType,
    scheduleAt,
    setScheduleAt,
    intervalValue,
    setIntervalValue,
    intervalUnit,
    setIntervalUnit,
    cronExpression,
    setCronExpression,
    ignoreSpaceRequirements,
    setIgnoreSpaceRequirements,
    usernameSearch,
    setUsernameSearch,
    showSuggestions,
    setShowSuggestions,
  } = model;

  const filteredSubscriptions = MOCK_SUBSCRIPTIONS.filter(
    (sub) =>
      usernameSearch &&
      sub.username.toLowerCase().includes(usernameSearch.toLowerCase()) &&
      !templateUsernames.includes(sub.username)
  );

  const handleDispatchJob = () => {
    if (creatorMode === 'tasks' && saveAsTemplate) {
      createNewTemplate(templateName || jobName, templateDescription, tasks);
      model.showNotification(`Created Job & Saved New Template "${templateName || jobName}" (${tasks.length} tasks)`);
    } else if (creatorMode === 'tasks') {
      model.showNotification(`Created Job "${jobName || 'Ad-Hoc Job'}" with ${tasks.length} tasks!`);
    } else {
      model.showNotification(`Instantiated Template "${selectedTemplate.name}" with ${previewTaskCount} total tasks across ${templateUsernames.length} performers!`);
    }
  };

  const handleCreateTemplateFromLab = (e: React.FormEvent) => {
    e.preventDefault();
    createNewTemplate(authoringTemplateName, authoringTemplateDesc, tasks);
    setCreatorMode('template');
  };

  return (
    <section className="jcm-concept jcm-dual-mode" aria-label="Dual-Mode Studio">
      {/* Mode Segmented Controls */}
      <div className="jcm-mode-bar" role="tablist" aria-label="Job creator modes">
        <button
          type="button"
          role="tab"
          aria-selected={creatorMode === 'tasks'}
          className={`jcm-mode-tab ${creatorMode === 'tasks' ? 'is-active' : ''}`}
          onClick={() => setCreatorMode('tasks')}
        >
          <span className="jcm-tab-icon">🛠️</span>
          <div>
            <strong>Build from Tasks</strong>
            <small>Compose ad-hoc queues &amp; optional template save</small>
          </div>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={creatorMode === 'template'}
          className={`jcm-mode-tab ${creatorMode === 'template' ? 'is-active' : ''}`}
          onClick={() => setCreatorMode('template')}
        >
          <span className="jcm-tab-icon">📋</span>
          <div>
            <strong>Use Template ({templates.length})</strong>
            <small>Instantiate from saved library</small>
          </div>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={creatorMode === 'create_template'}
          className={`jcm-mode-tab ${creatorMode === 'create_template' ? 'is-active' : ''}`}
          onClick={() => setCreatorMode('create_template')}
        >
          <span className="jcm-tab-icon">✨</span>
          <div>
            <strong>Create Template Studio</strong>
            <small>Author new reusable template</small>
          </div>
        </button>
      </div>

      {/* Main Grid: Form Canvas & Live Sidebar */}
      <div className="jcm-studio-grid">
        {/* Left Column: Editor Canvas */}
        <div className="jcm-studio-main">
          {/* Mode 1: Build from Tasks */}
          {creatorMode === 'tasks' && (
            <>
              {/* Job Details Section */}
              <article className="jcm-panel">
                <header className="jcm-panel-head">
                  <div>
                    <span className="jcm-eyebrow">JOB SPECIFICATION</span>
                    <h3>Job Details &amp; Template Export</h3>
                  </div>
                  <span className="jcm-badge">{tasks.length} tasks in queue</span>
                </header>

                <div className="jcm-form-grid">
                  <div className="jcm-field">
                    <label>Job Name <span className="jcm-required">*</span></label>
                    <input
                      type="text"
                      value={jobName}
                      onChange={(e) => setJobName(e.target.value)}
                      placeholder="e.g. VIP Performer Sync"
                    />
                    <small>Unique name to identify this job in queue and telemetry</small>
                  </div>

                  <div className="jcm-field">
                    <label>Target Platform</label>
                    <select value={site} onChange={(e) => setSite(e.target.value as SupportedSite)}>
                      <option value="OnlyFans">OnlyFans</option>
                      <option value="Fansly">Fansly</option>
                      <option value="LoyalFans">LoyalFans</option>
                    </select>
                  </div>

                  {/* Save as Template Toggle */}
                  <div className="jcm-field jcm-field--wide">
                    <label className="jcm-checkbox-row">
                      <input
                        type="checkbox"
                        checked={saveAsTemplate}
                        onChange={(e) => {
                          setSaveAsTemplate(e.target.checked);
                          if (e.target.checked && !templateName.trim()) {
                            setTemplateName(jobName);
                          }
                        }}
                      />
                      <div>
                        <strong>Save this configuration as a reusable Template</strong>
                        <small>Registers the current task structure in the template library for future reuse</small>
                      </div>
                    </label>
                  </div>

                  {saveAsTemplate && (
                    <>
                      <div className="jcm-field">
                        <label>Template Name <span className="jcm-required">*</span></label>
                        <input
                          type="text"
                          value={templateName}
                          onChange={(e) => setTemplateName(e.target.value)}
                          placeholder="e.g. Standard VIP Mirror"
                        />
                      </div>
                      <div className="jcm-field">
                        <label>Template Description</label>
                        <input
                          type="text"
                          value={templateDescription}
                          onChange={(e) => setTemplateDescription(e.target.value)}
                          placeholder="Optional summary of this template workflow"
                        />
                      </div>
                    </>
                  )}
                </div>
              </article>

              {/* Task Builder Section */}
              <article className="jcm-panel">
                <header className="jcm-panel-head">
                  <div>
                    <span className="jcm-eyebrow">TASK BUILDER</span>
                    <h3>Configure &amp; Enqueue Task</h3>
                  </div>
                  <span className="jcm-badge">{selectedTaskDef.category.toUpperCase()}</span>
                </header>

                <div className="jcm-form-grid">
                  <div className="jcm-field jcm-field--wide">
                    <label>Task Type</label>
                    <select value={selectedTaskType} onChange={(e) => handleTaskTypeChange(e.target.value)}>
                      {taskTypes.map((t) => (
                        <option key={t.task_id} value={t.task_id}>
                          {t.name} — {t.description}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="jcm-field">
                    <label>Auth Account</label>
                    <select
                      value={String(selectedAuthId)}
                      onChange={(e) =>
                        setSelectedAuthId(e.target.value === 'all' ? 'all' : Number(e.target.value))
                      }
                    >
                      <option value="all">All active auths ({activeAuths.length})</option>
                      {activeAuths.map((auth) => (
                        <option key={auth.id} value={auth.id}>
                          {auth.username} (ID {auth.user_id})
                        </option>
                      ))}
                    </select>
                    <small>
                      {selectedAuthId === 'all'
                        ? `Adding task will duplicate across all ${activeAuths.length} active sessions.`
                        : 'Task assigned to specific session.'}
                    </small>
                  </div>

                  {/* Dynamic Parameters */}
                  {selectedTaskDef.parameters.map((param) => {
                    if (param.name === 'site') return null; // Controlled globally
                    const val = taskParams[param.name] ?? param.default;

                    if (param.param_type === 'username') {
                      return (
                        <div key={param.name} className="jcm-field">
                          <label>{param.label} <span className="jcm-required">*</span></label>
                          <input
                            type="text"
                            value={String(val || '')}
                            onChange={(e) =>
                              setTaskParams((prev) => ({ ...prev, [param.name]: e.target.value }))
                            }
                            placeholder="e.g. luna_archive"
                          />
                          <small>{param.description}</small>
                        </div>
                      );
                    }

                    if (param.param_type === 'multiselect') {
                      const selectedList = Array.isArray(val) ? val : [];
                      return (
                        <div key={param.name} className="jcm-field jcm-field--wide">
                          <label>{param.label}</label>
                          <div className="jcm-multiselect-pills">
                            {param.options.map((opt) => {
                              const active = selectedList.includes(opt.value);
                              return (
                                <button
                                  type="button"
                                  key={opt.value}
                                  className={`jcm-pill-btn ${active ? 'is-active' : ''}`}
                                  onClick={() => {
                                    const next = active
                                      ? selectedList.filter((x) => x !== opt.value)
                                      : [...selectedList, opt.value];
                                    setTaskParams((prev) => ({ ...prev, [param.name]: next }));
                                  }}
                                >
                                  {active ? '✓ ' : '+ '}
                                  {opt.label}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    }

                    if (param.param_type === 'boolean') {
                      return (
                        <div key={param.name} className="jcm-field jcm-field--wide">
                          <label className="jcm-checkbox-row">
                            <input
                              type="checkbox"
                              checked={Boolean(val)}
                              onChange={(e) =>
                                setTaskParams((prev) => ({ ...prev, [param.name]: e.target.checked }))
                              }
                            />
                            <div>
                              <strong>{param.label}</strong>
                              <small>{param.description}</small>
                            </div>
                          </label>
                        </div>
                      );
                    }

                    return null;
                  })}

                  <div className="jcm-field jcm-field--wide">
                    <button type="button" className="jcm-btn jcm-btn--primary" onClick={addTask}>
                      ➕ Add Task to Queue
                    </button>
                  </div>
                </div>
              </article>
            </>
          )}

          {/* Mode 2: Use Template */}
          {creatorMode === 'template' && (
            <article className="jcm-panel">
              <header className="jcm-pane-head">
                <div>
                  <span className="jcm-eyebrow">TEMPLATE INSTANTIATION</span>
                  <h3>Select &amp; Parameterize Template</h3>
                </div>
                <div className="jcm-header-actions">
                  <button
                    type="button"
                    className="jcm-mini-btn is-accent"
                    onClick={() => setCreatorMode('create_template')}
                  >
                    + Create New Template
                  </button>
                </div>
              </header>

              <div className="jcm-form-grid">
                <div className="jcm-field jcm-field--wide">
                  <label>Template Choice</label>
                  <select value={selectedTemplateId} onChange={(e) => selectTemplate(e.target.value)}>
                    {templates.map((t) => (
                      <option key={t.template_id} value={t.template_id}>
                        {t.name} (by {t.created_by})
                      </option>
                    ))}
                  </select>
                  <p className="jcm-template-desc-callout">{selectedTemplate.description}</p>
                </div>

                <div className="jcm-field">
                  <label>Auth Account</label>
                  <select
                    value={String(selectedAuthId)}
                    onChange={(e) =>
                      setSelectedAuthId(e.target.value === 'all' ? 'all' : Number(e.target.value))
                    }
                  >
                    <option value="all">All active auths ({activeAuths.length})</option>
                    {activeAuths.map((auth) => (
                      <option key={auth.id} value={auth.id}>
                        {auth.username} (ID {auth.user_id})
                      </option>
                    ))}
                  </select>
                </div>

                {/* Performer Search & Autocomplete */}
                <div className="jcm-field jcm-field--wide">
                  <label>Target Performers ({templateUsernames.length})</label>
                  <div className="jcm-autocomplete-box">
                    <input
                      type="text"
                      value={usernameSearch}
                      onChange={(e) => {
                        setUsernameSearch(e.target.value);
                        setShowSuggestions(true);
                      }}
                      onFocus={() => setShowSuggestions(true)}
                      placeholder="Search subscriptions or type handle..."
                    />
                    {showSuggestions && filteredSubscriptions.length > 0 && (
                      <div className="jcm-suggestions-dropdown">
                        {filteredSubscriptions.map((sub) => (
                          <button
                            type="button"
                            key={sub.user_id}
                            className="jcm-suggestion-item"
                            onClick={() => addTemplateUsername(sub.username)}
                          >
                            <strong>@{sub.username}</strong>
                            <span>{sub.name}</span>
                            <small>{sub.site}</small>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="jcm-chip-list">
                    {templateUsernames.map((u) => (
                      <span key={u} className="jcm-chip">
                        @{u}
                        <button type="button" onClick={() => removeTemplateUsername(u)}>×</button>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Template Parameter Overrides */}
                {selectedTemplate.parameters.map((param) => {
                  if (param.name === 'username') return null;
                  const val = templateParams[param.name] ?? param.default;
                  if (param.type === 'multiselect' && param.choices) {
                    const sel = Array.isArray(val) ? val : [];
                    return (
                      <div key={param.name} className="jcm-field jcm-field--wide">
                        <label>{param.name.replace(/_/g, ' ').toUpperCase()}</label>
                        <div className="jcm-multiselect-pills">
                          {param.choices.map((choice) => {
                            const str = String(choice);
                            const active = sel.includes(str);
                            return (
                              <button
                                type="button"
                                key={str}
                                className={`jcm-pill-btn ${active ? 'is-active' : ''}`}
                                onClick={() => {
                                  const next = active ? sel.filter((x) => x !== str) : [...sel, str];
                                  setTemplateParams((prev) => ({ ...prev, [param.name]: next }));
                                }}
                              >
                                {active ? '✓ ' : '+ '}
                                {str}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  }
                  return null;
                })}
              </div>
            </article>
          )}

          {/* Mode 3: Dedicated Create Template Studio */}
          {creatorMode === 'create_template' && (
            <article className="jcm-panel">
              <header className="jcm-pane-head">
                <div>
                  <span className="jcm-eyebrow">TEMPLATE AUTHORING LAB</span>
                  <h3>Create &amp; Register New Template</h3>
                  <p>Design a reusable template definition complete with task sequence and parameterized placeholders.</p>
                </div>
                <button
                  type="button"
                  className="jcm-mini-btn"
                  onClick={() => setCreatorMode('template')}
                >
                  Cancel &amp; Back to Templates
                </button>
              </header>

              <form onSubmit={handleCreateTemplateFromLab} className="jcm-form-grid">
                <div className="jcm-field">
                  <label>Template Name <span className="jcm-required">*</span></label>
                  <input
                    type="text"
                    value={authoringTemplateName}
                    onChange={(e) => setAuthoringTemplateName(e.target.value)}
                    placeholder="e.g. VIP Full Vault Archival"
                    required
                  />
                </div>

                <div className="jcm-field">
                  <label>Template Description</label>
                  <input
                    type="text"
                    value={authoringTemplateDesc}
                    onChange={(e) => setAuthoringTemplateDesc(e.target.value)}
                    placeholder="e.g. Comprehensive scraper for premium creators"
                  />
                </div>

                <div className="jcm-field jcm-field--wide">
                  <label>Template Tasks Included ({tasks.length})</label>
                  <div className="jcm-template-task-spec">
                    {tasks.map((t, idx) => (
                      <div key={idx} className="jcm-spec-row">
                        <span>0{idx + 1}</span>
                        <strong>{t.task_type}</strong>
                        <code>{JSON.stringify(t.params)}</code>
                      </div>
                    ))}
                    {tasks.length === 0 && (
                      <p className="jcm-empty-hint">
                        Queue is empty. You can build tasks in "Build from Tasks" mode first or register the default 2-stage workflow.
                      </p>
                    )}
                  </div>
                </div>

                <div className="jcm-field jcm-field--wide">
                  <button type="submit" className="jcm-btn jcm-btn--launch">
                    💾 Save to Template Library &amp; Use Immediately
                  </button>
                </div>
              </form>
            </article>
          )}

          {/* Shared Scheduling & Space Options Drawer */}
          <article className="jcm-panel">
            <header className="jcm-panel-head">
              <div>
                <span className="jcm-eyebrow">SCHEDULING &amp; POLICIES</span>
                <h3>Execution Timing &amp; Space Constraints</h3>
              </div>
              <span className={`jcm-pill ${scheduleEnabled ? 'is-queued' : 'is-running'}`}>
                {scheduleEnabled ? 'SCHEDULE ACTIVE' : 'RUN ON DEMAND'}
              </span>
            </header>

            <div className="jcm-form-grid">
              <div className="jcm-field jcm-field--wide">
                <label className="jcm-checkbox-row">
                  <input
                    type="checkbox"
                    checked={scheduleEnabled}
                    onChange={(e) => setScheduleEnabled(e.target.checked)}
                  />
                  <div>
                    <strong>Enable Scheduled or Recurring Execution</strong>
                    <small>Run this job automatically on a periodic interval, specific future timestamp, or cron pattern</small>
                  </div>
                </label>
              </div>

              {scheduleEnabled && (
                <>
                  <div className="jcm-field">
                    <label>Schedule Type</label>
                    <select
                      value={scheduleType}
                      onChange={(e) => setScheduleType(e.target.value as ScheduleType)}
                    >
                      <option value="interval">Run Every (Interval)...</option>
                      <option value="once">Run Once At...</option>
                      <option value="cron">Cron Expression...</option>
                    </select>
                  </div>

                  {scheduleType === 'interval' && (
                    <div className="jcm-field">
                      <label>Repeat Frequency</label>
                      <div className="jcm-schedule-unit-row">
                        <input
                          type="number"
                          min="1"
                          value={intervalValue}
                          onChange={(e) => setIntervalValue(Number(e.target.value))}
                        />
                        <select
                          value={intervalUnit}
                          onChange={(e) => setIntervalUnit(e.target.value as IntervalUnit)}
                        >
                          <option value="minutes">Minutes</option>
                          <option value="hours">Hours</option>
                          <option value="days">Days</option>
                        </select>
                      </div>
                    </div>
                  )}

                  {scheduleType === 'once' && (
                    <div className="jcm-field">
                      <label>Target Execution Time</label>
                      <input
                        type="datetime-local"
                        value={scheduleAt}
                        onChange={(e) => setScheduleAt(e.target.value)}
                      />
                    </div>
                  )}

                  {scheduleType === 'cron' && (
                    <div className="jcm-field">
                      <label>Cron Syntax</label>
                      <input
                        type="text"
                        value={cronExpression}
                        onChange={(e) => setCronExpression(e.target.value)}
                      />
                    </div>
                  )}
                </>
              )}

              <div className="jcm-field jcm-field--wide">
                <label className="jcm-checkbox-row">
                  <input
                    type="checkbox"
                    checked={ignoreSpaceRequirements}
                    onChange={(e) => setIgnoreSpaceRequirements(e.target.checked)}
                  />
                  <div>
                    <strong>Ignore storage space checks</strong>
                    <small>Bypass disk free-space watermark guards (use with caution on small mounts)</small>
                  </div>
                </label>
              </div>
            </div>
          </article>
        </div>

        {/* Right Column: Live Context Sidebar */}
        <aside className="jcm-studio-sidebar">
          {creatorMode === 'tasks' ? (
            /* Task Queue Sidebar */
            <article className="jcm-panel jcm-sidebar-panel">
              <header className="jcm-panel-head">
                <div>
                  <span className="jcm-eyebrow">TASK QUEUE</span>
                  <h3>Queued Task Payloads ({tasks.length})</h3>
                </div>
                {tasks.length > 0 && (
                  <button type="button" className="jcm-mini-btn" onClick={clearTasks}>
                    Clear
                  </button>
                )}
              </header>

              <div className="jcm-queue-list">
                {tasks.map((task, idx) => (
                  <div key={idx} className="jcm-queue-card">
                    <div className="jcm-queue-card-top">
                      <span className="jcm-task-ordinal">0{idx + 1}</span>
                      <strong>{task.task_type}</strong>
                      <button
                        type="button"
                        aria-label={`Remove task ${idx + 1}`}
                        onClick={() => removeTask(idx)}
                      >
                        ×
                      </button>
                    </div>
                    <div className="jcm-queue-params">
                      {task.params.username != null && <span>@{String(task.params.username)}</span>}
                      {task.params.auth_id != null && <span>Auth #{String(task.params.auth_id)}</span>}
                      {Array.isArray(task.params.content_types) && (
                        <small>{(task.params.content_types as string[]).join(', ')}</small>
                      )}
                      {Array.isArray(task.params.media_types) && (
                        <small>{(task.params.media_types as string[]).join(', ')}</small>
                      )}
                    </div>
                  </div>
                ))}
                {tasks.length === 0 && (
                  <p className="jcm-empty-hint">Queue is empty. Select a task type and click "Add Task to Queue".</p>
                )}
              </div>
            </article>
          ) : (
            /* Template Preview Sidebar */
            <article className="jcm-panel jcm-sidebar-panel">
              <header className="jcm-panel-head">
                <div>
                  <span className="jcm-eyebrow">TEMPLATE SYNTHESIS</span>
                  <h3>{selectedTemplate.name}</h3>
                </div>
                <span className="jcm-badge">~{previewTaskCount} tasks</span>
              </header>

              <div className="jcm-template-preview-body">
                <div className="jcm-summary-stat">
                  <span>TARGET PERFORMERS</span>
                  <strong>{templateUsernames.length}</strong>
                </div>
                <div className="jcm-summary-stat">
                  <span>TASKS PER PERFORMER</span>
                  <strong>{selectedTemplate.tasks.length}</strong>
                </div>
                <div className="jcm-summary-stat">
                  <span>TOTAL INSTANTIATED</span>
                  <strong className="is-cyan">{previewTaskCount}</strong>
                </div>

                <div className="jcm-auth-breakdown">
                  <span className="jcm-eyebrow">QUALIFYING SESSIONS:</span>
                  {templateUsernames.map((u) => (
                    <div key={u} className="jcm-auth-user-row">
                      <span>@{u}</span>
                      <code>{authsPerUsername[u]?.length ?? 1} active auth(s)</code>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          )}

          {/* Action Dispatch Button */}
          <div className="jcm-panel jcm-dispatch-panel">
            <button
              type="button"
              className="jcm-btn jcm-btn--launch jcm-btn--full"
              disabled={creatorMode === 'tasks' ? tasks.length === 0 : templateUsernames.length === 0}
              onClick={handleDispatchJob}
            >
              🚀 {creatorMode === 'tasks'
                ? saveAsTemplate
                  ? `Create Job & Save Template (${tasks.length} Tasks)`
                  : `Dispatch Job (${tasks.length} Tasks)`
                : `Instantiate Template (${previewTaskCount} Tasks)`}
            </button>
          </div>
        </aside>
      </div>
    </section>
  );
}
