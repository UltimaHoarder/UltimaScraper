import { useCallback, useState, type FormEvent } from 'react';

import type {
  CallbackDefinition,
  EventSubscriptionDefinition,
  OutboundDeliveryDefinition,
  PluginCreateRequest,
  TaskTypeDefinition,
  RemoteDelegationDefinition,
  RemoteDelegationRole,
  RemoteAuthMethod,
  RemoteHttpMethod,
  RemoteHttpOperationDefinition,
  RemoteInboundCallbackDefinition,
} from '../../../api/types/plugins';
import type { TaskDefinition } from '../../../api/types/jobs';
import {
  FIELD_TYPES,
  REMOTE_AUTH_METHODS,
  REMOTE_HTTP_METHODS,
  REMOTE_LIFECYCLE_EVENTS,
  REMOTE_ROLES,
  createHttpOperation,
  createInboundCallbackMapping,
  getMappingLiteral,
  getMappingSourcePath,
} from '../lib/pluginManifestOptions';

function findTaskDefinition(
  taskCatalog: TaskDefinition[],
  taskTypeId: string,
): TaskDefinition | undefined {
  return taskCatalog.find((task) => task.task_id === taskTypeId);
}

// ── Plugin Create Form ──────────────────────────────────────────────────

export function PluginCreateForm({
  onSubmit,
  onCancel,
  isCreating,
  createError,
  taskCatalog,
  isTaskCatalogLoading,
  capabilityOptions,
  eventFamilyOptions,
}: {
  onSubmit: (req: PluginCreateRequest) => void;
  onCancel: () => void;
  isCreating: boolean;
  createError: Error | null;
  taskCatalog: TaskDefinition[];
  isTaskCatalogLoading: boolean;
  capabilityOptions: string[];
  eventFamilyOptions: string[];
}) {
  const [pluginId, setPluginId] = useState('');
  const [pluginVersion, setPluginVersion] = useState('1.0.0');
  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [capabilities, setCapabilities] = useState<Set<string>>(new Set());
  const [pluginTaskTypes, setPluginTaskTypes] = useState<TaskTypeDefinition[]>([]);
  const [eventSubscriptions, setEventSubscriptions] = useState<EventSubscriptionDefinition[]>([]);
  const [callbacks, setCallbacks] = useState<CallbackDefinition[]>([]);
  const [outboundDeliveries, setOutboundDeliveries] = useState<OutboundDeliveryDefinition[]>([]);
  const [stateQuotaBytes, setStateQuotaBytes] = useState(65536);
  const [replayOnEnable] = useState(true);
  const [allowPrivateNetworks, setAllowPrivateNetworks] = useState(false);
  const [allowInsecureHttp, setAllowInsecureHttp] = useState(false);
  const [allowedOutboundDomains, setAllowedOutboundDomains] = useState('');
  const [enableRemoteDelegation, setEnableRemoteDelegation] = useState(false);
  const [remoteDelegation, setRemoteDelegation] = useState<RemoteDelegationDefinition>({
    integration_id: '',
    role: 'submitter',
    description: '',
    external_system_url: '',
    auth: { method: 'api_key', header_name: 'X-API-Key' },
    correlation: { local_id_field: 'usr_submission_id', remote_id_field: 'remote_job_id', submitter_id_field: 'submitted_by' },
    operations: {
      submission: createHttpOperation('POST', ''),
    },
    callbacks: {
      inbound: [],
    },
  });

  const updateRemoteOperation = useCallback(
    (
      operationName: keyof NonNullable<RemoteDelegationDefinition['operations']>,
      updater: (current: RemoteHttpOperationDefinition) => RemoteHttpOperationDefinition,
    ) => {
      setRemoteDelegation((prev) => ({
        ...prev,
        operations: {
          ...(prev.operations ?? {}),
          [operationName]: updater(
            prev.operations?.[operationName] ??
              createHttpOperation(operationName === 'poll' ? 'GET' : 'POST', ''),
          ),
        },
      }));
    },
    [],
  );

  const updateInboundCallback = useCallback(
    (
      index: number,
      updater: (current: RemoteInboundCallbackDefinition) => RemoteInboundCallbackDefinition,
    ) => {
      setRemoteDelegation((prev) => ({
        ...prev,
        callbacks: {
          inbound: (prev.callbacks?.inbound ?? []).map((item, itemIndex) =>
            itemIndex === index ? updater(item) : item,
          ),
        },
      }));
    },
    [],
  );

  const toggleCapability = useCallback((cap: string) => {
    setCapabilities((prev) => {
      const next = new Set(prev);
      if (next.has(cap)) {
        next.delete(cap);
      } else {
        next.add(cap);
      }
      return next;
    });
  }, []);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const sanitizedOperations = Object.fromEntries(
      Object.entries(remoteDelegation.operations ?? {}).filter(([, operation]) =>
        Boolean(operation?.endpoint?.trim()),
      ),
    );
    const sanitizedInboundCallbacks = (remoteDelegation.callbacks?.inbound ?? []).filter(
      (mapping) => mapping.handler_id.trim().length > 0,
    );
    const request: PluginCreateRequest = {
      plugin_id: pluginId,
      plugin_version: pluginVersion,
      display_name: displayName,
      description,
      capabilities: Array.from(capabilities),
      task_types: pluginTaskTypes,
      event_subscriptions: eventSubscriptions,
      callbacks,
      outbound_deliveries: outboundDeliveries,
      operational_policy: {
        state_quota_bytes: stateQuotaBytes,
        replay_on_enable: replayOnEnable,
        allow_private_networks: allowPrivateNetworks,
        allow_insecure_http: allowInsecureHttp,
        allowed_outbound_domains: allowedOutboundDomains
          .split(',')
          .map((domain) => domain.trim())
          .filter(Boolean),
      },
      remote_delegation: enableRemoteDelegation
        ? {
            ...remoteDelegation,
            operations: sanitizedOperations,
            callbacks: {
              inbound: sanitizedInboundCallbacks,
            },
          }
        : null,
    };
    onSubmit(request);
  };

  return (
    <form className="plugins-create-panel" onSubmit={handleSubmit}>
      <div className="plugins-create-header">
        <h3>Create New Plugin</h3>
      </div>

      {createError && (
        <div className="plugins-error">
          {createError.message}
        </div>
      )}

      {/* ── Metadata section ── */}
      <div className="plugins-section">
        <div className="plugins-section-title">Metadata</div>
        <div className="plugins-field-row">
          <div className="plugins-field">
            <label>Plugin ID</label>
            <input
              type="text"
              value={pluginId}
              onChange={(e) => setPluginId(e.target.value)}
              placeholder="my-plugin-name"
              required
              pattern="^[a-z][a-z0-9_-]{1,62}[a-z0-9]$"
              title="Lowercase letters, numbers, hyphens, underscores. 3-64 chars."
            />
          </div>
          <div className="plugins-field">
            <label>Version</label>
            <input
              type="text"
              value={pluginVersion}
              onChange={(e) => setPluginVersion(e.target.value)}
              placeholder="1.0.0"
              required
            />
          </div>
        </div>
        <div className="plugins-field-row">
          <div className="plugins-field">
            <label>Display Name</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="My Plugin"
              required
            />
          </div>
          <div className="plugins-field">
            <label>Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this plugin do?"
            />
          </div>
        </div>
      </div>

      {/* ── Capabilities section ── */}
      <div className="plugins-section">
        <div className="plugins-section-title">Capabilities</div>
        <div className="plugins-caps-grid">
          {capabilityOptions.map((cap) => (
            <label key={cap} className="plugins-cap-check">
              <input
                type="checkbox"
                checked={capabilities.has(cap)}
                onChange={() => toggleCapability(cap)}
              />
              {cap}
            </label>
          ))}
        </div>
      </div>

      {/* ── Task Types section ── */}
      <div className="plugins-section">
        <div className="plugins-section-title">Task Types</div>
        <div className="plugins-list-editor">
          {pluginTaskTypes.map((jt, i) => {
            const selectedTaskDef = findTaskDefinition(taskCatalog, jt.task_type);
            return (
            <div key={i} className="plugins-list-item">
              <div className="plugins-list-item-header">
                <span>Task Type #{i + 1}</span>
                <button
                  type="button"
                  className="plugins-list-remove-btn"
                  onClick={() => setPluginTaskTypes((prev) => prev.filter((_, idx) => idx !== i))}
                >
                  Remove
                </button>
              </div>
              <div className="plugins-field-row">
                <div className="plugins-field">
                  <label>Runtime Task Type</label>
                  <select
                    value={jt.task_type}
                    onChange={(e) =>
                      setPluginTaskTypes((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, task_type: e.target.value } : item,
                        ),
                      )
                    }
                    required
                    disabled={isTaskCatalogLoading}
                  >
                    <option value="">{isTaskCatalogLoading ? 'Loading task types...' : 'Select a task type'}</option>
                    {taskCatalog.map((task) => (
                      <option key={task.task_id} value={task.task_id}>
                        {task.name} - {task.category}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="plugins-field">
                  <label>Description</label>
                  <input
                    type="text"
                    value={jt.description ?? ''}
                    onChange={(e) =>
                      setPluginTaskTypes((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, description: e.target.value } : item,
                        ),
                      )
                    }
                    placeholder="Optional plugin-specific override description"
                  />
                </div>
              </div>
              {selectedTaskDef && (
                <div className="plugins-error" style={{ borderColor: 'var(--color-border-primary, #30363d)', background: 'transparent', color: 'var(--color-text-secondary, #8b949e)' }}>
                  <strong>{selectedTaskDef.name}</strong>: {selectedTaskDef.description}
                  {selectedTaskDef.parameters.length > 0 && (
                    <div style={{ marginTop: 6, fontSize: '0.78rem' }}>
                      Runtime parameters: {selectedTaskDef.parameters.map((param) => param.label).join(', ')}
                    </div>
                  )}
                </div>
              )}
              <div className="plugins-field-row">
                <div className="plugins-field">
                  <label>Max Priority</label>
                  <input
                    type="number"
                    value={jt.max_priority ?? 10}
                    min={0}
                    max={100}
                    onChange={(e) =>
                      setPluginTaskTypes((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, max_priority: Number(e.target.value) } : item,
                        ),
                      )
                    }
                  />
                </div>
              </div>
              {/* Payload fields sub-list */}
              <div className="plugins-section">
                <div className="plugins-section-title" style={{ fontSize: '0.72rem' }}>
                  Payload Fields
                </div>
                {(jt.payload_fields ?? []).map((pf, fi) => (
                  <div key={fi} className="plugins-list-item" style={{ marginLeft: 8 }}>
                    <div className="plugins-list-item-header">
                      <span>Field #{fi + 1}</span>
                      <button
                        type="button"
                        className="plugins-list-remove-btn"
                        onClick={() =>
                          setPluginTaskTypes((prev) =>
                            prev.map((item, idx) =>
                              idx === i
                                ? {
                                    ...item,
                                    payload_fields: (item.payload_fields ?? []).filter(
                                      (_, fidx) => fidx !== fi,
                                    ),
                                  }
                                : item,
                            ),
                          )
                        }
                      >
                        Remove
                      </button>
                    </div>
                    <div className="plugins-field-row">
                      <div className="plugins-field">
                        <label>Name</label>
                        <input
                          type="text"
                          value={pf.name}
                          onChange={(e) =>
                            setPluginTaskTypes((prev) =>
                              prev.map((item, idx) =>
                                idx === i
                                  ? {
                                      ...item,
                                      payload_fields: (item.payload_fields ?? []).map(
                                        (field, fidx) =>
                                          fidx === fi
                                            ? { ...field, name: e.target.value }
                                            : field,
                                      ),
                                    }
                                  : item,
                              ),
                            )
                          }
                          required
                        />
                      </div>
                      <div className="plugins-field">
                        <label>Type</label>
                        <select
                          value={pf.field_type}
                          onChange={(e) =>
                            setPluginTaskTypes((prev) =>
                              prev.map((item, idx) =>
                                idx === i
                                  ? {
                                      ...item,
                                      payload_fields: (item.payload_fields ?? []).map(
                                        (field, fidx) =>
                                          fidx === fi
                                            ? {
                                                ...field,
                                                field_type: e.target.value as typeof pf.field_type,
                                              }
                                            : field,
                                      ),
                                    }
                                  : item,
                              ),
                            )
                          }
                        >
                          {FIELD_TYPES.map((ft) => (
                            <option key={ft} value={ft}>
                              {ft}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <label className="plugins-cap-check">
                      <input
                        type="checkbox"
                        checked={pf.required ?? true}
                        onChange={(e) =>
                          setPluginTaskTypes((prev) =>
                            prev.map((item, idx) =>
                              idx === i
                                ? {
                                    ...item,
                                    payload_fields: (item.payload_fields ?? []).map(
                                      (field, fidx) =>
                                        fidx === fi
                                          ? { ...field, required: e.target.checked }
                                          : field,
                                    ),
                                  }
                                : item,
                            ),
                          )
                        }
                      />
                      Required
                    </label>
                  </div>
                ))}
                <button
                  type="button"
                  className="plugins-list-add-btn"
                  onClick={() =>
                    setPluginTaskTypes((prev) =>
                      prev.map((item, idx) =>
                        idx === i
                          ? {
                              ...item,
                              payload_fields: [
                                ...(item.payload_fields ?? []),
                                { name: '', field_type: 'string', required: true },
                              ],
                            }
                          : item,
                      ),
                    )
                  }
                >
                  + Add Payload Field
                </button>
              </div>
            </div>
            );
          })}
          <button
            type="button"
            className="plugins-list-add-btn"
            onClick={() =>
              setPluginTaskTypes((prev) => [
                ...prev,
                {
                  task_type: taskCatalog[0]?.task_id ?? '',
                  description: '',
                  payload_fields: [],
                  max_priority: 10,
                },
              ])
            }
            disabled={isTaskCatalogLoading}
          >
            + Add Task Type
          </button>
        </div>
      </div>

      {/* ── Outbound Deliveries section ── */}
      <div className="plugins-section">
        <div className="plugins-section-title">Outbound Deliveries</div>
        <div className="plugins-list-editor">
          {outboundDeliveries.map((od, i) => (
            <div key={i} className="plugins-list-item">
              <div className="plugins-list-item-header">
                <span>Delivery Target #{i + 1}</span>
                <button
                  type="button"
                  className="plugins-list-remove-btn"
                  onClick={() =>
                    setOutboundDeliveries((prev) => prev.filter((_, idx) => idx !== i))
                  }
                >
                  Remove
                </button>
              </div>
              <div className="plugins-field-row">
                <div className="plugins-field">
                  <label>Target Name</label>
                  <input
                    type="text"
                    value={od.target_name}
                    onChange={(e) =>
                      setOutboundDeliveries((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, target_name: e.target.value } : item,
                        ),
                      )
                    }
                    placeholder="main"
                    required
                  />
                </div>
                <div className="plugins-field">
                  <label>URL</label>
                  <input
                    type="url"
                    value={od.url}
                    onChange={(e) =>
                      setOutboundDeliveries((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, url: e.target.value } : item,
                        ),
                      )
                    }
                    placeholder="https://example.com/hook"
                    required
                  />
                </div>
              </div>
              <div className="plugins-field-row--full">
                <div className="plugins-field">
                  <label>Description</label>
                  <input
                    type="text"
                    value={od.description ?? ''}
                    onChange={(e) =>
                      setOutboundDeliveries((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, description: e.target.value } : item,
                        ),
                      )
                    }
                  />
                </div>
              </div>
            </div>
          ))}
          <button
            type="button"
            className="plugins-list-add-btn"
            onClick={() =>
              setOutboundDeliveries((prev) => [
                ...prev,
                { target_name: '', url: '', description: '' },
              ])
            }
          >
            + Add Delivery Target
          </button>
        </div>
      </div>

      {/* ── Event Subscriptions section ── */}
      <div className="plugins-section">
        <div className="plugins-section-title">Event Subscriptions</div>
        <div className="plugins-list-editor">
          {eventSubscriptions.map((es, i) => (
            <div key={i} className="plugins-list-item">
              <div className="plugins-list-item-header">
                <span>Subscription #{i + 1}</span>
                <button
                  type="button"
                  className="plugins-list-remove-btn"
                  onClick={() =>
                    setEventSubscriptions((prev) => prev.filter((_, idx) => idx !== i))
                  }
                >
                  Remove
                </button>
              </div>
              <div className="plugins-field-row">
                <div className="plugins-field">
                  <label>Event Family</label>
                  <select
                    value={es.event_family}
                    onChange={(e) =>
                      setEventSubscriptions((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, event_family: e.target.value } : item,
                        ),
                      )
                    }
                  >
                    <option value="">Select...</option>
                    {eventFamilyOptions.map((ef) => (
                      <option key={ef} value={ef}>
                        {ef}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="plugins-field">
                  <label>Delivery Target</label>
                  <input
                    type="text"
                    value={es.delivery_target}
                    onChange={(e) =>
                      setEventSubscriptions((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, delivery_target: e.target.value } : item,
                        ),
                      )
                    }
                    placeholder="Must match an outbound delivery target name"
                    required
                  />
                </div>
              </div>
              <div className="plugins-field-row--full">
                <div className="plugins-field">
                  <label>Event Types (comma-separated)</label>
                  <input
                    type="text"
                    value={(es.event_types ?? []).join(', ')}
                    onChange={(e) =>
                      setEventSubscriptions((prev) =>
                        prev.map((item, idx) =>
                          idx === i
                            ? {
                                ...item,
                                event_types: e.target.value
                                  .split(',')
                                  .map((s) => s.trim())
                                  .filter(Boolean),
                              }
                            : item,
                        ),
                      )
                    }
                    placeholder="job.created, job.completed"
                  />
                </div>
              </div>
            </div>
          ))}
          <button
            type="button"
            className="plugins-list-add-btn"
            onClick={() =>
              setEventSubscriptions((prev) => [
                ...prev,
                { event_family: '', event_types: [], delivery_target: '' },
              ])
            }
          >
            + Add Event Subscription
          </button>
        </div>
      </div>

      {/* ── Callbacks section ── */}
      <div className="plugins-section">
        <div className="plugins-section-title">Callbacks</div>
        <div className="plugins-list-editor">
          {callbacks.map((cb, i) => (
            <div key={i} className="plugins-list-item">
              <div className="plugins-list-item-header">
                <span>Callback #{i + 1}</span>
                <button
                  type="button"
                  className="plugins-list-remove-btn"
                  onClick={() => setCallbacks((prev) => prev.filter((_, idx) => idx !== i))}
                >
                  Remove
                </button>
              </div>
              <div className="plugins-field-row">
                <div className="plugins-field">
                  <label>Handler ID</label>
                  <input
                    type="text"
                    value={cb.handler_id}
                    onChange={(e) =>
                      setCallbacks((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, handler_id: e.target.value } : item,
                        ),
                      )
                    }
                    placeholder="on-event-received"
                    required
                  />
                </div>
                <div className="plugins-field">
                  <label>Auth Method</label>
                  <select
                    value={cb.auth_method ?? 'hmac'}
                    onChange={(e) =>
                      setCallbacks((prev) =>
                        prev.map((item, idx) =>
                          idx === i
                            ? { ...item, auth_method: e.target.value as 'hmac' | 'bearer' }
                            : item,
                        ),
                      )
                    }
                  >
                    <option value="hmac">HMAC</option>
                    <option value="bearer">Bearer</option>
                  </select>
                </div>
              </div>
              <div className="plugins-field-row--full">
                <div className="plugins-field">
                  <label>Description</label>
                  <input
                    type="text"
                    value={cb.description ?? ''}
                    onChange={(e) =>
                      setCallbacks((prev) =>
                        prev.map((item, idx) =>
                          idx === i ? { ...item, description: e.target.value } : item,
                        ),
                      )
                    }
                  />
                </div>
              </div>
            </div>
          ))}
          <button
            type="button"
            className="plugins-list-add-btn"
            onClick={() =>
              setCallbacks((prev) => [
                ...prev,
                { handler_id: '', auth_method: 'hmac', description: '' },
              ])
            }
          >
            + Add Callback
          </button>
        </div>
      </div>

      {/* ── Remote Delegation section ── */}
      <div className="plugins-section">
        <div className="plugins-section-title">Remote Delegation</div>
        <label className="plugins-cap-check" style={{ marginBottom: 8 }}>
          <input
            type="checkbox"
            checked={enableRemoteDelegation}
            onChange={(e) => setEnableRemoteDelegation(e.target.checked)}
          />
          Enable remote delegation
        </label>
        {enableRemoteDelegation && (
          <div className="plugins-list-editor">
            <div className="plugins-field-row">
              <div className="plugins-field">
                <label>Integration ID</label>
                <input
                  type="text"
                  value={remoteDelegation.integration_id}
                  onChange={(e) => setRemoteDelegation((prev) => ({ ...prev, integration_id: e.target.value }))}
                  placeholder="my-remote-system"
                  required
                  pattern="^[a-z][a-z0-9_-]{1,62}[a-z0-9]$"
                  title="Lowercase letters, numbers, hyphens, underscores. 3-64 chars."
                />
              </div>
              <div className="plugins-field">
                <label>Role</label>
                <select
                  value={remoteDelegation.role}
                  onChange={(e) => setRemoteDelegation((prev) => ({ ...prev, role: e.target.value as RemoteDelegationRole }))}
                >
                  {REMOTE_ROLES.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="plugins-field-row">
              <div className="plugins-field">
                <label>Description</label>
                <input
                  type="text"
                  value={remoteDelegation.description ?? ''}
                  onChange={(e) => setRemoteDelegation((prev) => ({ ...prev, description: e.target.value }))}
                  placeholder="What does this integration do?"
                />
              </div>
            </div>

            <div className="plugins-hint-box" style={{ background: 'var(--surface-02, #1a1a2e)', border: '1px solid var(--border-subtle, #333)', borderRadius: 6, padding: '8px 12px', margin: '8px 0', fontSize: '0.72rem', lineHeight: 1.5, color: 'var(--text-secondary, #999)' }}>
              Remote delegation uses per-operation HTTP mappings in v2. The create form captures the common operation endpoints and inbound callback extraction fields, and you can refine deeper request or response mappings later in the raw manifest editor.
            </div>

            <div className="plugins-section-title" style={{ fontSize: '0.72rem', marginTop: 8 }}>Remote System</div>
            <div className="plugins-field-row">
              <div className="plugins-field">
                <label>External System URL</label>
                <input
                  type="url"
                  value={remoteDelegation.external_system_url ?? ''}
                  onChange={(e) => setRemoteDelegation((prev) => ({ ...prev, external_system_url: e.target.value }))}
                  placeholder="https://remote.example.com"
                  required
                />
              </div>
            </div>

            {/* Auth config */}
            <div className="plugins-section-title" style={{ fontSize: '0.72rem', marginTop: 8 }}>Authentication</div>
            <div className="plugins-field-row">
              <div className="plugins-field">
                <label>Auth Method</label>
                <select
                  value={remoteDelegation.auth?.method ?? 'api_key'}
                  onChange={(e) => setRemoteDelegation((prev) => ({ ...prev, auth: { ...prev.auth, method: e.target.value as RemoteAuthMethod } }))}
                >
                  {REMOTE_AUTH_METHODS.map((m) => (
                    <option key={m} value={m}>{m.replace('_', ' ')}</option>
                  ))}
                </select>
              </div>
              <div className="plugins-field">
                <label>Auth Header</label>
                <input
                  type="text"
                  value={remoteDelegation.auth?.header_name ?? 'X-API-Key'}
                  onChange={(e) => setRemoteDelegation((prev) => ({ ...prev, auth: { ...prev.auth, header_name: e.target.value } }))}
                />
              </div>
            </div>

            {(remoteDelegation.role === 'submitter' || remoteDelegation.role === 'bidirectional') && (
              <>
                <div className="plugins-section-title" style={{ fontSize: '0.72rem', marginTop: 8 }}>Submission Operation</div>
                <div className="plugins-field-row">
                  <div className="plugins-field">
                    <label>Method</label>
                    <select
                      value={remoteDelegation.operations?.submission?.method ?? 'POST'}
                      onChange={(e) =>
                        updateRemoteOperation('submission', (current) => ({
                          ...current,
                          method: e.target.value as RemoteHttpMethod,
                        }))
                      }
                    >
                      {REMOTE_HTTP_METHODS.map((method) => (
                        <option key={method} value={method}>{method}</option>
                      ))}
                    </select>
                  </div>
                  <div className="plugins-field">
                    <label>Endpoint</label>
                    <input
                      type="text"
                      value={remoteDelegation.operations?.submission?.endpoint ?? ''}
                      onChange={(e) =>
                        updateRemoteOperation('submission', (current) => ({
                          ...current,
                          endpoint: e.target.value,
                        }))
                      }
                      placeholder="/api/jobs"
                      required
                    />
                  </div>
                </div>

                <div className="plugins-section-title" style={{ fontSize: '0.72rem', marginTop: 8 }}>Polling Operation</div>
                <div className="plugins-field-row">
                  <div className="plugins-field">
                    <label>Method</label>
                    <select
                      value={remoteDelegation.operations?.poll?.method ?? 'GET'}
                      onChange={(e) =>
                        updateRemoteOperation('poll', (current) => ({
                          ...current,
                          method: e.target.value as RemoteHttpMethod,
                        }))
                      }
                    >
                      {REMOTE_HTTP_METHODS.map((method) => (
                        <option key={method} value={method}>{method}</option>
                      ))}
                    </select>
                  </div>
                  <div className="plugins-field">
                    <label>Endpoint</label>
                    <input
                      type="text"
                      value={remoteDelegation.operations?.poll?.endpoint ?? ''}
                      onChange={(e) =>
                        updateRemoteOperation('poll', (current) => ({
                          ...current,
                          endpoint: e.target.value,
                        }))
                      }
                      placeholder="/api/jobs/{external_job_id}"
                    />
                  </div>
                </div>
              </>
            )}

            {(remoteDelegation.role === 'executor' || remoteDelegation.role === 'bidirectional') && (
              <>
                <div className="plugins-section-title" style={{ fontSize: '0.72rem', marginTop: 8 }}>Execution Operations</div>
                {([
                  ['claim', 'Claim', true, '/api/jobs/claim', 'POST'],
                  ['heartbeat', 'Heartbeat', false, '/api/jobs/{external_job_id}/heartbeat', 'POST'],
                  ['progress', 'Progress', false, '/api/jobs/{external_job_id}/progress', 'POST'],
                  ['complete', 'Complete', false, '/api/jobs/{external_job_id}/complete', 'POST'],
                  ['fail', 'Fail', false, '/api/jobs/{external_job_id}/fail', 'POST'],
                  ['cancel', 'Cancel', false, '/api/jobs/{external_job_id}/cancel', 'POST'],
                ] as const).map(([operationName, label, required, placeholder, defaultMethod]) => (
                  <div key={operationName} className="plugins-list-item">
                    <div className="plugins-list-item-header">
                      <span>{label}</span>
                    </div>
                    <div className="plugins-field-row">
                      <div className="plugins-field">
                        <label>Method</label>
                        <select
                          value={remoteDelegation.operations?.[operationName]?.method ?? defaultMethod}
                          onChange={(e) =>
                            updateRemoteOperation(operationName, (current) => ({
                              ...current,
                              method: e.target.value as RemoteHttpMethod,
                            }))
                          }
                        >
                          {REMOTE_HTTP_METHODS.map((method) => (
                            <option key={method} value={method}>{method}</option>
                          ))}
                        </select>
                      </div>
                      <div className="plugins-field">
                        <label>Endpoint</label>
                        <input
                          type="text"
                          value={remoteDelegation.operations?.[operationName]?.endpoint ?? ''}
                          onChange={(e) =>
                            updateRemoteOperation(operationName, (current) => ({
                              ...current,
                              endpoint: e.target.value,
                            }))
                          }
                          placeholder={placeholder}
                          required={required}
                        />
                      </div>
                    </div>
                  </div>
                ))}

                <div style={{ marginTop: 8 }}>
                  <div className="plugins-section-title" style={{ fontSize: '0.72rem' }}>Inbound Callback Mappings</div>
                  {(remoteDelegation.callbacks?.inbound ?? []).map((mapping, i) => (
                    <div key={i} className="plugins-list-item">
                      <div className="plugins-list-item-header">
                        <span>Inbound Mapping #{i + 1}</span>
                        <button
                          type="button"
                          className="plugins-list-remove-btn"
                          onClick={() =>
                            setRemoteDelegation((prev) => ({
                              ...prev,
                              callbacks: {
                                inbound: (prev.callbacks?.inbound ?? []).filter((_, idx) => idx !== i),
                              },
                            }))
                          }
                        >
                          Remove
                        </button>
                      </div>
                      <div className="plugins-field-row">
                        <div className="plugins-field">
                          <label>Handler ID</label>
                          <input
                            type="text"
                            value={mapping.handler_id}
                            onChange={(e) =>
                              updateInboundCallback(i, (current) => ({
                                ...current,
                                handler_id: e.target.value,
                              }))
                            }
                            placeholder="Must match a declared callback handler"
                            required
                          />
                        </div>
                        <div className="plugins-field">
                          <label>Lifecycle Event</label>
                          <select
                            value={getMappingLiteral(mapping.extract.lifecycle_event)}
                            onChange={(e) =>
                              updateInboundCallback(i, (current) => ({
                                ...current,
                                extract: {
                                  ...current.extract,
                                  lifecycle_event: { literal: e.target.value },
                                },
                              }))
                            }
                          >
                            {REMOTE_LIFECYCLE_EVENTS.map((eventName) => (
                              <option key={eventName} value={eventName}>{eventName}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div className="plugins-field-row">
                        <div className="plugins-field">
                          <label>Correlation Source Path</label>
                          <input
                            type="text"
                            value={getMappingSourcePath(mapping.extract.correlation_id)}
                            onChange={(e) =>
                              updateInboundCallback(i, (current) => ({
                                ...current,
                                extract: {
                                  ...current.extract,
                                  correlation_id: e.target.value ? { source_path: e.target.value } : undefined,
                                },
                              }))
                            }
                            placeholder="callback.body.correlation_id"
                          />
                        </div>
                        <div className="plugins-field">
                          <label>External Job Source Path</label>
                          <input
                            type="text"
                            value={getMappingSourcePath(mapping.extract.external_job_id)}
                            onChange={(e) =>
                              updateInboundCallback(i, (current) => ({
                                ...current,
                                extract: {
                                  ...current.extract,
                                  external_job_id: e.target.value ? { source_path: e.target.value } : undefined,
                                },
                              }))
                            }
                            placeholder="callback.body.external_job_id"
                          />
                        </div>
                      </div>
                      <div className="plugins-field-row">
                        <div className="plugins-field">
                          <label>Status Source Path</label>
                          <input
                            type="text"
                            value={getMappingSourcePath(mapping.extract.remote_status)}
                            onChange={(e) =>
                              updateInboundCallback(i, (current) => ({
                                ...current,
                                extract: {
                                  ...current.extract,
                                  remote_status: e.target.value ? { source_path: e.target.value } : undefined,
                                },
                              }))
                            }
                            placeholder="callback.body.remote_status"
                          />
                        </div>
                        <div className="plugins-field">
                          <label>Progress Source Path</label>
                          <input
                            type="text"
                            value={getMappingSourcePath(mapping.extract.progress)}
                            onChange={(e) =>
                              updateInboundCallback(i, (current) => ({
                                ...current,
                                extract: {
                                  ...current.extract,
                                  progress: e.target.value ? { source_path: e.target.value } : undefined,
                                },
                              }))
                            }
                            placeholder="callback.body.progress"
                          />
                        </div>
                      </div>
                      <div className="plugins-field-row">
                        <div className="plugins-field">
                          <label>Result Source Path</label>
                          <input
                            type="text"
                            value={getMappingSourcePath(mapping.extract.result)}
                            onChange={(e) =>
                              updateInboundCallback(i, (current) => ({
                                ...current,
                                extract: {
                                  ...current.extract,
                                  result: e.target.value ? { source_path: e.target.value } : undefined,
                                },
                              }))
                            }
                            placeholder="callback.body.result"
                          />
                        </div>
                        <div className="plugins-field">
                          <label>Error Source Path</label>
                          <input
                            type="text"
                            value={getMappingSourcePath(mapping.extract.error)}
                            onChange={(e) =>
                              updateInboundCallback(i, (current) => ({
                                ...current,
                                extract: {
                                  ...current.extract,
                                  error: e.target.value ? { source_path: e.target.value } : undefined,
                                },
                              }))
                            }
                            placeholder="callback.body.error"
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                  <button
                    type="button"
                    className="plugins-list-add-btn"
                    onClick={() =>
                      setRemoteDelegation((prev) => ({
                        ...prev,
                        callbacks: {
                          inbound: [...(prev.callbacks?.inbound ?? []), createInboundCallbackMapping()],
                        },
                      }))
                    }
                  >
                    + Add Inbound Callback Mapping
                  </button>
                </div>
              </>
            )}

            {/* Correlation config */}
            <div className="plugins-section-title" style={{ fontSize: '0.72rem', marginTop: 8 }}>Correlation</div>
            <div className="plugins-field-row">
              <div className="plugins-field">
                <label>Local ID Field</label>
                <input
                  type="text"
                  value={remoteDelegation.correlation?.local_id_field ?? 'usr_submission_id'}
                  onChange={(e) => setRemoteDelegation((prev) => ({
                    ...prev,
                    correlation: { ...prev.correlation, local_id_field: e.target.value },
                  }))}
                />
              </div>
              <div className="plugins-field">
                <label>Remote ID Field</label>
                <input
                  type="text"
                  value={remoteDelegation.correlation?.remote_id_field ?? 'remote_job_id'}
                  onChange={(e) => setRemoteDelegation((prev) => ({
                    ...prev,
                    correlation: { ...prev.correlation, remote_id_field: e.target.value },
                  }))}
                />
              </div>
              <div className="plugins-field">
                <label>Submitter ID Field</label>
                <input
                  type="text"
                  value={remoteDelegation.correlation?.submitter_id_field ?? 'submitted_by'}
                  onChange={(e) => setRemoteDelegation((prev) => ({
                    ...prev,
                    correlation: { ...prev.correlation, submitter_id_field: e.target.value },
                  }))}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Operational Policy section ── */}
      <div className="plugins-section">
        <div className="plugins-section-title">Operational Policy</div>
        <div className="plugins-field-row">
          <div className="plugins-field">
            <label>State Quota (bytes)</label>
            <input
              type="number"
              value={stateQuotaBytes}
              min={0}
              max={1048576}
              onChange={(e) => setStateQuotaBytes(Number(e.target.value))}
            />
          </div>
          <div className="plugins-field" style={{ justifyContent: 'flex-end' }}>
            <label className="plugins-cap-check">
              <input
                type="checkbox"
                checked={replayOnEnable}
                disabled
              />
              Replay on enable (reserved; not active yet)
            </label>
          </div>
        </div>
        <div className="plugins-field-row">
          <div className="plugins-field">
            <label>Allowed outbound domains</label>
            <input
              type="text"
              value={allowedOutboundDomains}
              onChange={(event) => setAllowedOutboundDomains(event.target.value)}
              placeholder="api.example.com, hooks.example.com"
            />
            <span className="plugins-field-hint">
              Optional comma-separated allowlist. Subdomains are included.
            </span>
          </div>
          <div className="plugins-field plugins-field--action">
            <label className="plugins-cap-check">
              <input
                type="checkbox"
                checked={allowPrivateNetworks}
                onChange={(event) => setAllowPrivateNetworks(event.target.checked)}
              />
              Allow private network targets
            </label>
            <label className="plugins-cap-check">
              <input
                type="checkbox"
                checked={allowInsecureHttp}
                onChange={(event) => setAllowInsecureHttp(event.target.checked)}
              />
              Allow cleartext HTTP / WS
            </label>
            <span className="plugins-field-hint">
              Private and cleartext access are separate opt-ins. Leave both off for public plugins.
            </span>
          </div>
        </div>
      </div>

      {/* ── form actions ── */}
      <div className="plugins-form-actions">
        <button type="button" className="plugins-cancel-btn" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="plugins-submit-btn" disabled={isCreating}>
          {isCreating ? 'Creating...' : 'Create Plugin'}
        </button>
      </div>
    </form>
  );
}
