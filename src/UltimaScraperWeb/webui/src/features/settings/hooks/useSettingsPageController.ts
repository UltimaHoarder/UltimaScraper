import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  deleteBackendInventory,
  deleteDbSetting,
  getSettings,
  listBackendInventory,
  listDbSettings,
  patchBackendInventory,
  patchDbSetting,
  testSettingsRedisConnection,
  updateSettings,
  upsertBackendInventory,
  upsertDbSetting,
} from '../../../api/settings';
import type {
  BackendInventoryRecord,
  DBSettingRecord,
  SettingsConflictDetail,
  SettingsResponse,
  SettingsUpdate,
  TestRedisConnectionResponse,
} from '../../../api/types/settings';
import {
  RESERVED_CONFLICT_FIELDS,
  buildConflictLeafEntries,
  type ConflictLeafEntry,
  type ConflictModalState,
  type MergeChoice,
  type SettingsTab,
  type TopLevelSettingsKey,
  deepClone,
  isPlainObject,
  mergePlainObjects,
  setNestedObjectValue,
} from '../lib/settingsUtils';

type DbMessage = { type: 'success' | 'error'; text: string } | null;

type DbEditorState = {
  backend: string;
  key: string;
  value: string;
  description: string;
  isSecret: boolean;
};

type InventoryEditorState = {
  backendName: string;
  hostname: string;
  localIp: string;
  settingsId: string;
};

const createEmptyDbEditor = (): DbEditorState => ({
  backend: '',
  key: '',
  value: '',
  description: '',
  isSecret: false,
});

const createEmptyInventoryEditor = (): InventoryEditorState => ({
  backendName: '',
  hostname: '',
  localIp: '',
  settingsId: '',
});

