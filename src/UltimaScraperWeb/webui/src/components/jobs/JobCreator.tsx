/**
 * Job Creator component for creating new scraper jobs
 */

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getAuthList } from '../../api/auths';
import {
  createJob,
  getTaskTypes,
  instantiateTemplate,
  listTemplates,
} from '../../api/jobs';
import { getSubscriptions } from '../../api/subscriptions';
import type {
  CreateJobRequest,
  InstantiateTemplateRequest,
  TaskDefinition,
  TaskPayload,
  TemplateEntry,
} from '../../api/types/jobs';
import type { SubscriptionInfo } from '../../api/types/subscriptions';
import { JobCreatorDetailsSection } from '../../features/jobs/components/creator/JobCreatorDetailsSection';
import { JobCreatorFooter } from '../../features/jobs/components/creator/JobCreatorFooter';
import { JobCreatorScheduleSection } from '../../features/jobs/components/creator/JobCreatorScheduleSection';
import { JobCreatorTaskBuilderSection } from '../../features/jobs/components/creator/JobCreatorTaskBuilderSection';
import { JobCreatorTaskQueueSidebar } from '../../features/jobs/components/creator/JobCreatorTaskQueueSidebar';
import { JobCreatorTemplateBuilderSection } from '../../features/jobs/components/creator/JobCreatorTemplateBuilderSection';
import { JobCreatorTemplatePreviewSidebar } from '../../features/jobs/components/creator/JobCreatorTemplatePreviewSidebar';
import {
  parseAuthId,
  templateParamToTaskParam,
} from '../../features/jobs/lib/jobCreatorUtils';
import './JobCreator.css';

export interface JobCreatorChanges {
  tasksChanged: boolean;
  scheduleChanged: boolean;
}

interface JobCreatorProps {
  onJobCreated?: (jobId: string) => void;
  onCancel?: () => void;
  mode?: 'create' | 'edit';
  submitLabel?: string;
  initialJobName?: string;
  initialTasks?: TaskPayload[];
  initialSchedule?: {
    enabled: boolean;
    type: 'once' | 'interval' | 'cron';
    at?: string;
    intervalValue?: number;
    intervalUnit?: 'minutes' | 'hours' | 'days';
    cron?: string;
    startImmediately?: boolean;
  };
  onSubmit?: (payload: CreateJobRequest, changes: JobCreatorChanges) => Promise<unknown>;
}

function cloneParamValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return [...value];
  }
  if (value && typeof value === 'object') {
    return { ...(value as Record<string, unknown>) };
  }
  return value;
}

function getDefaultTaskParams(taskDef: TaskDefinition | undefined): Record<string, unknown> {
  if (!taskDef) {
    return {};
  }

  const defaults: Record<string, unknown> = {};
  for (const param of taskDef.parameters) {
    if (param.default !== null && param.default !== undefined) {
      defaults[param.name] = cloneParamValue(param.default);
    }
  }
  return defaults;
}

