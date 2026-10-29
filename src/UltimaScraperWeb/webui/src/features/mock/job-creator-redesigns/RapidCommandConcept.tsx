import { useState, useMemo } from 'react';
import type { JobCreatorMockModel, IntervalUnit, ScheduleType } from './jobCreatorMockModel';

export function RapidCommandConcept({ model }: { model: JobCreatorMockModel }) {
  const {
    jobName,
    setJobName,
    site,
    setSite,
    selectedAuthId,
    setSelectedAuthId,
    activeAuths,
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
    createNewTemplate,
    selectTemplate,
    scheduleEnabled,
    setScheduleEnabled,
    scheduleType,
    setScheduleType,
    intervalValue,
    setIntervalValue,
    intervalUnit,
    setIntervalUnit,
    cronExpression,
    setCronExpression,
    ignoreSpaceRequirements,
    setIgnoreSpaceRequirements,
    showNotification,
  } = model;

  const [showJsonDebugger, setShowJsonDebugger] = useState(true);
  const [handleInput, setHandleInput] = useState('luna_archive\nsarah_sky\nnova_star');
  const [isTemplateModalOpen, setIsTemplateModalOpen] = useState(false);
  const [newTmplName, setNewTmplName] = useState('Rapid Pipeline Template');
  const [newTmplDesc, setNewTmplDesc] = useState('High velocity scraper task sequence');

  const parsedHandles = useMemo(() => {
    return handleInput
      .split(/[\n,;\s]+/)
      .map((s) => s.replace(/^@/, '').trim())
      .filter(Boolean);
  }, [handleInput]);

  // Construct real API representation
  const generatedPayload = useMemo(() => {
    return {
      name: jobName || 'Untitled Job',
      tasks: tasks.map((t) => ({
        task_type: t.task_type,
        params: t.params,
      })),
      schedule: scheduleEnabled
        ? scheduleType === 'interval'
          ? { interval_seconds: intervalValue * (intervalUnit === 'days' ? 86400 : intervalUnit === 'hours' ? 3600 : 60), start_immediately: true }
          : scheduleType === 'cron'
            ? { cron: cronExpression }
            : { scheduled_for: new Date().toISOString() }
        : null,
      save_as_template: saveAsTemplate,
      template_name: saveAsTemplate ? templateName : undefined,
      template_description: saveAsTemplate ? templateDescription : undefined,
      ignore_space_requirements: ignoreSpaceRequirements,
    };
  }, [
    jobName,
    tasks,
    scheduleEnabled,
    scheduleType,
    intervalValue,
    intervalUnit,
    cronExpression,
    saveAsTemplate,
    templateName,
    templateDescription,
    ignoreSpaceRequirements,
  ]);

  const handleQuickAddTask = (taskTypeId: string) => {
    handleTaskTypeChange(taskTypeId);
    // add task after brief tick
    setTimeout(() => {
      addTask();
    }, 10);
  };

  const handleAddAllHandlesAsTasks = () => {
    if (parsedHandles.length === 0) return;
    for (const h of parsedHandles) {
      setTaskParams((prev) => ({ ...prev, username: h }));
      setTimeout(() => {
        addTask();
      }, 20);
    }
    showNotification(`Generated tasks for ${parsedHandles.length} parsed creator handles!`);
  };

  const handleSaveAsTemplateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTmplName.trim()) return;
    createNewTemplate(newTmplName, newTmplDesc, tasks);
    setIsTemplateModalOpen(false);
  };

  const handleDispatchJob = () => {
    if (tasks.length === 0) {
      showNotification('Cannot dispatch: Task queue is empty. Add at least one task.', 'error');
      return;
    }
    showNotification(
      `Dispatched command job "${jobName || 'Rapid Job'}" with ${tasks.length} tasks!${
        saveAsTemplate ? ` Also saved as template "${templateName}".` : ''
      }`
    );
  };

  return (
    <section className="jcm-concept jcm-rapid-command" aria-label="Rapid Command Terminal">
      {/* Top Velocity Banner */}
      <div className="jcm-command-banner">
        <div>
          <span className="jcm-eyebrow">HOTKEY-DRIVEN WORKBENCH // HIGH-VELOCITY DISPATCH</span>
          <h3>Rapid Task Console &amp; Template Generator</h3>
        </div>
        <div className="jcm-command-shortcuts">
          <button
            type="button"
            className="jcm-btn jcm-btn--template"
            onClick={() => setIsTemplateModalOpen(true)}
            title="Save current tasks as reusable template"
          >
            💾 Save Queue as Template
          </button>
          <button
            type="button"
            className="jcm-btn jcm-btn--launch"
            onClick={handleDispatchJob}
            disabled={tasks.length === 0}
          >
            ⚡ Quick Dispatch ({tasks.length} Tasks)
          </button>
        </div>
      </div>

      {/* Main Grid: Inputs vs Real-time Payload Spec */}
      <div className="jcm-terminal-layout">
        {/* Left Column: Command Center */}
        <div className="jcm-terminal-inputs jcm-card">
          {/* Row 1: Job Identity & Template Loader */}
          <div className="jcm-form-grid" style={{ marginBottom: '1rem' }}>
            <div className="jcm-field">
              <label>Job Name</label>
              <input
                type="text"
                value={jobName}
                onChange={(e) => setJobName(e.target.value)}
                placeholder="e.g. Creator Fast Pipeline"
              />
            </div>
            <div className="jcm-field">
              <label>Import from Existing Template</label>
              <select
                onChange={(e) => {
                  if (e.target.value) {
                    selectTemplate(e.target.value);
                    const t = templates.find((item) => item.template_id === e.target.value);
                    if (t) {
                      setJobName(t.name);
                      showNotification(`Imported template: ${t.name}`);
                    }
                  }
                }}
                defaultValue=""
              >
                <option value="" disabled>
                  -- Select Template to Pre-populate --
                </option>
                {templates.map((tmpl) => (
                  <option key={tmpl.template_id} value={tmpl.template_id}>
                    {tmpl.name} ({tmpl.tasks.length} tasks)
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Row 2: Target Site & Active Auth Selection */}
          <div className="jcm-quick-toggles" style={{ marginBottom: '1.25rem' }}>
            <div>
              <span className="jcm-eyebrow">TARGET PLATFORM</span>
              <div className="jcm-pill-group">
                {(['OnlyFans', 'Fansly', 'LoyalFans'] as const).map((s) => (
                  <button
                    type="button"
                    key={s}
                    className={`jcm-pill-btn ${site === s ? 'is-active' : ''}`}
                    onClick={() => setSite(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className="jcm-eyebrow">AUTH QUALIFICATION</span>
              <select
                value={String(selectedAuthId)}
                onChange={(e) =>
                  setSelectedAuthId(e.target.value === 'all' ? 'all' : Number(e.target.value))
                }
              >
                <option value="all">⚡ All Active Sessions ({activeAuths.length} available)</option>
                {activeAuths.map((auth) => (
                  <option key={auth.id} value={auth.id}>
                    {auth.username} (id: {auth.id})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Quick Task Injection Toolbar */}
          <div className="jcm-task-inject-box">
            <div className="jcm-label-row">
              <label><strong>Quick Add Tasks to Queue</strong></label>
              <span className="jcm-subtle-hint">1-Click task composition</span>
            </div>
            <div className="jcm-quick-task-buttons">
              <button
                type="button"
                className="jcm-task-btn"
                onClick={() => handleQuickAddTask('scrape_user')}
              >
                + Scrape User Posts
              </button>
              <button
                type="button"
                className="jcm-task-btn"
                onClick={() => handleQuickAddTask('download_media')}
              >
                + Download Media
              </button>
              <button
                type="button"
                className="jcm-task-btn"
                onClick={() => handleQuickAddTask('scrape_paid_content')}
              >
                + Scrape Paid / PPV
              </button>
              <button
                type="button"
                className="jcm-task-btn"
                onClick={() => handleQuickAddTask('verify_checksums')}
              >
                + Verify Checksums
              </button>
            </div>
          </div>

          {/* Multi-Creator Handle Fast Ingestion */}
          <div className="jcm-field" style={{ marginTop: '1.25rem' }}>
            <div className="jcm-label-row">
              <label>Bulk Creator Handles (One per line or comma separated)</label>
              <span className="jcm-badge">{parsedHandles.length} handles detected</span>
            </div>
            <textarea
              rows={3}
              className="jcm-textarea-mono"
              value={handleInput}
              onChange={(e) => setHandleInput(e.target.value)}
              placeholder="e.g. luna_archive&#10;sarah_sky&#10;nova_star"
            />
            <div className="jcm-handle-actions">
              <button
                type="button"
                className="jcm-btn jcm-btn--small"
                onClick={handleAddAllHandlesAsTasks}
              >
                ⚡ Generate Tasks for All {parsedHandles.length} Handles
              </button>
            </div>
          </div>

          {/* Inline Save as Template Toggle */}
          <div className="jcm-template-inline-box">
            <label className="jcm-checkbox-row">
              <input
                type="checkbox"
                checked={saveAsTemplate}
                onChange={(e) => setSaveAsTemplate(e.target.checked)}
              />
              <span><strong>Save this job configuration as a reusable Template</strong></span>
            </label>

            {saveAsTemplate && (
              <div className="jcm-template-inline-fields">
                <div className="jcm-field">
                  <label>Template Name *</label>
                  <input
                    type="text"
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                    placeholder="e.g. Rapid Delta Scraper Recipe"
                  />
                </div>
                <div className="jcm-field">
                  <label>Template Description (Optional)</label>
                  <input
                    type="text"
                    value={templateDescription}
                    onChange={(e) => setTemplateDescription(e.target.value)}
                    placeholder="e.g. Standard 2-stage scrape & download"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Execution & Storage Policies */}
          <div className="jcm-policy-bar">
            <label className="jcm-checkbox-row">
              <input
                type="checkbox"
                checked={scheduleEnabled}
                onChange={(e) => setScheduleEnabled(e.target.checked)}
              />
              <span>Enable Schedule</span>
            </label>

            {scheduleEnabled && (
              <div className="jcm-schedule-mini-row">
                <select
                  value={scheduleType}
                  onChange={(e) => setScheduleType(e.target.value as ScheduleType)}
                >
                  <option value="interval">Repeat Every</option>
                  <option value="cron">Cron Schedule</option>
                </select>
                {scheduleType === 'interval' ? (
                  <>
                    <input
                      type="number"
                      min="1"
                      style={{ width: '70px' }}
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
                  </>
                ) : (
                  <input
                    type="text"
                    value={cronExpression}
                    onChange={(e) => setCronExpression(e.target.value)}
                    placeholder="0 */6 * * *"
                  />
                )}
              </div>
            )}

            <label className="jcm-checkbox-row">
              <input
                type="checkbox"
                checked={ignoreSpaceRequirements}
                onChange={(e) => setIgnoreSpaceRequirements(e.target.checked)}
              />
              <span>Ignore storage space checks</span>
            </label>
          </div>
        </div>

        {/* Right Column: Active Task Queue & Live API JSON */}
        <div className="jcm-terminal-spec jcm-card">
          <header className="jcm-pane-head">
            <div>
              <span className="jcm-eyebrow">WORKLOAD QUEUE // {tasks.length} TASKS STAGED</span>
              <h3>Active Task Queue &amp; Payloads</h3>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {tasks.length > 0 && (
                <button
                  type="button"
                  className="jcm-btn jcm-btn--small"
                  onClick={clearTasks}
                >
                  Clear Queue
                </button>
              )}
              <button
                type="button"
                className="jcm-btn jcm-btn--small"
                onClick={() => setShowJsonDebugger((v) => !v)}
              >
                {showJsonDebugger ? 'Show Queue View' : 'Show JSON View'}
              </button>
            </div>
          </header>

          {!showJsonDebugger ? (
            <div className="jcm-terminal-task-list">
              {tasks.length === 0 ? (
                <div className="jcm-empty-hint">
                  <p>Queue is empty. Click "+ Scrape User Posts" or "+ Download Media" above to inject tasks.</p>
                </div>
              ) : (
                tasks.map((t, idx) => (
                  <div key={idx} className="jcm-queue-item">
                    <span className="jcm-queue-num">0{idx + 1}</span>
                    <div className="jcm-queue-info">
                      <strong>{t.task_type}</strong>
                      <div className="jcm-queue-details">
                        <span>@{String(t.params.username || 'creator')}</span>
                        <span>• {String(t.params.site || site)}</span>
                        {t.params.auth_id != null && <span>• auth: {String(t.params.auth_id)}</span>}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="jcm-mini-del"
                      onClick={() => removeTask(idx)}
                      title="Remove task"
                    >
                      ✕
                    </button>
                  </div>
                ))
              )}
            </div>
          ) : (
            <pre className="jcm-json-viewer">
              <code>{JSON.stringify(generatedPayload, null, 2)}</code>
            </pre>
          )}

          {/* Preflight Stats */}
          <div className="jcm-terminal-preflight">
            <div>
              <span>Syntax Validity</span>
              <strong className="is-cyan">Valid API Schema</strong>
            </div>
            <div>
              <span>Total Tasks</span>
              <strong>{tasks.length}</strong>
            </div>
            <div>
              <span>Storage Policy</span>
              <strong>{ignoreSpaceRequirements ? 'Checks Bypassed' : 'Enforced'}</strong>
            </div>
            <div>
              <span>Template Target</span>
              <strong>{saveAsTemplate ? `Save: "${templateName || 'Untitled'}"` : 'Job Only'}</strong>
            </div>
          </div>
        </div>
      </div>

      {/* Save Queue as Template Modal */}
      {isTemplateModalOpen && (
        <div className="jcm-modal-overlay" role="dialog" aria-modal="true">
          <div className="jcm-modal jcm-card">
            <header className="jcm-modal-header">
              <div>
                <span className="jcm-eyebrow">REUSABLE TEMPLATE AUTHORING</span>
                <h4>Save Task Queue as Named Template</h4>
              </div>
              <button
                type="button"
                className="jcm-close-btn"
                onClick={() => setIsTemplateModalOpen(false)}
              >
                ✕
              </button>
            </header>

            <form onSubmit={handleSaveAsTemplateSubmit}>
              <div className="jcm-field">
                <label>Template Name *</label>
                <input
                  type="text"
                  required
                  value={newTmplName}
                  onChange={(e) => setNewTmplName(e.target.value)}
                  placeholder="e.g. Creator Delta Ingestion"
                />
              </div>

              <div className="jcm-field">
                <label>Template Description</label>
                <textarea
                  rows={2}
                  value={newTmplDesc}
                  onChange={(e) => setNewTmplDesc(e.target.value)}
                  placeholder="Describe when and how this template should be used..."
                />
              </div>

              <div className="jcm-modal-summary">
                <p>
                  <strong>{tasks.length} tasks</strong> will be converted into template task blueprints with parametric variables (<code>{'{username}'}</code>, <code>{'{site}'}</code>).
                </p>
              </div>

              <div className="jcm-modal-actions">
                <button
                  type="button"
                  className="jcm-btn jcm-btn--quiet"
                  onClick={() => setIsTemplateModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="jcm-btn jcm-btn--primary">
                  Save Template to Library
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
