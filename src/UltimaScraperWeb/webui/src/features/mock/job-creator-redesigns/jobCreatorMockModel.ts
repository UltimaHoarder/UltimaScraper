import { useState, useMemo } from 'react';
import type {
  JobTemplateResponse,
  TaskDefinition,
  TaskPayload,
  TemplateParameterPayload,
} from '../../../api/types/jobs';
import type { AuthCredential } from '../../../api/types/auths';

export type SupportedSite = 'OnlyFans' | 'Fansly' | 'LoyalFans';
export type CreatorMode = 'tasks' | 'template' | 'create_template';
export type NotificationType = 'success' | 'warning' | 'info' | 'error';
export type ScheduleType = 'interval' | 'once' | 'cron';
export type IntervalUnit = 'minutes' | 'hours' | 'days';

export const MOCK_TASK_TYPES: TaskDefinition[] = [
  {
    task_id: 'scrape_user',
    name: 'Scrape User Posts',
    category: 'metadata',
    description: 'Scrapes timeline posts, archived posts, stories, and highlights from creator profile.',
    keywords: ['scrape', 'posts', 'timeline'],
    parameters: [
      {
        name: 'site',
        label: 'Site',
        param_type: 'select',
        required: true,
        default: 'OnlyFans',
        description: 'Target platform',
        options: [
          { label: 'OnlyFans', value: 'OnlyFans' },
          { label: 'Fansly', value: 'Fansly' },
          { label: 'LoyalFans', value: 'LoyalFans' },
        ],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
      {
        name: 'username',
        label: 'Username',
        param_type: 'username',
        required: true,
        default: '',
        description: 'Creator handle to scrape',
        options: [],
        placeholder: 'e.g. luna_archive',
        min_value: null,
        max_value: null,
      },
      {
        name: 'content_types',
        label: 'Content Types',
        param_type: 'multiselect',
        required: true,
        default: ['Posts', 'Stories'],
        description: 'Sections of creator profile to query',
        options: [
          { label: 'Posts (Timeline)', value: 'Posts' },
          { label: 'Stories (24h)', value: 'Stories' },
          { label: 'Archived Posts', value: 'Archived' },
          { label: 'Highlights', value: 'Highlights' },
          { label: 'Messages / Chats', value: 'Messages' },
        ],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
      {
        name: 'overwrite',
        label: 'Overwrite Existing Files',
        param_type: 'boolean',
        required: false,
        default: false,
        description: 'Re-scrape and overwrite existing database records',
        options: [],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
    ],
  },
  {
    task_id: 'download_media',
    name: 'Download Media Files',
    category: 'download',
    description: 'Downloads photos, videos, and audio streams found in scraped posts into storage mounts.',
    keywords: ['download', 'media', 'photos', 'videos'],
    parameters: [
      {
        name: 'site',
        label: 'Site',
        param_type: 'select',
        required: true,
        default: 'OnlyFans',
        description: 'Target platform',
        options: [
          { label: 'OnlyFans', value: 'OnlyFans' },
          { label: 'Fansly', value: 'Fansly' },
          { label: 'LoyalFans', value: 'LoyalFans' },
        ],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
      {
        name: 'username',
        label: 'Username',
        param_type: 'username',
        required: true,
        default: '',
        description: 'Creator handle',
        options: [],
        placeholder: 'e.g. luna_archive',
        min_value: null,
        max_value: null,
      },
      {
        name: 'media_types',
        label: 'Media Types',
        param_type: 'multiselect',
        required: true,
        default: ['Photos', 'Videos'],
        description: 'Binary media streams to download',
        options: [
          { label: 'Photos (JPG/PNG)', value: 'Photos' },
          { label: 'Videos (MP4)', value: 'Videos' },
          { label: 'Audio / Voice Notes', value: 'Audio' },
          { label: 'Widevine DRM Encrypted', value: 'DRM' },
        ],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
      {
        name: 'skip_existing',
        label: 'Skip Existing Checksums',
        param_type: 'boolean',
        required: false,
        default: true,
        description: 'Skips files already present on disk with valid checksum',
        options: [],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
    ],
  },
  {
    task_id: 'scrape_paid_content',
    name: 'Scrape Paid & PPV Content',
    category: 'metadata',
    description: 'Queries subscriber purchase receipts, unlocked pay-per-view messages, and paid mass chats.',
    keywords: ['paid', 'ppv', 'messages', 'purchases'],
    parameters: [
      {
        name: 'site',
        label: 'Site',
        param_type: 'select',
        required: true,
        default: 'OnlyFans',
        description: 'Target platform',
        options: [
          { label: 'OnlyFans', value: 'OnlyFans' },
          { label: 'Fansly', value: 'Fansly' },
        ],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
      {
        name: 'username',
        label: 'Username',
        param_type: 'username',
        required: true,
        default: '',
        description: 'Creator handle',
        options: [],
        placeholder: 'e.g. luna_archive',
        min_value: null,
        max_value: null,
      },
    ],
  },
  {
    task_id: 'verify_checksums',
    name: 'Verify Media Checksums',
    category: 'integrity',
    description: 'Performs SHA-256 block hash audit against stored disk assets to detect bitrot or missing files.',
    keywords: ['verify', 'checksum', 'integrity', 'audit'],
    parameters: [
      {
        name: 'username',
        label: 'Username',
        param_type: 'username',
        required: true,
        default: '',
        description: 'Creator directory to verify',
        options: [],
        placeholder: 'e.g. luna_archive',
        min_value: null,
        max_value: null,
      },
      {
        name: 'repair_corrupt',
        label: 'Auto-Repair Corrupt Assets',
        param_type: 'boolean',
        required: false,
        default: true,
        description: 'Automatically re-downloads any corrupted media blocks',
        options: [],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
    ],
  },
];

export const INITIAL_TEMPLATES: JobTemplateResponse[] = [
  {
    template_id: 'tmpl-full-vault',
    name: 'Full Creator Vault Mirror',
    description: 'Complete archival mirror. Scrapes user timeline posts, stories, paid PPV messages, downloads all media assets, and registers checksums.',
    created_by: 'system',
    created_at: '2026-09-12T14:00:00Z',
    updated_at: '2026-10-18T09:30:00Z',
    default_priority: 50,
    job_name_template: 'Full Archival — {username}',
    parameters: [
      {
        name: 'username',
        type: 'username',
        required: true,
        default: null,
        description: 'Target performer handles',
        choices: null,
      },
      {
        name: 'content_types',
        type: 'multiselect',
        required: true,
        default: ['Posts', 'Stories', 'Messages', 'Paid'],
        description: 'Profile content types to mirror',
        choices: ['Posts', 'Stories', 'Messages', 'Paid', 'Archived'],
      },
      {
        name: 'media_types',
        type: 'multiselect',
        required: true,
        default: ['Photos', 'Videos'],
        description: 'Media streams to download',
        choices: ['Photos', 'Videos', 'Audio', 'DRM'],
      },
      {
        name: 'overwrite',
        type: 'bool',
        required: false,
        default: false,
        description: 'Overwrite existing files',
        choices: null,
      },
    ],
    tasks: [
      {
        name: 'Scrape Posts & Stories',
        task_type: 'scrape_user',
        site_name_template: '{site}',
        user_id_template: '{user_id}',
        content_type_template: 'Posts',
        payload_template: { content_types: ['Posts', 'Stories'] },
        capabilities: ['metadata'],
        depends_on: [],
        ip_lock_key_template: null,
        max_attempts: 3,
        dedupe_override: false,
      },
      {
        name: 'Scrape Paid Content',
        task_type: 'scrape_paid_content',
        site_name_template: '{site}',
        user_id_template: '{user_id}',
        content_type_template: 'Paid',
        payload_template: {},
        capabilities: ['metadata'],
        depends_on: ['Scrape Posts & Stories'],
        ip_lock_key_template: null,
        max_attempts: 3,
        dedupe_override: false,
      },
      {
        name: 'Download Media Files',
        task_type: 'download_media',
        site_name_template: '{site}',
        user_id_template: '{user_id}',
        content_type_template: 'Media',
        payload_template: { media_types: ['Photos', 'Videos'] },
        capabilities: ['download'],
        depends_on: ['Scrape Posts & Stories'],
        ip_lock_key_template: null,
        max_attempts: 3,
        dedupe_override: false,
      },
    ],
  },
  {
    template_id: 'tmpl-nightly-delta',
    name: 'Nightly Delta Catch-Up',
    description: 'Fast differential synchronization. Scrapes only new posts and stories from the last 24 hours without re-indexing existing assets.',
    created_by: 'operator_dan',
    created_at: '2026-10-02T18:20:00Z',
    updated_at: '2026-10-21T11:45:00Z',
    default_priority: 30,
    job_name_template: 'Nightly Delta — {username}',
    parameters: [
      {
        name: 'username',
        type: 'username',
        required: true,
        default: null,
        description: 'Performer handles',
        choices: null,
      },
      {
        name: 'content_types',
        type: 'multiselect',
        required: true,
        default: ['Posts', 'Stories'],
        description: 'Sections to check for updates',
        choices: ['Posts', 'Stories'],
      },
    ],
    tasks: [
      {
        name: 'Quick Delta Scrape',
        task_type: 'scrape_user',
        site_name_template: '{site}',
        user_id_template: '{user_id}',
        content_type_template: 'Posts',
        payload_template: { delta_only: true },
        capabilities: ['metadata'],
        depends_on: [],
        ip_lock_key_template: null,
        max_attempts: 2,
        dedupe_override: false,
      },
      {
        name: 'Download New Media',
        task_type: 'download_media',
        site_name_template: '{site}',
        user_id_template: '{user_id}',
        content_type_template: 'Media',
        payload_template: { skip_existing: true },
        capabilities: ['download'],
        depends_on: ['Quick Delta Scrape'],
        ip_lock_key_template: null,
        max_attempts: 3,
        dedupe_override: false,
      },
    ],
  },
  {
    template_id: 'tmpl-paid-recovery',
    name: 'Paid PPV & Order Backfill',
    description: 'Audits transaction purchases and unlocks paywalled media assets across authenticated accounts.',
    created_by: 'system',
    created_at: '2026-08-15T12:00:00Z',
    updated_at: '2026-10-15T14:10:00Z',
    default_priority: 60,
    job_name_template: 'PPV Backfill — {username}',
    parameters: [
      {
        name: 'username',
        type: 'username',
        required: true,
        default: null,
        description: 'Target performer',
        choices: null,
      },
    ],
    tasks: [
      {
        name: 'Query Purchase Receipts',
        task_type: 'scrape_paid_content',
        site_name_template: '{site}',
        user_id_template: '{user_id}',
        content_type_template: 'Paid',
        payload_template: {},
        capabilities: ['metadata'],
        depends_on: [],
        ip_lock_key_template: null,
        max_attempts: 3,
        dedupe_override: false,
      },
    ],
  },
];

/** A complete AuthCredential, so the mock stays in step with the API type. */
function mockAuth(id: number, site: string, user_id: number, username: string): AuthCredential {
  return {
    id,
    site,
    user_id,
    username,
    status: 'valid',
    active: true,
    last_tested_at: '2026-10-24T00:00:00Z',
    created_at: '2026-01-10T00:00:00Z',
    cookie_preview: null,
    has_authorization: true,
    user_agent_preview: null,
    proxy_id: null,
    worker_shard: null,
    is_age_verified: true,
    age_verification_required: false,
    spend: false,
    spender_type: null,
  };
}

export const MOCK_AUTHS: AuthCredential[] = [
  mockAuth(1, 'onlyfans', 104218, 'vip_operator_01'),
  mockAuth(2, 'onlyfans', 209514, 'indexer_bot_02'),
  mockAuth(3, 'fansly', 318490, 'fansly_master_01'),
  mockAuth(4, 'loyalfans', 489201, 'loyal_agent_01'),
];

/** What the concepts show of a subscription: a handle, a name, a site and when it started. */
export interface MockSubscription {
  id: number;
  user_id: number;
  username: string;
  name: string;
  site: string;
  is_active: boolean;
  subscribed_at: string;
}

export const MOCK_SUBSCRIPTIONS: MockSubscription[] = [
  { id: 1, user_id: 5001, username: 'luna_archive', name: 'Luna Valens (VIP)', site: 'onlyfans', is_active: true, subscribed_at: '2026-03-02' },
  { id: 2, user_id: 5002, username: 'sarah_sky', name: 'Sarah Sky', site: 'onlyfans', is_active: true, subscribed_at: '2026-05-19' },
  { id: 3, user_id: 5003, username: 'elena_raw', name: 'Elena Raw', site: 'fansly', is_active: true, subscribed_at: '2026-06-07' },
  { id: 4, user_id: 5004, username: 'mila_fox', name: 'Mila Fox', site: 'onlyfans', is_active: false, subscribed_at: '2025-11-30' },
  { id: 5, user_id: 5005, username: 'aurora_vip', name: 'Aurora Borealis', site: 'loyalfans', is_active: true, subscribed_at: '2026-08-14' },
];

export function useJobCreatorMockModel() {
  const [creatorMode, setCreatorMode] = useState<CreatorMode>('tasks');
  const [jobName, setJobName] = useState<string>('Creator Delta Archive');
  const [site, setSite] = useState<SupportedSite>('OnlyFans');
  const [selectedAuthId, setSelectedAuthId] = useState<number | 'all'>('all');

  // Task Builder State
  const [taskTypes] = useState<TaskDefinition[]>(MOCK_TASK_TYPES);
  const [selectedTaskType, setSelectedTaskType] = useState<string>('scrape_user');
  const [taskParams, setTaskParams] = useState<Record<string, unknown>>({
    site: 'OnlyFans',
    username: 'luna_archive',
    content_types: ['Posts', 'Stories'],
    overwrite: false,
  });
  const [tasks, setTasks] = useState<TaskPayload[]>([
    {
      task_type: 'scrape_user',
      params: { site: 'OnlyFans', username: 'luna_archive', content_types: ['Posts', 'Stories'], auth_id: 1 },
    },
    {
      task_type: 'download_media',
      params: { site: 'OnlyFans', username: 'luna_archive', media_types: ['Photos', 'Videos'], skip_existing: true, auth_id: 1 },
    },
  ]);

  // "Save as Template" within Task Builder
  const [saveAsTemplate, setSaveAsTemplate] = useState<boolean>(false);
  const [templateName, setTemplateName] = useState<string>('');
  const [templateDescription, setTemplateDescription] = useState<string>('');

  // Template Library State
  const [templates, setTemplates] = useState<JobTemplateResponse[]>(INITIAL_TEMPLATES);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('tmpl-full-vault');
  const [templateParams, setTemplateParams] = useState<Record<string, unknown>>({
    content_types: ['Posts', 'Stories', 'Messages'],
    media_types: ['Photos', 'Videos'],
    overwrite: false,
  });
  const [templateUsernames, setTemplateUsernames] = useState<string[]>(['luna_archive', 'sarah_sky']);

  // Dedicated "Create Template Studio" State
  const [authoringTemplateName, setAuthoringTemplateName] = useState<string>('Custom VIP Ingestion');
  const [authoringTemplateDesc, setAuthoringTemplateDesc] = useState<string>('User-defined template for VIP subscriptions');
  const [authoringTemplateParams, setAuthoringTemplateParams] = useState<TemplateParameterPayload[]>([
    { name: 'username', type: 'username', required: true, default: null, description: 'Performer handle', choices: null },
    { name: 'content_types', type: 'multiselect', required: true, default: ['Posts', 'Stories'], description: 'Sections to scrape', choices: ['Posts', 'Stories', 'Messages', 'Paid'] },
  ]);

  // Scheduling State
  const [scheduleEnabled, setScheduleEnabled] = useState<boolean>(false);
  const [scheduleType, setScheduleType] = useState<ScheduleType>('interval');
  const [scheduleAt, setScheduleAt] = useState<string>('2026-10-25T04:00');
  const [intervalValue, setIntervalValue] = useState<number>(6);
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>('hours');
  const [cronExpression, setCronExpression] = useState<string>('0 */6 * * *');
  const [startImmediately, setStartImmediately] = useState<boolean>(true);

  // Storage Space Policy
  const [ignoreSpaceRequirements, setIgnoreSpaceRequirements] = useState<boolean>(false);

  // Autocomplete / Search State
  const [usernameSearch, setUsernameSearch] = useState<string>('');
  const [showSuggestions, setShowSuggestions] = useState<boolean>(false);

  // Notification Toast
  const [notification, setNotification] = useState<{ message: string; type: NotificationType } | null>(null);

  const showNotification = (message: string, type: NotificationType = 'success') => {
    setNotification({ message, type });
    setTimeout(() => {
      setNotification((curr) => (curr?.message === message ? null : curr));
    }, 4500);
  };

  const selectedTaskDef = useMemo(
    () => taskTypes.find((t) => t.task_id === selectedTaskType) ?? taskTypes[0],
    [taskTypes, selectedTaskType]
  );

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.template_id === selectedTemplateId) ?? templates[0],
    [templates, selectedTemplateId]
  );

  const activeAuths = useMemo(
    () => MOCK_AUTHS.filter((a) => a.site.toLowerCase() === site.toLowerCase() && a.active),
    [site]
  );

  // Task Actions
  const handleTaskTypeChange = (taskId: string) => {
    setSelectedTaskType(taskId);
    const def = taskTypes.find((t) => t.task_id === taskId);
    if (!def) return;
    const defaults: Record<string, unknown> = {};
    for (const p of def.parameters) {
      if (p.default !== undefined && p.default !== null) {
        defaults[p.name] = p.default;
      }
    }
    setTaskParams(defaults);
  };

  const addTask = () => {
    const buildTask = (authId: number | undefined): TaskPayload => ({
      task_type: selectedTaskType,
      params: {
        ...taskParams,
        ...(authId !== undefined ? { auth_id: authId } : {}),
      },
    });

    if (selectedAuthId === 'all' && activeAuths.length > 0) {
      const fanOutTasks = activeAuths.map((a) => buildTask(a.id));
      setTasks((prev) => [...prev, ...fanOutTasks]);
      showNotification(`Added ${fanOutTasks.length} tasks across ${activeAuths.length} active auths`);
    } else {
      const singleTask = buildTask(typeof selectedAuthId === 'number' ? selectedAuthId : undefined);
      setTasks((prev) => [...prev, singleTask]);
      showNotification(`Added ${selectedTaskDef.name} to queue`);
    }

    if (!jobName.trim() && taskParams.username) {
      setJobName(`Scrape @${taskParams.username}`);
    }
  };

  const removeTask = (index: number) => {
    setTasks((prev) => prev.filter((_, idx) => idx !== index));
    showNotification('Removed task from queue', 'info');
  };

  const clearTasks = () => {
    setTasks([]);
    showNotification('Cleared all tasks from queue', 'info');
  };

  // Template Actions
  const selectTemplate = (templateId: string) => {
    setSelectedTemplateId(templateId);
    const tmpl = templates.find((t) => t.template_id === templateId);
    if (!tmpl) return;
    const defaults: Record<string, unknown> = {};
    for (const p of tmpl.parameters) {
      if (p.default !== undefined && p.default !== null) {
        defaults[p.name] = p.default;
      }
    }
    setTemplateParams(defaults);
    showNotification(`Loaded template: ${tmpl.name}`, 'info');
  };

  const addTemplateUsername = (handle: string) => {
    const clean = handle.replace(/^@/, '').trim();
    if (!clean) return;
    if (!templateUsernames.includes(clean)) {
      setTemplateUsernames((prev) => [...prev, clean]);
      showNotification(`Added @${clean} to template target list`);
    }
    setUsernameSearch('');
    setShowSuggestions(false);
  };

  const removeTemplateUsername = (handle: string) => {
    setTemplateUsernames((prev) => prev.filter((u) => u !== handle));
    showNotification(`Removed @${handle}`);
  };

  // Create New Template from scratch or from tasks
  const createNewTemplate = (
    name: string,
    description: string,
    sourceTasks: TaskPayload[] = tasks,
    customParams: TemplateParameterPayload[] = authoringTemplateParams
  ) => {
    if (!name.trim()) {
      showNotification('Template name is required', 'warning');
      return;
    }
    const newTmpl: JobTemplateResponse = {
      template_id: `tmpl-${Date.now()}`,
      name: name.trim(),
      description: description.trim() || 'User created template',
      created_by: 'operator',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      default_priority: 40,
      job_name_template: `${name} — {username}`,
      parameters: customParams,
      tasks: sourceTasks.map((t, idx) => ({
        name: `Task 0${idx + 1} (${t.task_type})`,
        task_type: t.task_type,
        site_name_template: '{site}',
        user_id_template: '{user_id}',
        content_type_template: String(t.params.content_type || 'Posts'),
        payload_template: { ...t.params },
        capabilities: ['metadata'],
        depends_on: idx > 0 ? [`Task 0${idx} (${sourceTasks[idx - 1].task_type})`] : [],
        ip_lock_key_template: null,
        max_attempts: 3,
        dedupe_override: false,
      })),
    };
    setTemplates((prev) => [newTmpl, ...prev]);
    setSelectedTemplateId(newTmpl.template_id);
    setSaveAsTemplate(false);
    showNotification(`Created template: "${name}" and saved to Template Library!`);
  };

  // Preview task calculations
  const previewTaskCount = useMemo(() => {
    const userCount = Math.max(templateUsernames.length, 1);
    const authCount = selectedAuthId === 'all' ? Math.max(activeAuths.length, 1) : 1;
    const taskCount = selectedTemplate?.tasks.length ?? 2;
    return userCount * authCount * taskCount;
  }, [templateUsernames.length, selectedAuthId, activeAuths.length, selectedTemplate]);

  const authsPerUsername = useMemo(() => {
    const result: Record<string, number[]> = {};
    for (const u of templateUsernames) {
      result[u] = selectedAuthId === 'all' ? activeAuths.map((a) => a.id) : typeof selectedAuthId === 'number' ? [selectedAuthId] : [1];
    }
    return result;
  }, [templateUsernames, selectedAuthId, activeAuths]);

  const resetAll = () => {
    setCreatorMode('tasks');
    setJobName('Creator Delta Archive');
    setSite('OnlyFans');
    setSelectedAuthId('all');
    setSelectedTaskType('scrape_user');
    setTasks([
      {
        task_type: 'scrape_user',
        params: { site: 'OnlyFans', username: 'luna_archive', content_types: ['Posts', 'Stories'], auth_id: 1 },
      },
      {
        task_type: 'download_media',
        params: { site: 'OnlyFans', username: 'luna_archive', media_types: ['Photos', 'Videos'], skip_existing: true, auth_id: 1 },
      },
    ]);
    setSaveAsTemplate(false);
    setTemplateName('');
    setTemplateDescription('');
    setSelectedTemplateId('tmpl-full-vault');
    setTemplateUsernames(['luna_archive', 'sarah_sky']);
    setScheduleEnabled(false);
    setScheduleType('interval');
    setIntervalValue(6);
    setIntervalUnit('hours');
    setIgnoreSpaceRequirements(false);
    showNotification('Reset preview to default state', 'info');
  };

  return {
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
    setTasks,
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
    authoringTemplateParams,
    setAuthoringTemplateParams,
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
    startImmediately,
    setStartImmediately,
    ignoreSpaceRequirements,
    setIgnoreSpaceRequirements,
    usernameSearch,
    setUsernameSearch,
    showSuggestions,
    setShowSuggestions,
    notification,
    showNotification,
    resetAll,
  };
}

export type JobCreatorMockModel = ReturnType<typeof useJobCreatorMockModel>;
