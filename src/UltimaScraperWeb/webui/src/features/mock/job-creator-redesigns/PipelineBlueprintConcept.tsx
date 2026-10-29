import { useState } from 'react';
import type { JobCreatorMockModel, IntervalUnit } from './jobCreatorMockModel';

export function PipelineBlueprintConcept({ model }: { model: JobCreatorMockModel }) {
  const {
    jobName,
    site,
    activeAuths,
    tasks,
    addTask,
    removeTask,
    clearTasks,
    saveAsTemplate,
    templateName,
    templateDescription,
    templates,
    createNewTemplate,
    selectTemplate,
    scheduleEnabled,
    setScheduleEnabled,
    intervalValue,
    setIntervalValue,
    intervalUnit,
    setIntervalUnit,
    ignoreSpaceRequirements,
    setIgnoreSpaceRequirements,
  } = model;

  const [selectedNodeIndex, setSelectedNodeIndex] = useState<number>(0);
  const [showTemplateModal, setShowTemplateModal] = useState<boolean>(false);
  const [exportTemplateName, setExportTemplateName] = useState<string>('Custom Visual Blueprint');
  const [exportTemplateDesc, setExportTemplateDesc] = useState<string>('Exported pipeline template');

  const activeTask = tasks[selectedNodeIndex] ?? tasks[0];
  const updateActiveParams = (patch: Record<string, unknown>) =>
    model.setTasks(tasks.map((task) => (task === activeTask ? { ...task, params: { ...task.params, ...patch } } : task)));

  const handleExportTemplate = (e: React.FormEvent) => {
    e.preventDefault();
    createNewTemplate(exportTemplateName, exportTemplateDesc, tasks);
    setShowTemplateModal(false);
  };

  const handleImportTemplate = (templateId: string) => {
    selectTemplate(templateId);
    const tmpl = templates.find((t) => t.template_id === templateId);
    if (!tmpl) return;
    clearTasks();
    tmpl.tasks.forEach(() => addTask());
    model.showNotification(`Loaded ${tmpl.tasks.length} tasks from template "${tmpl.name}" into visual pipeline`);
  };

  const handleDeploy = () => {
    if (saveAsTemplate) {
      createNewTemplate(templateName || jobName, templateDescription, tasks);
      model.showNotification(`Pipeline deployed to queue and saved as template "${templateName || jobName}"!`);
    } else {
      model.showNotification(`Pipeline deployed to queue with ${tasks.length} active stages!`);
    }
  };

  return (
    <section className="jcm-concept jcm-pipeline-blueprint" aria-label="Pipeline Blueprint Architect">
      {/* Blueprint Header */}
      <div className="jcm-blueprint-bar">
        <div>
          <span className="jcm-eyebrow">VISUAL PIPELINE BLUEPRINT // WORKFLOW BUILDER</span>
          <h3>Interactive Node Canvas</h3>
        </div>
        <div className="jcm-blueprint-actions">
          <select
            className="jcm-template-select-inline"
            onChange={(e) => handleImportTemplate(e.target.value)}
            defaultValue=""
          >
            <option value="" disabled>Load from Template...</option>
            {templates.map((t) => (
              <option key={t.template_id} value={t.template_id}>
                {t.name}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="jcm-btn jcm-btn--primary"
            onClick={() => setShowTemplateModal(true)}
          >
            💾 Save Pipeline as Template
          </button>

          <button
            type="button"
            className="jcm-btn jcm-btn--launch"
            disabled={tasks.length === 0}
            onClick={handleDeploy}
          >
            🚀 Deploy Pipeline ({tasks.length} Stages)
          </button>
        </div>
      </div>

      {/* Save Template Modal / Drawer */}
      {showTemplateModal && (
        <div className="jcm-modal-backdrop" onClick={() => setShowTemplateModal(false)}>
          <div className="jcm-modal-window" onClick={(e) => e.stopPropagation()}>
            <header className="jcm-pane-head">
              <div>
                <span className="jcm-eyebrow">TEMPLATE SYNTHESIS</span>
                <h3>Save Current Pipeline as Reusable Template</h3>
              </div>
              <button type="button" className="jcm-close-btn" onClick={() => setShowTemplateModal(false)}>×</button>
            </header>
            <form onSubmit={handleExportTemplate} className="jcm-form-grid">
              <div className="jcm-field jcm-field--wide">
                <label>Template Name <span className="jcm-required">*</span></label>
                <input
                  type="text"
                  value={exportTemplateName}
                  onChange={(e) => setExportTemplateName(e.target.value)}
                  placeholder="e.g. VIP Multi-Stage Ingestion Blueprint"
                  required
                />
              </div>
              <div className="jcm-field jcm-field--wide">
                <label>Description</label>
                <textarea
                  rows={2}
                  value={exportTemplateDesc}
                  onChange={(e) => setExportTemplateDesc(e.target.value)}
                  placeholder="Describe when to use this template workflow..."
                />
              </div>
              <div className="jcm-field jcm-field--wide">
                <small className="jcm-mono-text">
                  Bundling {tasks.length} active pipeline stages: {tasks.map((t) => t.task_type).join(' ➔ ')}
                </small>
              </div>
              <div className="jcm-modal-footer">
                <button type="button" className="jcm-btn" onClick={() => setShowTemplateModal(false)}>Cancel</button>
                <button type="submit" className="jcm-btn jcm-btn--launch">Confirm &amp; Save Template</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Visual DAG Nodes Chain */}
      <div className="jcm-dag-chain" role="list" aria-label="Pipeline task stages">
        {tasks.map((task, index) => {
          const isSelected = selectedNodeIndex === index;
          return (
            <div key={index} className="jcm-dag-step" role="listitem">
              <div
                role="button"
                tabIndex={0}
                className={`jcm-dag-node ${isSelected ? 'is-selected' : ''}`}
                aria-pressed={isSelected}
                onClick={() => setSelectedNodeIndex(index)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    setSelectedNodeIndex(index);
                  }
                }}
              >
                <div className="jcm-dag-top">
                  <span>STAGE 0{index + 1}</span>
                  <button
                    type="button"
                    className="jcm-node-del"
                    aria-label={`Remove stage ${index + 1}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      removeTask(index);
                      if (selectedNodeIndex >= tasks.length - 1) {
                        setSelectedNodeIndex(Math.max(0, tasks.length - 2));
                      }
                    }}
                  >
                    ×
                  </button>
                </div>
                <strong>{task.task_type}</strong>
                <p>
                  {task.params.username ? `@${String(task.params.username)}` : 'Target: all'} · Auth: #{String(task.params.auth_id || 'active')}
                </p>
                <div className="jcm-dag-foot">
                  <span>{Array.isArray(task.params.content_types) ? (task.params.content_types as string[]).join(', ') : 'Default'}</span>
                </div>
              </div>
              {index < tasks.length - 1 && (
                <div className="jcm-dag-connector" aria-hidden="true">
                  <span className="jcm-connector-line" />
                  <span className="jcm-connector-arrow">➔</span>
                </div>
              )}
            </div>
          );
        })}

        {/* Append Node Button */}
        <div className="jcm-add-node-box">
          <button
            type="button"
            className="jcm-add-node-btn"
            onClick={addTask}
          >
            + Add Stage
          </button>
        </div>
      </div>

      {/* Node Inspector Drawer */}
      {activeTask && (
        <div className="jcm-card jcm-blueprint-drawer">
          <header className="jcm-pane-head">
            <div>
              <span className="jcm-eyebrow">STAGE CONFIGURATION // 0{selectedNodeIndex + 1}</span>
              <h3>{activeTask.task_type}</h3>
            </div>
            <span className="jcm-badge">Auth: {activeTask.params.auth_id ? `ID #${activeTask.params.auth_id}` : 'All active'}</span>
          </header>

          <div className="jcm-form-grid">
            <div className="jcm-field">
              <label>Target Performer Handle</label>
              <input
                type="text"
                value={String(activeTask.params.username || '')}
                onChange={(e) => updateActiveParams({ username: e.target.value })}
                placeholder="e.g. luna_archive"
              />
            </div>

            <div className="jcm-field">
              <label>Target Site</label>
              <select
                value={String(activeTask.params.site || site)}
                onChange={(e) => updateActiveParams({ site: e.target.value })}
              >
                <option value="OnlyFans">OnlyFans</option>
                <option value="Fansly">Fansly</option>
                <option value="LoyalFans">LoyalFans</option>
              </select>
            </div>

            <div className="jcm-field jcm-field--wide">
              <label>Active Auth Session</label>
              <select
                value={String(activeTask.params.auth_id || '')}
                onChange={(e) => updateActiveParams({ auth_id: Number(e.target.value) })}
              >
                {activeAuths.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.username} (ID {a.user_id})
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}

      {/* Global Bottom Policy Bar */}
      <div className="jcm-card jcm-blueprint-footer-policy">
        <div className="jcm-checkbox-cluster">
          <label className="jcm-checkbox-row">
            <input
              type="checkbox"
              checked={scheduleEnabled}
              onChange={(e) => setScheduleEnabled(e.target.checked)}
            />
            <span>Enable Periodic Schedule</span>
          </label>

          <label className="jcm-checkbox-row">
            <input
              type="checkbox"
              checked={ignoreSpaceRequirements}
              onChange={(e) => setIgnoreSpaceRequirements(e.target.checked)}
            />
            <span>Ignore storage space checks</span>
          </label>
        </div>

        {scheduleEnabled && (
          <div className="jcm-inline-schedule">
            <span>Interval:</span>
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
              <option value="hours">Hours</option>
              <option value="days">Days</option>
            </select>
          </div>
        )}
      </div>
    </section>
  );
}
