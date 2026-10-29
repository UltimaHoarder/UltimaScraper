import type { KeyboardEvent, ReactNode, RefObject } from 'react';

import type {
  JobTemplateResponse,
  TaskDefinition,
  TemplateParameterPayload,
} from '../../../../api/types/jobs';
import type { AuthCredential } from '../../../../api/types/auths';
import type { SubscriptionInfo } from '../../../../api/types/subscriptions';

interface JobCreatorTemplateBuilderSectionProps {
  selectedTemplateId: string;
  templates: JobTemplateResponse[];
  selectedTemplate: JobTemplateResponse | null;
  onTemplateSelect: (templateId: string) => void;
  taskSupportsAuth: boolean;
  selectedAuthId: number | 'all';
  onSelectedAuthIdChange: (value: number | 'all') => void;
  activeAuths: AuthCredential[];
  loadingAuths: boolean;
  currentSite: string;
  templateUsesUsernameParam: boolean;
  templateUsernames: string[];
  onRemoveTemplateUsername: (username: string) => void;
  usernameSearch: string;
  onUsernameSearchChange: (value: string) => void;
  onUsernameFocus: () => void;
  onUsernameKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
  showUsernameSuggestions: boolean;
  loadingUsernames: boolean;
  usernameSuggestions: SubscriptionInfo[];
  debouncedSearch: string;
  onSuggestionSelect: (subscription: SubscriptionInfo) => void;
  usernameInputRef: RefObject<HTMLInputElement | null>;
  suggestionsRef: RefObject<HTMLDivElement | null>;
  templateParams: Record<string, unknown>;
  onTemplateParamChange: (name: string, value: unknown) => void;
  templateParamToTaskParam: (
    parameter: TemplateParameterPayload
  ) => TaskDefinition['parameters'][0];
  renderParamInput: (
    param: TaskDefinition['parameters'][0],
    paramValues?: Record<string, unknown>,
    onChangeParam?: (name: string, value: unknown) => void
  ) => ReactNode;
}

export function JobCreatorTemplateBuilderSection({
  selectedTemplateId,
  templates,
  selectedTemplate,
  onTemplateSelect,
  taskSupportsAuth,
  selectedAuthId,
  onSelectedAuthIdChange,
  activeAuths,
  loadingAuths,
  currentSite,
  templateUsesUsernameParam,
  templateUsernames,
  onRemoveTemplateUsername,
  usernameSearch,
  onUsernameSearchChange,
  onUsernameFocus,
  onUsernameKeyDown,
  showUsernameSuggestions,
  loadingUsernames,
  usernameSuggestions,
  debouncedSearch,
  onSuggestionSelect,
  usernameInputRef,
  suggestionsRef,
  templateParams,
  onTemplateParamChange,
  templateParamToTaskParam,
  renderParamInput,
}: JobCreatorTemplateBuilderSectionProps) {
  return (
    <div className="creator-section">
      <h3 className="section-title">
        <span className="section-icon">📋</span>
        Template
      </h3>

      <div className="form-field">
        <label className="field-label">Template</label>
        <select
          value={selectedTemplateId}
          onChange={(event) => onTemplateSelect(event.target.value)}
          className="field-select"
        >
          <option value="">Select a template...</option>
          {templates.map((template) => (
            <option key={template.template_id} value={template.template_id}>
              {template.name}
            </option>
          ))}
        </select>
      </div>

      {selectedTemplate && (
        <>
          {selectedTemplate.description && (
            <div className="task-description-box">
              <span className="description-icon">ℹ️</span>
              {selectedTemplate.description}
            </div>
          )}

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
                      ? 'Creates jobs only for auths that have subscription data for the performer (including expired). Auths with no prior relationship are skipped.'
                      : 'Username search is filtered to show only users linked to this auth.'}
              </span>
            </div>
          )}

          {templateUsesUsernameParam && (
            <div className="form-field">
              <label className="field-label">
                Usernames <span className="field-required">*</span>
              </label>
              {templateUsernames.length > 0 && (
                <div className="username-chips">
                  {templateUsernames.map((username) => (
                    <span key={username} className="username-chip">
                      {username}
                      <button
                        type="button"
                        className="username-chip-remove"
                        onClick={() => onRemoveTemplateUsername(username)}
                        title={`Remove ${username}`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="username-autocomplete">
                <input
                  ref={usernameInputRef}
                  type="text"
                  value={usernameSearch}
                  placeholder="Type to search and add usernames..."
                  className="field-input"
                  autoComplete="off"
                  onChange={(event) => onUsernameSearchChange(event.target.value)}
                  onFocus={onUsernameFocus}
                  onKeyDown={onUsernameKeyDown}
                />
                {showUsernameSuggestions && (usernameSearch.length >= 2 || loadingUsernames) && (
                  <div className="username-suggestions" ref={suggestionsRef}>
                    {loadingUsernames ? (
                      <div className="suggestion-loading">Searching...</div>
                    ) : usernameSuggestions.length > 0 ? (
                      usernameSuggestions.map((subscription) => (
                        <div
                          key={`${subscription.user_id}-${subscription.site}`}
                          className="suggestion-item"
                          onMouseDown={(event) => {
                            event.preventDefault();
                            onSuggestionSelect(subscription);
                          }}
                        >
                          <span className="suggestion-username">{subscription.username}</span>
                          {subscription.name && subscription.name !== subscription.username && (
                            <span className="suggestion-name">{subscription.name}</span>
                          )}
                          <span className="suggestion-site">{subscription.site}</span>
                        </div>
                      ))
                    ) : debouncedSearch.length >= 2 ? (
                      <div className="suggestion-empty">No matches. Press Enter to add anyway.</div>
                    ) : null}
                  </div>
                )}
              </div>
              <span className="field-hint">Each username creates a separate job.</span>
            </div>
          )}

          <div className="task-params-grid">
            {selectedTemplate.parameters
              .filter((param) => param.name !== 'username')
              .map((param) => {
                const taskParam = templateParamToTaskParam(param);
                return (
                  <div key={param.name} className="form-field">
                    {taskParam.param_type !== 'boolean' && (
                      <label className="field-label">
                        {taskParam.label}
                        {param.required && <span className="field-required">*</span>}
                      </label>
                    )}
                    {renderParamInput(taskParam, templateParams, onTemplateParamChange)}
                    {param.description && taskParam.param_type !== 'boolean' && (
                      <span className="field-hint">{param.description}</span>
                    )}
                  </div>
                );
              })}
          </div>
        </>
      )}
    </div>
  );
}
