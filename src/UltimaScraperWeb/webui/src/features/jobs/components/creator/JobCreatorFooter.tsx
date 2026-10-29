interface JobCreatorFooterProps {
  creatorMode: 'tasks' | 'template';
  selectedTemplateId: string;
  selectedTemplateName: string | null;
  templateUsesUsernameParam: boolean;
  templateUsernames: string[];
  selectedAuthId: number | 'all';
  activeAuthCount: number;
  taskCount: number;
  onCancel?: () => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  isSubmitDisabled: boolean;
  submitLabel?: string;
  mode: 'create' | 'edit';
}

export function JobCreatorFooter({
  creatorMode,
  selectedTemplateId,
  selectedTemplateName,
  templateUsesUsernameParam,
  templateUsernames,
  selectedAuthId,
  activeAuthCount,
  taskCount,
  onCancel,
  onSubmit,
  isSubmitting,
  isSubmitDisabled,
  submitLabel,
  mode,
}: JobCreatorFooterProps) {
  const infoText =
    creatorMode === 'template'
      ? !selectedTemplateId
        ? 'Select a template to create a job'
        : templateUsesUsernameParam && templateUsernames.length === 0
          ? 'Add at least one username'
          : templateUsesUsernameParam
            ? `${selectedTemplateName ?? 'Template'} × ${templateUsernames.length} username${
                templateUsernames.length !== 1 ? 's' : ''
              }`
            : `${selectedTemplateName ?? 'Template'} × ${
                selectedAuthId === 'all' ? activeAuthCount : 1
              } auth${selectedAuthId === 'all' ? 's' : ''}`
      : mode === 'edit'
        ? 'Ready to save job changes'
        : taskCount === 0
        ? 'Add tasks to enable job creation'
        : `Ready to create job with ${taskCount} task${taskCount !== 1 ? 's' : ''}`;

  return (
    <div className="creator-footer">
      <div className="footer-info">
        <span className="info-icon">💡</span>
        <span className="info-text">{infoText}</span>
      </div>
      <div className="footer-actions">
        {onCancel && (
          <button className="btn btn-secondary" onClick={onCancel}>
            Cancel
          </button>
        )}
        <button className="btn btn-primary" onClick={onSubmit} disabled={isSubmitDisabled}>
          {isSubmitting ? (
            <>
              <span className="btn-spinner" />
              {submitLabel ? 'Saving...' : 'Creating...'}
            </>
          ) : (
            <>
              <span>🚀</span>
              {submitLabel || (mode === 'edit' ? 'Save Changes' : 'Create Job')}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
