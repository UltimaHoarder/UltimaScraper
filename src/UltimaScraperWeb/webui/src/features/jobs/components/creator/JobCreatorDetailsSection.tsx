interface JobCreatorDetailsSectionProps {
  creatorMode: 'tasks' | 'template';
  mode: 'create' | 'edit';
  jobName: string;
  onJobNameChange: (value: string) => void;
  saveAsTemplate: boolean;
  onSaveAsTemplateChange: (checked: boolean) => void;
  templateName: string;
  onTemplateNameChange: (value: string) => void;
  templateDescription: string;
  onTemplateDescriptionChange: (value: string) => void;
  selectedTemplateName: string | null;
  templateUsernames: string[];
}

export function JobCreatorDetailsSection({
  creatorMode,
  mode,
  jobName,
  onJobNameChange,
  saveAsTemplate,
  onSaveAsTemplateChange,
  templateName,
  onTemplateNameChange,
  templateDescription,
  onTemplateDescriptionChange,
  selectedTemplateName,
  templateUsernames,
}: JobCreatorDetailsSectionProps) {
  const placeholder =
    creatorMode === 'template' && selectedTemplateName
      ? `Auto: ${selectedTemplateName}${
          templateUsernames.length > 0
            ? ` — ${templateUsernames.slice(0, 2).join(', ')}${
                templateUsernames.length > 2 ? ` +${templateUsernames.length - 2}` : ''
              }`
            : ''
        }`
      : 'Enter a descriptive name for this job';

  return (
    <div className="creator-section">
      <h3 className="section-title">
        <span className="section-icon">📝</span>
        Job Details
      </h3>
      <div className="form-field">
        <label className="field-label">
          Job Name{creatorMode === 'tasks' && <span className="field-required"> *</span>}
        </label>
        <input
          type="text"
          value={jobName}
          onChange={(event) => onJobNameChange(event.target.value)}
          placeholder={placeholder}
          className="field-input"
        />
        <span className="field-hint">
          {creatorMode === 'template'
            ? 'Auto-generated from template and usernames if left blank.'
            : 'A unique name to identify this job'}
        </span>
      </div>

      {mode === 'create' && creatorMode === 'tasks' && (
        <>
          <div className="form-field">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={saveAsTemplate}
                onChange={(event) => onSaveAsTemplateChange(event.target.checked)}
                className="field-checkbox"
              />
              <span>Save as template</span>
            </label>
            <span className="field-hint">Save this configuration for reuse later.</span>
          </div>

          {saveAsTemplate && (
            <>
              <div className="form-field">
                <label className="field-label">
                  Template Name <span className="field-required">*</span>
                </label>
                <input
                  type="text"
                  value={templateName}
                  onChange={(event) => onTemplateNameChange(event.target.value)}
                  placeholder="Enter a template name"
                  className="field-input"
                />
              </div>
              <div className="form-field">
                <label className="field-label">Template Description</label>
                <input
                  type="text"
                  value={templateDescription}
                  onChange={(event) => onTemplateDescriptionChange(event.target.value)}
                  placeholder="Optional description"
                  className="field-input"
                />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
