import { useState } from 'react';
import type { JobCreatorMockModel, IntervalUnit, ScheduleType } from './jobCreatorMockModel';
import { MOCK_SUBSCRIPTIONS } from './jobCreatorMockModel';

export function RecipeRunwayConcept({ model }: { model: JobCreatorMockModel }) {
  const {
    site,
    selectedAuthId,
    setSelectedAuthId,
    activeAuths,
    templates,
    selectedTemplateId,
    selectedTemplate,
    selectTemplate,
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
    showNotification,
  } = model;

  const [activeView, setActiveView] = useState<'run' | 'create'>('run');
  const [templateSearchQuery, setTemplateSearchQuery] = useState('');

  // Authoring state
  const [newParams, setNewParams] = useState([
    { name: 'username', label: 'Creator Username', type: 'username', required: true, default: '' },
    { name: 'site', label: 'Target Platform', type: 'select', required: true, default: 'OnlyFans' },
    { name: 'content_types', label: 'Content Categories', type: 'multiselect', required: true, default: ['Posts', 'Stories'] },
  ]);
  const [newTasks, setNewTasks] = useState([
    { task_type: 'scrape_user', name: 'Scrape Creator Posts' },
    { task_type: 'download_media', name: 'Download Media Vault' },
  ]);

  const filteredTemplates = templates.filter(
    (t) =>
      t.name.toLowerCase().includes(templateSearchQuery.toLowerCase()) ||
      (t.description || '').toLowerCase().includes(templateSearchQuery.toLowerCase())
  );

  const handleLaunchTemplate = () => {
    if (templateUsernames.length === 0) {
      showNotification('Please add at least one creator handle before instantiating.', 'error');
      return;
    }
    showNotification(
      `Dispatched job from template "${selectedTemplate?.name}" across ${templateUsernames.length} performers (${previewTaskCount} total tasks)!`
    );
  };

  const handleCreateTemplate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!authoringTemplateName.trim()) {
      showNotification('Template name is required.', 'error');
      return;
    }
    createNewTemplate(
      authoringTemplateName,
      authoringTemplateDesc,
      newTasks.map((t) => ({
        task_type: t.task_type,
        params: { site, username: '{username}', content_types: ['Posts'] },
      }))
    );
    setActiveView('run');
  };

  const handleCloneAsNewTemplate = () => {
    if (!selectedTemplate) return;
    setAuthoringTemplateName(`${selectedTemplate.name} (Custom Copy)`);
    setAuthoringTemplateDesc(`Cloned from ${selectedTemplate.name}. ${selectedTemplate.description || ''}`);
    setActiveView('create');
    showNotification(`Cloned "${selectedTemplate.name}" into Template Studio for customization!`);
  };

  const handleAddParamToAuthor = () => {
    setNewParams((prev) => [
      ...prev,
      {
        name: `custom_field_${prev.length + 1}`,
        label: `Custom Field ${prev.length + 1}`,
        type: 'select',
        required: false,
        default: 'Standard',
      },
    ]);
  };

  const handleAddTaskToAuthor = (taskType: string, name: string) => {
    setNewTasks((prev) => [...prev, { task_type: taskType, name }]);
  };

  return (
    <section className="jcm-concept jcm-recipe-runway" aria-label="Recipe and Template Runway">
      <div className="jcm-recipe-layout">
        {/* Left Column: Template Deck & Search */}
        <div className="jcm-recipe-catalog">
          <header className="jcm-pane-head">
            <div>
              <span className="jcm-eyebrow">RECIPE RUNWAY // TEMPLATES</span>
              <h3>Standardized Archetypes</h3>
            </div>
            <button
              type="button"
              className="jcm-btn jcm-btn--primary"
              onClick={() => setActiveView('create')}
            >
              + Create Template
            </button>
          </header>

          <div className="jcm-search-bar" style={{ marginBottom: '1rem' }}>
            <input
              type="text"
              value={templateSearchQuery}
              onChange={(e) => setTemplateSearchQuery(e.target.value)}
              placeholder="Filter templates..."
            />
          </div>

          <div className="jcm-recipe-cards">
            {filteredTemplates.map((template) => {
              const isSelected = activeView === 'run' && template.template_id === selectedTemplateId;
              return (
                <button
                  type="button"
                  key={template.template_id}
                  className={`jcm-recipe-card ${isSelected ? 'is-selected' : ''}`}
                  aria-pressed={isSelected}
                  onClick={() => {
                    selectTemplate(template.template_id);
                    setActiveView('run');
                  }}
                >
                  <div className="jcm-recipe-card-top">
                    <span className="jcm-mini-tag">{template.tasks.length} Stages</span>
                    <small>Priority {template.default_priority}</small>
                  </div>
                  <strong>{template.name}</strong>
                  <p>{template.description || 'Configurable multi-task scraper template.'}</p>
                  <div className="jcm-recipe-meta">
                    <span>{template.parameters.length} Parameters</span>
                    <span>~{template.tasks.length * 3} Tasks/Creator</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Right Column: Template Execution or Template Authoring Studio */}
        {activeView === 'run' ? (
          <div className="jcm-recipe-detail jcm-card">
            <header className="jcm-pane-head">
              <div>
                <span className="jcm-eyebrow">RUNWAY STUDIO // INSTANTIATE RECIPE</span>
                <h3>{selectedTemplate?.name}</h3>
                <p>{selectedTemplate?.description}</p>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  type="button"
                  className="jcm-btn jcm-btn--template"
                  onClick={handleCloneAsNewTemplate}
                  title="Clone and edit as a new template"
                >
                  ✏️ Clone as New Template
                </button>
                <button
                  type="button"
                  className="jcm-btn jcm-btn--launch"
                  onClick={handleLaunchTemplate}
                >
                  🚀 Instantiate Template ({previewTaskCount} Tasks)
                </button>
              </div>
            </header>

            {/* Stage Pipeline Sequence */}
            <div className="jcm-recipe-stages-bar">
              <span className="jcm-eyebrow">BLUEPRINT TASK CHAIN:</span>
              <div className="jcm-stages-list">
                {selectedTemplate?.tasks.map((task, idx) => (
                  <span key={idx} className="jcm-stage-pill">
                    <b>0{idx + 1}</b> {task.name || task.task_type}
                  </span>
                ))}
              </div>
            </div>

            {/* Target Performers Section */}
            <div className="jcm-performer-section" style={{ marginTop: '1.25rem' }}>
              <div className="jcm-label-row">
                <label><strong>Target Creators / Performers *</strong></label>
                <span className="jcm-badge">{templateUsernames.length} selected</span>
              </div>

              {/* Tag Chips */}
              <div className="jcm-chips-wrap">
                {templateUsernames.map((u) => (
                  <span key={u} className="jcm-chip">
                    @{u}
                    <button
                      type="button"
                      onClick={() => removeTemplateUsername(u)}
                      aria-label={`Remove ${u}`}
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>

              {/* Autocomplete Input */}
              <div className="jcm-autocomplete-box">
                <input
                  type="text"
                  value={usernameSearch}
                  onChange={(e) => {
                    setUsernameSearch(e.target.value);
                    setShowSuggestions(true);
                  }}
                  onFocus={() => setShowSuggestions(true)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && usernameSearch.trim()) {
                      e.preventDefault();
                      addTemplateUsername(usernameSearch);
                    }
                  }}
                  placeholder="Search active subscriptions or type handle and hit Enter..."
                />
                {showSuggestions && usernameSearch.length >= 1 && (
                  <div className="jcm-suggestions-dropdown">
                    {MOCK_SUBSCRIPTIONS.filter((s) =>
                      s.username.toLowerCase().includes(usernameSearch.toLowerCase())
                    ).map((sub) => (
                      <button
                        type="button"
                        key={sub.id}
                        className="jcm-suggestion-item"
                        onClick={() => addTemplateUsername(sub.username)}
                      >
                        <strong>@{sub.username}</strong>
                        <span>{sub.subscribed_at} • {sub.site}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Active Auth Qualification Matrix */}
            <div className="jcm-qualification-box" style={{ marginTop: '1.25rem' }}>
              <div className="jcm-label-row">
                <label><strong>Active Auth Qualification Check</strong></label>
                <select
                  value={String(selectedAuthId)}
                  onChange={(e) =>
                    setSelectedAuthId(e.target.value === 'all' ? 'all' : Number(e.target.value))
                  }
                  style={{ maxWidth: '240px' }}
                >
                  <option value="all">Check All Active Auths ({activeAuths.length})</option>
                  {activeAuths.map((a) => (
                    <option key={a.id} value={a.id}>{a.username} (id: {a.id})</option>
                  ))}
                </select>
              </div>

              <div className="jcm-auth-qualification-list">
                {templateUsernames.map((u) => {
                  const qualified = authsPerUsername[u] || [1];
                  return (
                    <div key={u} className="jcm-qual-item">
                      <span>@{u}</span>
                      <span className="jcm-qual-tag is-pass">
                        ✓ {qualified.length} active auth session{qualified.length > 1 ? 's' : ''} qualified
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Execution Schedule & Policy */}
            <div className="jcm-policy-bar" style={{ marginTop: '1.25rem' }}>
              <label className="jcm-checkbox-row">
                <input
                  type="checkbox"
                  checked={scheduleEnabled}
                  onChange={(e) => setScheduleEnabled(e.target.checked)}
                />
                <span>Schedule Recurring Run</span>
              </label>

              {scheduleEnabled && (
                <div className="jcm-schedule-mini-row">
                  <select
                    value={scheduleType}
                    onChange={(e) => setScheduleType(e.target.value as ScheduleType)}
                  >
                    <option value="interval">Every</option>
                    <option value="cron">Cron</option>
                  </select>
                  {scheduleType === 'interval' ? (
                    <>
                      <input
                        type="number"
                        min="1"
                        style={{ width: '60px' }}
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
                      placeholder="0 */12 * * *"
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
        ) : (
          /* Template Authoring Studio */
          <div className="jcm-recipe-detail jcm-card">
            <header className="jcm-pane-head">
              <div>
                <span className="jcm-eyebrow">TEMPLATE STUDIO // AUTHORING LAB</span>
                <h3>Create New Reusable Template</h3>
                <p>Define parametric blueprints with custom parameter inputs and task chains.</p>
              </div>
              <button
                type="button"
                className="jcm-btn jcm-btn--quiet"
                onClick={() => setActiveView('run')}
              >
                Back to Catalog
              </button>
            </header>

            <form onSubmit={handleCreateTemplate} className="jcm-studio-form">
              <div className="jcm-form-grid">
                <div className="jcm-field">
                  <label>Template Name *</label>
                  <input
                    type="text"
                    required
                    value={authoringTemplateName}
                    onChange={(e) => setAuthoringTemplateName(e.target.value)}
                    placeholder="e.g. Creator Full Archive Recipe"
                  />
                </div>
                <div className="jcm-field">
                  <label>Default Priority (1-100)</label>
                  <input type="number" min="1" max="100" defaultValue="40" />
                </div>
              </div>

              <div className="jcm-field">
                <label>Template Description</label>
                <textarea
                  rows={2}
                  value={authoringTemplateDesc}
                  onChange={(e) => setAuthoringTemplateDesc(e.target.value)}
                  placeholder="Explain the workflow archetypes and use cases for this template..."
                />
              </div>

              {/* Parameter Schema Builder */}
              <div className="jcm-authoring-section">
                <div className="jcm-label-row">
                  <label><strong>Template Input Parameters Schema</strong></label>
                  <button
                    type="button"
                    className="jcm-mini-btn"
                    onClick={handleAddParamToAuthor}
                  >
                    + Add Parameter
                  </button>
                </div>
                <div className="jcm-schema-list">
                  {newParams.map((p, idx) => (
                    <div key={idx} className="jcm-schema-item">
                      <div className="jcm-schema-left">
                        <code className="jcm-schema-code">{`{${p.name}}`}</code>
                        <strong className="jcm-schema-label">{p.label}</strong>
                      </div>
                      <div className="jcm-schema-right">
                        <span className="jcm-schema-type">{p.type}</span>
                        <span className={`jcm-schema-badge ${p.required ? 'is-required' : 'is-optional'}`}>
                          {p.required ? 'Required' : 'Optional'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Task Sequence Chain Builder */}
              <div className="jcm-authoring-section" style={{ marginTop: '1.25rem' }}>
                <div className="jcm-label-row">
                  <label><strong>Template Task Sequence</strong></label>
                  <div className="jcm-quick-task-buttons">
                    <button
                      type="button"
                      className="jcm-mini-btn"
                      onClick={() => handleAddTaskToAuthor('scrape_user', 'Scrape User')}
                    >
                      + Scrape
                    </button>
                    <button
                      type="button"
                      className="jcm-mini-btn"
                      onClick={() => handleAddTaskToAuthor('download_media', 'Download Media')}
                    >
                      + Download
                    </button>
                    <button
                      type="button"
                      className="jcm-mini-btn"
                      onClick={() => handleAddTaskToAuthor('scrape_paid_content', 'Scrape PPV')}
                    >
                      + PPV
                    </button>
                    <button
                      type="button"
                      className="jcm-mini-btn"
                      onClick={() => handleAddTaskToAuthor('verify_checksums', 'Checksums')}
                    >
                      + Checksum
                    </button>
                  </div>
                </div>

                <div className="jcm-stages-list" style={{ marginTop: '0.75rem' }}>
                  {newTasks.map((t, idx) => (
                    <span key={idx} className="jcm-stage-pill">
                      <b>0{idx + 1}</b> {t.name} (<code>{t.task_type}</code>)
                    </span>
                  ))}
                </div>
              </div>

              <div className="jcm-form-actions" style={{ marginTop: '2rem' }}>
                <button
                  type="button"
                  className="jcm-btn jcm-btn--quiet"
                  onClick={() => setActiveView('run')}
                >
                  Cancel
                </button>
                <button type="submit" className="jcm-btn jcm-btn--launch">
                  💾 Save Template to Catalog
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </section>
  );
}