export function useSettingsPageController() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [editedSettings, setEditedSettings] = useState<
    Partial<SettingsResponse> & Record<string, unknown>
  >({});
  const [hasChanges, setHasChanges] = useState(false);
  const [isTestingRedis, setIsTestingRedis] = useState(false);
  const [redisTestResult, setRedisTestResult] =
    useState<TestRedisConnectionResponse | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [conflictState, setConflictState] = useState<ConflictModalState | null>(null);
  const [conflictChoices, setConflictChoices] = useState<Record<string, MergeChoice>>({});
  const [conflictSaveError, setConflictSaveError] = useState<string | null>(null);
  const [dbMessage, setDbMessage] = useState<DbMessage>(null);
  const [selectedDbSettingId, setSelectedDbSettingId] = useState<number | null>(null);
  const [dbEditor, setDbEditor] = useState<DbEditorState>(createEmptyDbEditor);
  const [selectedInventoryId, setSelectedInventoryId] = useState<number | null>(null);
  const [inventoryEditor, setInventoryEditor] = useState<InventoryEditorState>(
    createEmptyInventoryEditor,
  );

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  });

  const dbSettingsQuery = useQuery({
    queryKey: ['settings', 'db-rows'],
    queryFn: () => listDbSettings({ include_secrets: true }),
    enabled: activeTab === 'database',
  });

  const backendInventoryQuery = useQuery({
    queryKey: ['settings', 'backend-inventory'],
    queryFn: () => listBackendInventory(),
    enabled: activeTab === 'database',
  });

  const updateMutation = useMutation({
    mutationFn: (updates: SettingsUpdate) => updateSettings(updates),
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated);
      void queryClient.invalidateQueries({ queryKey: ['settings'] });
      void queryClient.invalidateQueries({ queryKey: ['system', 'backend'] });
      void queryClient.invalidateQueries({ queryKey: ['system', 'all-backends'] });
      setHasChanges(false);
      setEditedSettings({});
      setConflictState(null);
      setConflictChoices({});
      setConflictSaveError(null);
    },
  });

  const settings = settingsQuery.data;
  const dbSettings = dbSettingsQuery.data;
  const backendInventory = backendInventoryQuery.data;

  const handleChange = (key: TopLevelSettingsKey, value: unknown) => {
    setEditedSettings((previous) => ({ ...previous, [key]: value as never }));
    setHasChanges(true);
  };

  const handleNestedChange = (section: string, key: string, value: unknown) => {
    setEditedSettings((previous) => {
      const currentSection = previous[section as keyof SettingsResponse];
      const sectionData = {
        ...((currentSection as Record<string, unknown> | undefined) || {}),
        [key]: value,
      };
      let nextSettings = { ...previous, [section]: sectionData };

      if (section === 'redis' && key === 'enabled' && value === false) {
        const currentBackend = nextSettings.backend as Record<string, unknown> | undefined;
        nextSettings = {
          ...nextSettings,
          backend: {
            backend_id:
              (currentBackend?.backend_id as string | null | undefined) ??
              settings?.backend?.backend_id ??
              null,
            ...(currentBackend || {}),
            execution_mode: 'local',
          },
        };
      }

      return nextSettings;
    });
    setHasChanges(true);
    if (section === 'redis') {
      setRedisTestResult(null);
    }
  };

  const handleDeepNestedChange = (
    section: string,
    subsection: string,
    key: string,
    value: unknown,
  ) => {
    setEditedSettings((previous) => {
      const baseSection = settings?.[section as keyof SettingsResponse] as
        | Record<string, unknown>
        | undefined;
      const editedSection = previous[section as keyof SettingsResponse] as
        | Record<string, unknown>
        | undefined;
      const currentSection = { ...(baseSection || {}), ...(editedSection || {}) };
      const currentSubsection = {
        ...((currentSection[subsection] as Record<string, unknown> | undefined) || {}),
      };
      const updatedSubsection = { ...currentSubsection, [key]: value };
      return {
        ...previous,
        [section]: {
          ...currentSection,
          [subsection]: updatedSubsection,
        },
      };
    });
    setHasChanges(true);
  };

  const handleSave = async () => {
    if (!settings) return;

    setIsSaving(true);
    setRedisTestResult(null);

    try {
      const redisChanged = 'redis' in editedSettings;
      const editedRedis = editedSettings.redis as
        | { enabled?: boolean; host?: string; port?: number; db?: number; password?: string | null }
        | undefined;
      const redisEnabled = editedRedis?.enabled ?? settings.redis.enabled;
      const redisPassword = editedRedis && Object.prototype.hasOwnProperty.call(editedRedis, 'password')
        ? editedRedis.password ?? null
        : settings.redis.password;

      if (redisChanged && redisEnabled) {
        setIsTestingRedis(true);

        const testResult = await testSettingsRedisConnection({
          host: editedRedis?.host ?? settings.redis.host,
          port: editedRedis?.port ?? settings.redis.port,
          db: editedRedis?.db ?? settings.redis.db,
          password: redisPassword,
        });
        setRedisTestResult(testResult);
        setIsTestingRedis(false);

        if (!testResult.success) {
          setIsSaving(false);
          return;
        }
      }

      const payload: SettingsUpdate = {
        ...(editedSettings as SettingsUpdate),
      };

      for (const [key, value] of Object.entries(editedSettings)) {
        const currentValue = settings[key as keyof SettingsResponse];
        if (isPlainObject(value) && isPlainObject(currentValue)) {
          (payload as Record<string, unknown>)[key] = mergePlainObjects(currentValue, value);
        }
      }

      if (isPlainObject(payload.network)) {
        const rawTimeout = (payload.network as Record<string, unknown>).guest_lookup_timeout;
        if (rawTimeout !== undefined && rawTimeout !== null) {
          const parsed = typeof rawTimeout === 'number' ? rawTimeout : parseFloat(String(rawTimeout));
          (payload.network as Record<string, unknown>).guest_lookup_timeout =
            Number.isNaN(parsed) || parsed < 0.5 ? 3.5 : parsed;
        } else if (settings.network?.guest_lookup_timeout !== undefined) {
          (payload.network as Record<string, unknown>).guest_lookup_timeout =
            settings.network.guest_lookup_timeout;
        } else {
          (payload.network as Record<string, unknown>).guest_lookup_timeout = 3.5;
        }
      }

      if (settings.config_version !== null && settings.config_version !== undefined) {
        payload.expected_version = settings.config_version;
      }

      await updateMutation.mutateAsync(payload);
    } catch (error) {
      const raw = error as {
        response?: {
          status?: number;
          data?: { detail?: SettingsConflictDetail };
        };
      };
      if (raw.response?.status === 409) {
        const detail = raw.response.data?.detail;
        const current = detail?.current;
        const currentSettings =
          current &&
          typeof current === 'object' &&
          'hostname' in current &&
          'worker_pool' in current
            ? (current as SettingsResponse)
            : null;
        if (currentSettings) {
          const attemptedPatch =
            detail?.attempted_patch && typeof detail.attempted_patch === 'object'
              ? detail.attempted_patch
              : (editedSettings as Record<string, unknown>);
          const conflictingFields = Array.isArray(detail?.conflicting_fields)
            ? detail.conflicting_fields
            : [];
          setConflictState({
            current: currentSettings,
            currentVersion: detail?.current_version ?? currentSettings.config_version ?? null,
            currentUpdatedAt:
              detail?.current_updated_at ?? currentSettings.config_updated_at ?? null,
            attemptedPatch,
            conflictingFields,
          });
          const initialChoices: Record<string, MergeChoice> = {};
          const currentRecord = currentSettings as unknown as Record<string, unknown>;
          const entries = buildConflictLeafEntries(
            attemptedPatch,
            currentRecord,
            conflictingFields,
          );
          for (const entry of entries) {
            initialChoices[entry.path] = 'local';
          }
          setConflictChoices(initialChoices);
          setConflictSaveError(null);
          setRedisTestResult(null);
          setIsSaving(false);
          return;
        }
      }
      const detailMessage = raw.response?.data?.detail?.message;
      setRedisTestResult({
        success: false,
        message: detailMessage
          ? detailMessage
          : error instanceof Error ? error.message : 'Failed to save settings',
        latency_ms: null,
      });
    } finally {
      setIsSaving(false);
      setIsTestingRedis(false);
    }
  };

  const handleReset = () => {
    setEditedSettings({});
    setHasChanges(false);
    setRedisTestResult(null);
  };

  const getCurrentValue = (key: TopLevelSettingsKey): unknown => {
    if (key in editedSettings) {
      return editedSettings[key];
    }
    return settings?.[key as keyof SettingsResponse];
  };

  const getNestedValue = (section: string, key: string): unknown => {
    const editedSection = editedSettings[
      section as keyof SettingsResponse
    ] as Record<string, unknown> | undefined;
    if (editedSection && key in editedSection) {
      return editedSection[key];
    }
    const settingsSection = settings?.[
      section as keyof SettingsResponse
    ] as Record<string, unknown> | undefined;
    return settingsSection?.[key];
  };

  const getDeepNestedValue = (section: string, subsection: string, key: string): unknown => {
    const editedSection = editedSettings[section as keyof SettingsResponse] as
      | Record<string, Record<string, unknown>>
      | undefined;
    if (editedSection && subsection in editedSection && key in editedSection[subsection]) {
      return editedSection[subsection][key];
    }
    const settingsSection = settings?.[section as keyof SettingsResponse] as
      | Record<string, Record<string, unknown>>
      | undefined;
    return settingsSection?.[subsection]?.[key];
  };

  const conflictLeafEntries = useMemo(() => {
    if (!conflictState) return [] as ConflictLeafEntry[];
    return buildConflictLeafEntries(
      conflictState.attemptedPatch,
      conflictState.current as unknown as Record<string, unknown>,
      conflictState.conflictingFields,
    );
  }, [conflictState]);

  const conflictEntriesByTopField = useMemo(() => {
    const grouped: Record<string, ConflictLeafEntry[]> = {};
    for (const entry of conflictLeafEntries) {
      if (!grouped[entry.topField]) grouped[entry.topField] = [];
      grouped[entry.topField].push(entry);
    }
    return grouped;
  }, [conflictLeafEntries]);

  const setConflictChoice = (path: string, choice: MergeChoice) => {
    setConflictChoices((previous) => ({ ...previous, [path]: choice }));
  };

  const handleDiscardConflict = () => {
    if (!conflictState) return;
    queryClient.setQueryData(['settings'], conflictState.current);
    setEditedSettings({});
    setHasChanges(false);
    setConflictState(null);
    setConflictChoices({});
    setConflictSaveError(null);
  };

  const handleMergeConflict = async () => {
    if (!conflictState) return;

    const mergedPatch: SettingsUpdate = {};
    const attemptedPatch = conflictState.attemptedPatch as Record<string, unknown>;
    const currentValues = conflictState.current as unknown as Record<string, unknown>;
    const selectedPaths = new Map(
      conflictLeafEntries.map((entry) => [
        entry.path,
        conflictChoices[entry.path] ?? 'local',
      ] as const),
    );

    const topFields = Object.keys(attemptedPatch).filter(
      (field) => !RESERVED_CONFLICT_FIELDS.has(field),
    );
    for (const field of topFields) {
      const localTopValue = attemptedPatch[field];
      if (!isPlainObject(localTopValue)) {
        const choice = selectedPaths.get(field) ?? 'local';
        (mergedPatch as Record<string, unknown>)[field] =
          choice === 'remote' ? currentValues[field] : localTopValue;
        continue;
      }

      const remoteTop = isPlainObject(currentValues[field])
        ? deepClone(currentValues[field] as Record<string, unknown>)
        : {};

      const entries = conflictLeafEntries.filter((entry) => entry.topField === field);
      for (const entry of entries) {
        const choice = selectedPaths.get(entry.path) ?? 'local';
        if (choice !== 'local') continue;
        const nestedPath = entry.pathParts.slice(1);
        if (nestedPath.length === 0) {
          (mergedPatch as Record<string, unknown>)[field] = deepClone(entry.localValue);
          continue;
        }
        setNestedObjectValue(remoteTop, nestedPath, deepClone(entry.localValue));
      }

      if (!(field in (mergedPatch as Record<string, unknown>))) {
        (mergedPatch as Record<string, unknown>)[field] = remoteTop;
      }
    }

    // Redis is persisted through the runtime environment endpoint rather than
    // the versioned application-settings row, so preserve it across an
    // application-settings conflict as an independent local edit.
    const editedRedis = editedSettings.redis;
    if (isPlainObject(editedRedis)) {
      const currentRedis = isPlainObject(currentValues.redis) ? currentValues.redis : {};
      (mergedPatch as Record<string, unknown>).redis = mergePlainObjects(
        currentRedis,
        editedRedis,
      );
    }

    const latestVersion =
      conflictState.currentVersion ?? conflictState.current.config_version ?? null;
    if (latestVersion !== null && latestVersion !== undefined) {
      mergedPatch.expected_version = latestVersion;
    }

    try {
      setConflictSaveError(null);
      await updateMutation.mutateAsync(mergedPatch);
    } catch (error) {
      setConflictSaveError(
        error instanceof Error ? error.message : 'Failed to merge and save',
      );
    }
  };

  const selectDbSetting = (row: DBSettingRecord) => {
    setSelectedDbSettingId(row.id);
    setDbEditor({
      backend: row.backend,
      key: row.key,
      value: row.value,
      description: row.description || '',
      isSecret: row.is_secret,
    });
  };

  const resetDbEditor = () => {
    setSelectedDbSettingId(null);
    setDbEditor(createEmptyDbEditor());
  };

  const selectedDbSetting =
    dbSettings?.find((row) => row.id === selectedDbSettingId) || null;

  const handleDbEditorChange = (
    field: keyof DbEditorState,
    value: DbEditorState[keyof DbEditorState],
  ) => {
    setDbEditor((previous) => ({ ...previous, [field]: value }));
  };

  const saveDbSetting = async () => {
    setDbMessage(null);
    try {
      if (selectedDbSetting) {
        const updated = await patchDbSetting(selectedDbSetting.id, {
          backend: dbEditor.backend,
          key: dbEditor.key,
          value: dbEditor.value,
          is_secret: dbEditor.isSecret,
          description: dbEditor.description || null,
          expected_version: selectedDbSetting.version,
        });
        await dbSettingsQuery.refetch();
        setDbMessage({ type: 'success', text: `Updated setting #${updated.id}` });
        setSelectedDbSettingId(updated.id);
      } else {
        const created = await upsertDbSetting({
          backend: dbEditor.backend,
          key: dbEditor.key,
          value: dbEditor.value,
          is_secret: dbEditor.isSecret,
          description: dbEditor.description || null,
        });
        await dbSettingsQuery.refetch();
        setDbMessage({ type: 'success', text: `Created setting #${created.id}` });
        setSelectedDbSettingId(created.id);
      }
      void queryClient.invalidateQueries({ queryKey: ['settings'] });
    } catch (error) {
      const conflict = error as {
        response?: { status?: number; data?: { detail?: { current?: DBSettingRecord } } };
      };
      if (conflict.response?.status === 409) {
        const current = conflict.response.data?.detail?.current;
        if (current) {
          selectDbSetting(current);
          setDbMessage({
            type: 'error',
            text: `Conflict detected. Reloaded latest row #${current.id}.`,
          });
          return;
        }
      }
      setDbMessage({
        type: 'error',
        text: error instanceof Error ? error.message : 'Failed to save DB setting',
      });
    }
  };

  const deleteSelectedDbSetting = async () => {
    if (!selectedDbSetting) return;
    setDbMessage(null);
    try {
      const result = await deleteDbSetting(selectedDbSetting.id);
      if (result.success) {
        setDbMessage({
          type: 'success',
          text: `Deleted setting #${selectedDbSetting.id}`,
        });
        resetDbEditor();
        await dbSettingsQuery.refetch();
        void queryClient.invalidateQueries({ queryKey: ['settings'] });
      } else {
        setDbMessage({
          type: 'error',
          text: `No row deleted for #${selectedDbSetting.id}`,
        });
      }
    } catch (error) {
      setDbMessage({
        type: 'error',
        text: error instanceof Error ? error.message : 'Failed to delete DB setting',
      });
    }
  };

  const selectBackendInventory = (row: BackendInventoryRecord) => {
    setSelectedInventoryId(row.id);
    setInventoryEditor({
      backendName: row.backend_name,
      hostname: row.hostname,
      localIp: row.local_ip || '',
      settingsId: String(row.settings_id),
    });
  };

  const resetInventoryEditor = () => {
    setSelectedInventoryId(null);
    setInventoryEditor(createEmptyInventoryEditor());
  };

  const selectedInventory =
    backendInventory?.find((row) => row.id === selectedInventoryId) || null;

  const handleInventoryEditorChange = (
    field: keyof InventoryEditorState,
    value: string,
  ) => {
    setInventoryEditor((previous) => ({ ...previous, [field]: value }));
  };

  const saveInventory = async () => {
    setDbMessage(null);
    const parsedSettingsId = Number.parseInt(inventoryEditor.settingsId, 10);
    if (!Number.isFinite(parsedSettingsId) || parsedSettingsId <= 0) {
      setDbMessage({
        type: 'error',
        text: 'settings_id must be a positive integer.',
      });
      return;
    }
    try {
      if (selectedInventory) {
        const updated = await patchBackendInventory(selectedInventory.id, {
          backend_name: inventoryEditor.backendName,
          hostname: inventoryEditor.hostname,
          local_ip: inventoryEditor.localIp || null,
          settings_id: parsedSettingsId,
        });
        await backendInventoryQuery.refetch();
        setDbMessage({
          type: 'success',
          text: `Updated backend mapping #${updated.id}`,
        });
        setSelectedInventoryId(updated.id);
      } else {
        const created = await upsertBackendInventory({
          backend_name: inventoryEditor.backendName,
          hostname: inventoryEditor.hostname,
          local_ip: inventoryEditor.localIp || null,
          settings_id: parsedSettingsId,
        });
        await backendInventoryQuery.refetch();
        setDbMessage({
          type: 'success',
          text: `Created backend mapping #${created.id}`,
        });
        setSelectedInventoryId(created.id);
      }
    } catch (error) {
      setDbMessage({
        type: 'error',
        text: error instanceof Error ? error.message : 'Failed to save backend mapping',
      });
    }
  };

  const deleteSelectedInventory = async () => {
    if (!selectedInventory) return;
    setDbMessage(null);
    try {
      const result = await deleteBackendInventory(selectedInventory.id);
      if (result.success) {
        await backendInventoryQuery.refetch();
        setDbMessage({
          type: 'success',
          text: `Deleted backend mapping #${selectedInventory.id}`,
        });
        resetInventoryEditor();
      } else {
        setDbMessage({
          type: 'error',
          text: `No mapping deleted for #${selectedInventory.id}`,
        });
      }
    } catch (error) {
      setDbMessage({
        type: 'error',
        text: error instanceof Error ? error.message : 'Failed to delete backend mapping',
      });
    }
  };

  const redisEnabled =
    (getNestedValue('redis', 'enabled') as boolean | undefined) ?? settings?.redis.enabled ?? false;
  const executionMode =
    (getNestedValue('backend', 'execution_mode') as string | undefined) ??
    settings?.backend?.execution_mode ??
    'distributed';
  const changedFields = Object.keys(editedSettings).length;

  return {
    activeTab,
    backendInventory,
    changedFields,
    conflictChoices,
    conflictEntriesByTopField,
    conflictSaveError,
    conflictState,
    dbEditor,
    dbMessage,
    dbSettings,
    error: settingsQuery.error,
    executionMode,
    getCurrentValue,
    getDeepNestedValue,
    getNestedValue,
    handleChange,
    handleDbEditorChange,
    handleDeepNestedChange,
    handleDiscardConflict,
    handleInventoryEditorChange,
    handleMergeConflict,
    handleNestedChange,
    handleReset,
    handleSave,
    hasChanges,
    inventoryEditor,
    isFetchingBackendInventory: backendInventoryQuery.isFetching,
    isFetchingDbSettings: dbSettingsQuery.isFetching,
    isLoading: settingsQuery.isLoading,
    isSaving,
    isTestingRedis,
    redisEnabled,
    redisTestResult,
    refetchBackendInventory: backendInventoryQuery.refetch,
    refetchDbSettings: dbSettingsQuery.refetch,
    resetDbEditor,
    resetInventoryEditor,
    saveDbSetting,
    saveInventory,
    selectBackendInventory,
    selectDbSetting,
    selectedDbSetting,
    selectedDbSettingId,
    selectedInventory,
    selectedInventoryId,
    setActiveTab,
    setConflictChoice,
    settings,
    updateMutation,
    deleteSelectedDbSetting,
    deleteSelectedInventory,
  };
}

export type SettingsPageController = ReturnType<typeof useSettingsPageController>;