export function JobCreator({
  onJobCreated,
  onCancel,
  mode = 'create',
  submitLabel,
  initialJobName,
  initialTasks,
  initialSchedule,
  onSubmit,
}: JobCreatorProps) {
  const queryClient = useQueryClient();

  const initialSelectedAuthId =
    initialTasks
      ?.map((task) => parseAuthId(task.params.auth_id))
      .find((value): value is number => value !== null) ?? 'all';

  const [jobName, setJobName] = useState(initialJobName ?? '');
  const [selectedTaskType, setSelectedTaskType] = useState<string>('scrape_user');
  const [creatorMode, setCreatorMode] = useState<'tasks' | 'template'>('tasks');
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('');
  const [templateParams, setTemplateParams] = useState<Record<string, unknown>>({});
  const [templateUsernames, setTemplateUsernames] = useState<string[]>([]);
  const [taskParams, setTaskParams] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [tasks, setTasks] = useState<TaskPayload[]>(initialTasks ?? []);
  const [scheduleEnabled, setScheduleEnabled] = useState(initialSchedule?.enabled ?? false);
  const [scheduleType, setScheduleType] = useState<'once' | 'interval' | 'cron'>(
    initialSchedule?.type ?? 'interval'
  );
  const [scheduleAt, setScheduleAt] = useState(initialSchedule?.at ?? '');
  const [intervalValue, setIntervalValue] = useState(initialSchedule?.intervalValue ?? 1);
  const [intervalUnit, setIntervalUnit] = useState<'minutes' | 'hours' | 'days'>(
    initialSchedule?.intervalUnit ?? 'hours'
  );
  const [cronExpression, setCronExpression] = useState(initialSchedule?.cron ?? '');
  const [startImmediately, setStartImmediately] = useState(
    initialSchedule?.startImmediately ?? true
  );
  const scheduleSnapshot = () => JSON.stringify(
    !scheduleEnabled
      ? []
      : scheduleType === 'once'
        ? ['once', scheduleAt]
        : scheduleType === 'cron'
          ? ['cron', cronExpression.trim()]
          : ['interval', Number(intervalValue), intervalUnit, startImmediately],
  );
  // Capture the editor's starting state once. Background task updates can
  // refresh the props while the user is editing this snapshot.
  const [originalInput] = useState(() => ({ tasks, schedule: scheduleSnapshot() }));
  const missingRequiredTasks = tasks.length === 0
    && (mode !== 'edit' || originalInput.tasks.length > 0);
  const [saveAsTemplate, setSaveAsTemplate] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [templateDescription, setTemplateDescription] = useState('');
  const [ignoreSpaceRequirements, setIgnoreSpaceRequirements] = useState(true);
  const [selectedAuthId, setSelectedAuthId] = useState<number | 'all'>(initialSelectedAuthId);
  const [usernameSearch, setUsernameSearch] = useState('');
  const [showUsernameSuggestions, setShowUsernameSuggestions] = useState(false);
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const usernameInputRef = useRef<HTMLInputElement>(null);
  const suggestionsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(usernameSearch);
    }, 300);
    return () => clearTimeout(timer);
  }, [usernameSearch]);

  const currentSite =
    creatorMode === 'template'
      ? ((templateParams.site as string) || 'OnlyFans')
      : ((taskParams.site as string) || 'OnlyFans');
  const normalizedCurrentSite = currentSite.toLowerCase();

  const taskSupportsAuth =
    creatorMode === 'template' ||
    selectedTaskType === 'scrape_user' ||
    selectedTaskType === 'scrape_paid_content' ||
    selectedTaskType === 'download_media';

  const authIdFilter = typeof selectedAuthId === 'number' ? selectedAuthId : undefined;
  const { data: usernameSuggestions = [], isLoading: loadingUsernames } = useQuery({
    queryKey: ['username-suggestions', debouncedSearch, currentSite, authIdFilter],
    queryFn: async () => {
      if (!debouncedSearch || debouncedSearch.length < 2) return [];
      const response = await getSubscriptions(
        currentSite.toLowerCase(),
        debouncedSearch,
        false,
        authIdFilter,
        20,
        0
      );
      return response.subscriptions;
    },
    enabled: debouncedSearch.length >= 2 && showUsernameSuggestions,
    staleTime: 30000,
  });

  const { data: activeAuthResponse, isLoading: loadingAuths } = useQuery({
    queryKey: ['auths', 'active', normalizedCurrentSite],
    queryFn: () => getAuthList(normalizedCurrentSite, true),
    enabled: taskSupportsAuth,
    staleTime: 30000,
  });

  const activeAuths = activeAuthResponse?.auths ?? [];

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        suggestionsRef.current &&
        !suggestionsRef.current.contains(event.target as Node) &&
        usernameInputRef.current &&
        !usernameInputRef.current.contains(event.target as Node)
      ) {
        setShowUsernameSuggestions(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const { data: templates = [] } = useQuery({
    queryKey: ['job-templates'],
    queryFn: listTemplates,
    staleTime: 60000,
  });
  const selectedTemplate = templates.find((template) => template.template_id === selectedTemplateId) ?? null;
  const templateUsesUsernameParam =
    selectedTemplate?.parameters.some((param) => param.name === 'username') ?? false;

  const { data: taskTypes = [], isLoading: loadingTaskTypes } = useQuery({
    queryKey: ['task-types'],
    queryFn: getTaskTypes,
  });
  const selectedTaskDef = taskTypes.find((task) => task.task_id === selectedTaskType);

  const previewSite = ((templateParams.site as string) || 'OnlyFans').toLowerCase();
  const { data: authsPerUsername, isFetching: checkingSubData } = useQuery({
    queryKey: ['template-auth-check', previewSite, templateUsernames, activeAuths.map((auth) => auth.id)],
    queryFn: async (): Promise<Record<string, number[]>> => {
      const result: Record<string, number[]> = {};
      await Promise.all(
        templateUsernames.map(async (username) => {
          const checks = await Promise.all(
            activeAuths.map(async (auth) => {
              const response = await getSubscriptions(
                previewSite,
                username,
                false,
                auth.id,
                1,
                0
              );
              return response.total > 0 ? auth.id : null;
            })
          );
          result[username] = checks.filter((id): id is number => id !== null);
        })
      );
      return result;
    },
    enabled:
      creatorMode === 'template' &&
      templateUsesUsernameParam &&
      selectedAuthId === 'all' &&
      templateUsernames.length > 0 &&
      activeAuths.length > 0,
    staleTime: 30000,
  });

  const previewTaskCount = (() => {
    if (!selectedTemplate) return 0;
    const selectedContentTypes = Array.isArray(templateParams.content_types)
      ? (templateParams.content_types as string[])
      : null;
    const visibleTasks = selectedTemplate.tasks.filter((task) => {
      if (selectedContentTypes && !selectedContentTypes.includes(task.content_type_template)) {
        return false;
      }
      return true;
    });
    const visibleTaskCount = visibleTasks.length;
    const usernameMultiplier = templateUsesUsernameParam ? Math.max(templateUsernames.length, 1) : 1;

    if (selectedAuthId !== 'all' || !authsPerUsername || !templateUsesUsernameParam) {
      return (
        visibleTaskCount *
        usernameMultiplier *
        (selectedAuthId === 'all' ? Math.max(activeAuths.length, 1) : 1)
      );
    }

    const totalAuthJobs = templateUsernames.reduce(
      (sum, username) => sum + (authsPerUsername[username]?.length ?? 0),
      0
    );
    return visibleTaskCount * totalAuthJobs;
  })();

  const submitJobMutation = useMutation({
    mutationFn: async () => {
      if (creatorMode === 'tasks' && !jobName.trim()) {
        throw new Error('Job name is required');
      }

      if (creatorMode === 'template') {
        if (!selectedTemplateId) throw new Error('Please select a template');
        if (templateUsesUsernameParam && templateUsernames.length === 0) {
          throw new Error('Add at least one username');
        }
        if (selectedTemplate) {
          for (const param of selectedTemplate.parameters) {
            if (param.name === 'username') continue;
            const value = templateParams[param.name];
            if (
              param.required &&
              (value === undefined ||
                value === null ||
                value === '' ||
                (Array.isArray(value) && value.length === 0))
            ) {
              throw new Error(
                `${param.name.charAt(0).toUpperCase() + param.name.slice(1)} is required`
              );
            }
          }
        }

        let templateSchedule:
          | {
              scheduled_for?: string;
              interval_seconds?: number;
              cron?: string;
              start_immediately?: boolean;
            }
          | undefined;
        if (scheduleEnabled) {
          if (scheduleType === 'once') {
            if (!scheduleAt) throw new Error('Schedule time is required for a one-time job');
            const scheduledDate = new Date(scheduleAt);
            if (Number.isNaN(scheduledDate.getTime())) throw new Error('Schedule time is invalid');
            templateSchedule = { scheduled_for: scheduledDate.toISOString() };
          } else if (scheduleType === 'interval') {
            const interval = Number(intervalValue);
            if (!Number.isFinite(interval) || interval <= 0) {
              throw new Error('Interval must be greater than 0');
            }
            const unitSeconds =
              intervalUnit === 'days' ? 86400 : intervalUnit === 'hours' ? 3600 : 60;
            templateSchedule = {
              interval_seconds: Math.round(interval * unitSeconds),
              start_immediately: startImmediately,
            };
          } else {
            const cron = cronExpression.trim();
            if (!cron) throw new Error('Cron expression is required');
            templateSchedule = { cron };
          }
        }

        const authId = selectedAuthId !== 'all' ? selectedAuthId : undefined;
        const site = ((templateParams.site as string) || 'OnlyFans').toLowerCase();
        const effectiveJobName =
          jobName.trim() ||
          (selectedTemplate
            ? [
                selectedTemplate.name,
                ...templateUsernames.slice(0, 2),
                ...(templateUsernames.length > 2
                  ? [`+${templateUsernames.length - 2} more`]
                  : []),
              ].join(' — ')
            : 'Template Job');

        const batchEntries: TemplateEntry[] = [];
        if (templateUsesUsernameParam) {
          for (const username of templateUsernames) {
            let qualifyingAuths: typeof activeAuths;
            if (selectedAuthId === 'all') {
              const checks = await Promise.all(
                activeAuths.map(async (auth) => {
                  const response = await getSubscriptions(
                    site,
                    username,
                    false,
                    auth.id,
                    1,
                    0
                  );
                  return response.total > 0 ? auth : null;
                })
              );
              qualifyingAuths = checks.filter((auth): auth is typeof activeAuths[number] => auth !== null);
            } else {
              const match = activeAuths.find((auth) => auth.id === authId);
              qualifyingAuths = match ? [match] : [];
            }

            for (const auth of qualifyingAuths) {
              batchEntries.push({ username, auth_id: auth.user_id });
            }
          }
        } else {
          const qualifyingAuths =
            selectedAuthId === 'all'
              ? activeAuths
              : activeAuths.filter((auth) => auth.id === authId);
          for (const auth of qualifyingAuths) {
            batchEntries.push({
              username: auth.username || `auth-${auth.user_id}`,
              auth_id: auth.user_id,
            });
          }
        }

        if (batchEntries.length === 0) {
          throw new Error(
            templateUsesUsernameParam
              ? 'None of the selected performers have any subscription history on any active auth.'
              : 'No active auths are available for this template.'
          );
        }

        const request: InstantiateTemplateRequest = {
          parameter_values: { ...templateParams },
          job_name: effectiveJobName,
          created_by: 'webui',
          entries: batchEntries,
          schedule: templateSchedule,
          ignore_space_requirements: ignoreSpaceRequirements,
        };
        return instantiateTemplate(selectedTemplateId, request);
      }

      if (missingRequiredTasks) {
        throw new Error('At least one task is required');
      }

      const trimmedTemplateName = templateName.trim() || jobName.trim();
      if (mode === 'create' && saveAsTemplate && !trimmedTemplateName) {
        throw new Error('Template name is required when saving as a template');
      }

      let schedule:
        | {
            scheduled_for?: string;
            interval_seconds?: number;
            cron?: string;
            start_immediately?: boolean;
          }
        | undefined;
      if (scheduleEnabled) {
        if (scheduleType === 'once') {
          if (!scheduleAt) {
            throw new Error('Schedule time is required for a one-time job');
          }
          const scheduledDate = new Date(scheduleAt);
          if (Number.isNaN(scheduledDate.getTime())) {
            throw new Error('Schedule time is invalid');
          }
          schedule = { scheduled_for: scheduledDate.toISOString() };
        } else if (scheduleType === 'interval') {
          const interval = Number(intervalValue);
          if (!Number.isFinite(interval) || interval <= 0) {
            throw new Error('Interval must be greater than 0');
          }
          const unitSeconds =
            intervalUnit === 'days' ? 86400 : intervalUnit === 'hours' ? 3600 : 60;
          schedule = {
            interval_seconds: Math.round(interval * unitSeconds),
            start_immediately: startImmediately,
          };
        } else {
          const cron = cronExpression.trim();
          if (!cron) {
            throw new Error('Cron expression is required');
          }
          schedule = { cron };
        }
      }

      const request: CreateJobRequest = {
        job_name: jobName,
        tasks,
        created_by: 'webui',
        schedule,
        ignore_space_requirements: ignoreSpaceRequirements,
      };

      if (mode === 'create' && saveAsTemplate) {
        request.save_as_template = true;
        request.template_name = trimmedTemplateName;
        const trimmedDescription = templateDescription.trim();
        if (trimmedDescription) {
          request.template_description = trimmedDescription;
        }
      }

      if (onSubmit) {
        return onSubmit(request, {
          tasksChanged: JSON.stringify(tasks) !== JSON.stringify(originalInput.tasks),
          scheduleChanged: scheduleSnapshot() !== originalInput.schedule,
        });
      }
      return createJob(request);
    },
    onSuccess: (job) => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
      if (job && typeof job === 'object' && 'job_id' in job) {
        onJobCreated?.(String((job as { job_id?: string }).job_id));
      } else {
        onJobCreated?.('');
      }
      setJobName('');
      setTasks([]);
      setTaskParams({});
      setTemplateParams({});
      setTemplateUsernames([]);
      setUsernameSearch('');
      setSelectedTemplateId('');
      setSaveAsTemplate(false);
      setTemplateName('');
      setTemplateDescription('');
      setStartImmediately(false);
      setError(null);
    },
    onError: (mutationError: unknown) => {
      const axiosError = mutationError as {
        response?: { data?: { detail?: string } };
        message?: string;
      };
      const detail = axiosError?.response?.data?.detail ?? axiosError?.message ?? String(mutationError);
      setError(detail);
    },
  });

  const handleTaskTypeChange = (taskId: string) => {
    setSelectedTaskType(taskId);
    const taskDef = taskTypes.find((task) => task.task_id === taskId);
    if (!taskDef) return;

    const defaults = getDefaultTaskParams(taskDef);

    const supportsAuth =
      taskId === 'scrape_user' ||
      taskId === 'scrape_paid_content' ||
      taskId === 'download_media';
    if (supportsAuth && selectedAuthId !== 'all') {
      defaults.auth_id = selectedAuthId;
    }

    setTaskParams(defaults);
  };

  const handleTemplateSelect = (templateId: string) => {
    setSelectedTemplateId(templateId);
    const template = templates.find((entry) => entry.template_id === templateId);

    if (!template) {
      setTemplateParams({});
      setTemplateUsernames([]);
      setUsernameSearch('');
      return;
    }

    const defaults: Record<string, unknown> = {};
    for (const param of template.parameters) {
      if (param.name === 'username') continue;
      if (param.default !== null && param.default !== undefined) {
        defaults[param.name] = param.default;
      }
    }

    setTemplateParams(defaults);
    setTemplateUsernames([]);
    setUsernameSearch('');
  };

  const handleParamChange = (paramName: string, value: unknown) => {
    setTaskParams((previous) => ({ ...previous, [paramName]: value }));
  };

  const handleTemplateParamChange = (paramName: string, value: unknown) => {
    setTemplateParams((previous) => ({ ...previous, [paramName]: value }));
  };

  const addTemplateUsername = (username: string) => {
    const trimmed = username.trim();
    if (!trimmed) return;
    setTemplateUsernames((previous) =>
      previous.includes(trimmed) ? previous : [...previous, trimmed]
    );
    setUsernameSearch('');
  };

  const removeTemplateUsername = (username: string) => {
    setTemplateUsernames((previous) => previous.filter((entry) => entry !== username));
  };

  const handleUsernameSelect = (
    subscription: SubscriptionInfo,
    onChangeParam = handleParamChange
  ) => {
    onChangeParam('username', subscription.username ?? '');
    setUsernameSearch(subscription.username ?? '');
    setShowUsernameSuggestions(false);
  };

  const handleTemplateSuggestionSelect = (subscription: SubscriptionInfo) => {
    addTemplateUsername(subscription.username ?? '');
    setShowUsernameSuggestions(false);
  };

  const handleTemplateUsernameSearchChange = (value: string) => {
    setUsernameSearch(value);
    setShowUsernameSuggestions(true);
  };

  const handleTemplateUsernameFocus = () => {
    if (usernameSearch.length >= 2) {
      setShowUsernameSuggestions(true);
    }
  };

  const handleTemplateUsernameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && usernameSearch.trim()) {
      event.preventDefault();
      addTemplateUsername(usernameSearch.trim());
    }
  };

  const handleSaveAsTemplateChange = (checked: boolean) => {
    setSaveAsTemplate(checked);
    if (checked && !templateName.trim()) {
      setTemplateName(jobName);
    }
  };

  const handleAddTask = () => {
    if (!selectedTaskDef) return;

    for (const param of selectedTaskDef.parameters) {
      const value = taskParams[param.name] ?? param.default;
      if (param.required && !value) {
        setError(`${param.label} is required`);
        return;
      }
    }

    const buildTask = (authId: number | undefined): TaskPayload => {
      const params: Record<string, unknown> = {
        ...getDefaultTaskParams(selectedTaskDef),
        ...taskParams,
      };
      if (taskSupportsAuth) {
        if (authId !== undefined) {
          params.auth_id = authId;
        } else {
          delete params.auth_id;
        }
      }
      return { task_type: selectedTaskType, params };
    };

    if (selectedAuthId === 'all' && activeAuths.length > 0) {
      setTasks((previous) => [
        ...previous,
        ...activeAuths.map((auth) => buildTask(auth.id)),
      ]);
    } else {
      const resolvedAuthId = selectedAuthId !== 'all' ? selectedAuthId : undefined;
      setTasks((previous) => [...previous, buildTask(resolvedAuthId)]);
    }

    setError(null);
    if (!jobName && taskParams.username) {
      setJobName(`Scrape ${taskParams.username}`);
    }
  };

  const handleRemoveTask = (index: number) => {
    setTasks((previous) => previous.filter((_, taskIndex) => taskIndex !== index));
  };

  const renderParamInput = (
    param: TaskDefinition['parameters'][0],
    paramValues: Record<string, unknown> = taskParams,
    onChangeParam: (name: string, value: unknown) => void = handleParamChange
  ) => {
    const value = paramValues[param.name] ?? param.default ?? '';

    switch (param.param_type) {
      case 'select':
        return (
          <select
            value={String(value)}
            onChange={(event) => onChangeParam(param.name, event.target.value)}
            className="field-select"
          >
            {param.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        );

      case 'multiselect': {
        const selectedValues = Array.isArray(value) ? value : [];
        return (
          <div className="field-multiselect">
            {param.options.map((option) => (
              <label key={option.value} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={selectedValues.includes(option.value)}
                  onChange={(event) => {
                    const newValues = event.target.checked
                      ? [...selectedValues, option.value]
                      : selectedValues.filter((selected: string) => selected !== option.value);
                    onChangeParam(param.name, newValues);
                  }}
                  className="field-checkbox"
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        );
      }

      case 'boolean':
        return (
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={Boolean(value)}
              onChange={(event) => onChangeParam(param.name, event.target.checked)}
              className="field-checkbox"
            />
            <span>{param.label}</span>
          </label>
        );

      case 'number':
        return (
          <input
            type="number"
            value={value !== null && value !== undefined ? String(value) : ''}
            onChange={(event) =>
              onChangeParam(param.name, event.target.value ? Number(event.target.value) : null)
            }
            placeholder={param.placeholder}
            min={param.min_value ?? undefined}
            max={param.max_value ?? undefined}
            className="field-input"
          />
        );

      case 'username':
        return (
          <div className="username-autocomplete">
            <input
              ref={usernameInputRef}
              type="text"
              value={usernameSearch || String(value)}
              onChange={(event) => {
                const nextValue = event.target.value;
                setUsernameSearch(nextValue);
                onChangeParam(param.name, nextValue);
                setShowUsernameSuggestions(true);
              }}
              onFocus={() => {
                if (usernameSearch.length >= 2 || String(value).length >= 2) {
                  setShowUsernameSuggestions(true);
                }
              }}
              placeholder={param.placeholder || 'Start typing to search...'}
              className="field-input"
              autoComplete="off"
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
                      onClick={() => handleUsernameSelect(subscription, onChangeParam)}
                    >
                      <span className="suggestion-username">{subscription.username}</span>
                      {subscription.name && subscription.name !== subscription.username && (
                        <span className="suggestion-name">{subscription.name}</span>
                      )}
                      <span className="suggestion-site">{subscription.site}</span>
                    </div>
                  ))
                ) : debouncedSearch.length >= 2 ? (
                  <div className="suggestion-empty">
                    No matches found. You can still type a username manually.
                  </div>
                ) : null}
              </div>
            )}
          </div>
        );

      case 'text':
      default:
        return (
          <input
            type="text"
            value={String(value)}
            onChange={(event) => onChangeParam(param.name, event.target.value)}
            placeholder={param.placeholder}
            className="field-input"
          />
        );
    }
  };

  if (loadingTaskTypes) {
    return (
      <div className="job-creator">
        <div className="loading-state">
          <div className="spinner" />
          <p>Loading task types...</p>
        </div>
      </div>
    );
  }

  const isSubmitDisabled =
    submitJobMutation.isPending ||
    (creatorMode === 'tasks'
      ? !jobName.trim() || missingRequiredTasks
      : !selectedTemplateId || (templateUsesUsernameParam && templateUsernames.length === 0));

  return (
    <div className="job-creator">
      <div className="creator-header">
        <div>
          <h2>{mode === 'edit' ? 'Edit Job' : 'Create New Job'}</h2>
          <p className="creator-subtitle">
            {mode === 'edit'
              ? 'Update the job configuration and schedule'
              : 'Configure and schedule a new scraping job'}
          </p>
        </div>
        {onCancel && (
          <button className="btn-close" onClick={onCancel} title="Close">
            ×
          </button>
        )}
      </div>

      {error && (
        <div className="alert alert-error">
          <span className="alert-icon">⚠️</span>
          <span className="alert-message">{error}</span>
          <button className="alert-close" onClick={() => setError(null)}>
            ×
          </button>
        </div>
      )}

      <div className="creator-mode-toggle">
        <button
          className={`mode-btn${creatorMode === 'tasks' ? ' mode-btn--active' : ''}`}
          onClick={() => setCreatorMode('tasks')}
          type="button"
        >
          Build from Tasks
        </button>
        <button
          className={`mode-btn${creatorMode === 'template' ? ' mode-btn--active' : ''}`}
          onClick={() => setCreatorMode('template')}
          type="button"
        >
          Use Template
        </button>
      </div>

      <div className="creator-body">
        <div className="creator-grid">
          <div className="creator-main">
            <JobCreatorDetailsSection
              creatorMode={creatorMode}
              mode={mode}
              jobName={jobName}
              onJobNameChange={setJobName}
              saveAsTemplate={saveAsTemplate}
              onSaveAsTemplateChange={handleSaveAsTemplateChange}
              templateName={templateName}
              onTemplateNameChange={setTemplateName}
              templateDescription={templateDescription}
              onTemplateDescriptionChange={setTemplateDescription}
              selectedTemplateName={selectedTemplate?.name ?? null}
              templateUsernames={templateUsernames}
            />

            <JobCreatorScheduleSection
              scheduleEnabled={scheduleEnabled}
              onScheduleEnabledChange={setScheduleEnabled}
              scheduleType={scheduleType}
              onScheduleTypeChange={setScheduleType}
              scheduleAt={scheduleAt}
              onScheduleAtChange={setScheduleAt}
              intervalValue={intervalValue}
              onIntervalValueChange={setIntervalValue}
              intervalUnit={intervalUnit}
              onIntervalUnitChange={setIntervalUnit}
              startImmediately={startImmediately}
              onStartImmediatelyChange={setStartImmediately}
              cronExpression={cronExpression}
              onCronExpressionChange={setCronExpression}
            />

            <section className="creator-section">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={ignoreSpaceRequirements}
                  onChange={(event) => setIgnoreSpaceRequirements(event.target.checked)}
                  className="field-checkbox"
                />
                <span>Ignore storage space checks</span>
              </label>
            </section>

            {creatorMode === 'tasks' && (
              <JobCreatorTaskBuilderSection
                taskTypes={taskTypes}
                selectedTaskType={selectedTaskType}
                onTaskTypeChange={handleTaskTypeChange}
                selectedTaskDef={selectedTaskDef}
                taskSupportsAuth={taskSupportsAuth}
                selectedAuthId={selectedAuthId}
                onSelectedAuthIdChange={setSelectedAuthId}
                activeAuths={activeAuths}
                loadingAuths={loadingAuths}
                currentSite={currentSite}
                renderParamInput={renderParamInput}
                onAddTask={handleAddTask}
              />
            )}

            {creatorMode === 'template' && (
              <JobCreatorTemplateBuilderSection
                selectedTemplateId={selectedTemplateId}
                templates={templates}
                selectedTemplate={selectedTemplate}
                onTemplateSelect={handleTemplateSelect}
                taskSupportsAuth={taskSupportsAuth}
                selectedAuthId={selectedAuthId}
                onSelectedAuthIdChange={setSelectedAuthId}
                activeAuths={activeAuths}
                loadingAuths={loadingAuths}
                currentSite={currentSite}
                templateUsesUsernameParam={templateUsesUsernameParam}
                templateUsernames={templateUsernames}
                onRemoveTemplateUsername={removeTemplateUsername}
                usernameSearch={usernameSearch}
                onUsernameSearchChange={handleTemplateUsernameSearchChange}
                onUsernameFocus={handleTemplateUsernameFocus}
                onUsernameKeyDown={handleTemplateUsernameKeyDown}
                showUsernameSuggestions={showUsernameSuggestions}
                loadingUsernames={loadingUsernames}
                usernameSuggestions={usernameSuggestions}
                debouncedSearch={debouncedSearch}
                onSuggestionSelect={handleTemplateSuggestionSelect}
                usernameInputRef={usernameInputRef}
                suggestionsRef={suggestionsRef}
                templateParams={templateParams}
                onTemplateParamChange={handleTemplateParamChange}
                templateParamToTaskParam={templateParamToTaskParam}
                renderParamInput={renderParamInput}
              />
            )}
          </div>

          {creatorMode === 'tasks' && (
            <JobCreatorTaskQueueSidebar tasks={tasks} onRemoveTask={handleRemoveTask} />
          )}

          {creatorMode === 'template' && selectedTemplate && (
            <JobCreatorTemplatePreviewSidebar
              selectedTemplate={selectedTemplate}
              templateUsesUsernameParam={templateUsesUsernameParam}
              templateUsernames={templateUsernames}
              checkingSubData={checkingSubData}
              previewTaskCount={previewTaskCount}
              selectedAuthId={selectedAuthId}
              authsPerUsername={authsPerUsername}
              activeAuths={activeAuths}
              templateParams={templateParams}
            />
          )}
        </div>
      </div>

      <JobCreatorFooter
        creatorMode={creatorMode}
        selectedTemplateId={selectedTemplateId}
        selectedTemplateName={selectedTemplate?.name ?? null}
        templateUsesUsernameParam={templateUsesUsernameParam}
        templateUsernames={templateUsernames}
        selectedAuthId={selectedAuthId}
        activeAuthCount={activeAuths.length}
        taskCount={tasks.length}
        onCancel={onCancel}
        onSubmit={() => submitJobMutation.mutate()}
        isSubmitting={submitJobMutation.isPending}
        isSubmitDisabled={isSubmitDisabled}
        submitLabel={submitLabel}
        mode={mode}
      />
    </div>
  );
}
