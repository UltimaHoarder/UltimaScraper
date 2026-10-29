import { useCallback, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  approvePluginCapabilities,
  createPlugin,
  disablePlugin,
  enablePlugin,
  getPluginManifest,
  getPluginMetadata,
  listPluginSecrets,
  listPlugins,
  purgePluginData,
  reloadPlugin,
  setPluginSecret,
  updatePluginManifest,
} from '../../../api/plugins';
import type { PluginCreateRequest, PluginRecord, PluginSecretRecord, PluginStagedPackage } from '../../../api/types/plugins';
import {
  DEFAULT_EVENT_FAMILIES,
  DEFAULT_PLUGIN_CAPABILITIES,
} from '../lib/pluginManifestOptions';

const PLUGINS_QUERY_KEY = ['plugins'] as const;
const PLUGIN_METADATA_QUERY_KEY = ['plugin-metadata'] as const;

export function usePluginsPageController() {
  const queryClient = useQueryClient();
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showInstall, setShowInstall] = useState(false);
  const [uninstallTarget, setUninstallTarget] = useState<PluginRecord | null>(null);
  const [selectedPluginId, setSelectedPluginId] = useState<string | null>(null);
  const closeInstall = useCallback(() => setShowInstall(false), []);
  const closeUninstall = useCallback(() => setUninstallTarget(null), []);
  const [editingPluginId, setEditingPluginId] = useState<string | null>(null);
  const [editingManifestYaml, setEditingManifestYaml] = useState('');
  const manifestRequest = useRef(0);
  const [editingSecrets, setEditingSecrets] = useState<PluginSecretRecord[]>([]);
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const [stagedPackage, setStagedPackage] = useState<PluginStagedPackage | null>(null);
  const [setupTarget, setSetupTarget] = useState<{ pluginId: string; enable: boolean } | null>(null);
  const closeSetup = useCallback(() => setSetupTarget(null), []);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  };

  const pluginsQuery = useQuery<PluginRecord[]>({
    queryKey: PLUGINS_QUERY_KEY,
    queryFn: listPlugins,
    refetchInterval: 10_000,
  });

  const metadataQuery = useQuery({
    queryKey: PLUGIN_METADATA_QUERY_KEY,
    queryFn: getPluginMetadata,
    staleTime: Number.POSITIVE_INFINITY,
  });

  const createMutation = useMutation({
    mutationFn: (request: PluginCreateRequest) => createPlugin(request),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
      showToast(`Plugin "${data.display_name}" created successfully`, 'success');
      setShowCreateForm(false);
    },
    onError: (error: Error) => {
      showToast(error.message || 'Failed to create plugin', 'error');
    },
  });

  const enableMutation = useMutation({
    mutationFn: (pluginId: string) => enablePlugin(pluginId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ['active-plugins-webui'] });
      showToast(`Plugin "${data.display_name}" enabled`, 'success');
    },
    onError: (error: Error) => {
      showToast(error.message || 'Failed to enable plugin', 'error');
    },
  });

  const disableMutation = useMutation({
    mutationFn: (pluginId: string) => disablePlugin(pluginId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ['active-plugins-webui'] });
      showToast(`Plugin "${data.display_name}" disabled`, 'success');
    },
    onError: (error: Error) => {
      showToast(error.message || 'Failed to disable plugin', 'error');
    },
  });

  const approveCapabilitiesMutation = useMutation({
    mutationFn: (pluginId: string) => approvePluginCapabilities(pluginId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
      showToast(`Capabilities approved for "${data.display_name}"`, 'success');
    },
    onError: (error: Error) => {
      showToast(error.message || 'Failed to approve plugin capabilities', 'error');
    },
  });

  const reloadMutation = useMutation({
    mutationFn: (pluginId: string) => reloadPlugin(pluginId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
      showToast(`Plugin "${data.display_name}" reloaded`, 'success');
    },
    onError: (error: Error) => {
      showToast(error.message || 'Failed to reload plugin', 'error');
    },
  });

  const purgeMutation = useMutation({
    mutationFn: ({ pluginId, confirmation }: { pluginId: string; confirmation: string }) =>
      purgePluginData(pluginId, confirmation),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
      if (editingPluginId === data.plugin_id) {
        setEditingPluginId(null);
        setEditingManifestYaml('');
        setEditingSecrets([]);
        setSecretDrafts({});
      }
      showToast(`Purged ${data.deleted_records} retained record(s) for "${data.plugin_id}"`, 'success');
    },
    onError: (error: Error) => {
      showToast(error.message || 'Failed to purge plugin data', 'error');
    },
  });

  const editManifestLoadMutation = useMutation({
    mutationFn: async ({ pluginId, requestId }: { pluginId: string; requestId: number }) => {
      const [manifest, secrets] = await Promise.all([
        getPluginManifest(pluginId),
        listPluginSecrets(pluginId),
      ]);
      return { manifest, secrets, requestId };
    },
    onSuccess: ({ manifest, secrets, requestId }) => {
      if (requestId !== manifestRequest.current) return;
      setEditingPluginId(manifest.plugin_id);
      setEditingManifestYaml(manifest.manifest_yaml);
      setEditingSecrets(secrets);
      setSecretDrafts({});
      setShowCreateForm(false);
    },
    onError: (error: Error, variables) => {
      if (variables.requestId !== manifestRequest.current) return;
      showToast(error.message || 'Failed to load plugin manifest', 'error');
    },
  });

  const updateManifestMutation = useMutation({
    mutationFn: ({
      pluginId,
      manifestYaml,
    }: {
      pluginId: string;
      manifestYaml: string;
    }) => updatePluginManifest(pluginId, { manifest_yaml: manifestYaml }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
      setEditingPluginId(null);
      setEditingManifestYaml('');
      if (data.staged_package) {
        setStagedPackage(data.staged_package);
        showToast(`Plugin "${data.display_name}" upgrade is ready for review`, 'success');
      } else showToast(`Plugin "${data.display_name}" manifest updated`, 'success');
    },
    onError: (error: Error) => {
      showToast(error.message || 'Failed to update plugin manifest', 'error');
    },
  });

  const setSecretMutation = useMutation({
    mutationFn: ({
      pluginId,
      scopeKind,
      scopeName,
      rawSecret,
    }: {
      pluginId: string;
      scopeKind: string;
      scopeName: string;
      rawSecret: string;
    }) =>
      setPluginSecret(pluginId, {
        scope_kind: scopeKind,
        scope_name: scopeName,
        raw_secret: rawSecret,
      }),
    onSuccess: async (_, variables) => {
      const scopeKey = `${variables.scopeKind}:${variables.scopeName}`;
      setSecretDrafts((prev) => ({ ...prev, [scopeKey]: '' }));
      setEditingSecrets(await listPluginSecrets(variables.pluginId));
      showToast(`Stored secret for ${variables.scopeKind}/${variables.scopeName}`, 'success');
    },
    onError: (error: Error) => {
      showToast(error.message || 'Failed to store plugin secret', 'error');
    },
  });

  const handleCreate = useCallback(
    (request: PluginCreateRequest) => {
      createMutation.mutate(request);
    },
    [createMutation],
  );

  const handleEnable = useCallback(
    (pluginId: string) => {
      const plugin = pluginsQuery.data?.find((item) => item.plugin_id === pluginId);
      if ((plugin?.setup_required && !plugin.setup_ready) || plugin?.pending_capabilities?.length || plugin?.pending_scopes?.length || plugin?.enabled_at === null) setSetupTarget({ pluginId, enable: true });
      else enableMutation.mutate(pluginId);
    },
    [enableMutation, pluginsQuery.data],
  );

  const handleDisable = useCallback(
    (pluginId: string) => disableMutation.mutate(pluginId),
    [disableMutation],
  );

  const handleReload = useCallback(
    (pluginId: string) => reloadMutation.mutate(pluginId),
    [reloadMutation],
  );

  const handleApproveCapabilities = useCallback(
    (pluginId: string) => approveCapabilitiesMutation.mutate(pluginId),
    [approveCapabilitiesMutation],
  );

  const handlePurge = useCallback(
    (pluginId: string) => {
      const expected = `PURGE ${pluginId}`;
      const confirmation = window.prompt(
        `This permanently removes retained state, secrets, grants, runtime records, and delivery history. Type ${expected} to continue.`,
      );
      if (confirmation === null) {
        return;
      }
      if (confirmation !== expected) {
        showToast(`Confirmation must exactly match "${expected}".`, 'error');
        return;
      }
      purgeMutation.mutate({ pluginId, confirmation });
    },
    [purgeMutation],
  );

  const handleEdit = useCallback(
    (pluginId: string) => editManifestLoadMutation.mutate({ pluginId, requestId: ++manifestRequest.current }),
    [editManifestLoadMutation],
  );

  const handleManifestSave = useCallback(() => {
    if (!editingPluginId) {
      return;
    }
    updateManifestMutation.mutate({
      pluginId: editingPluginId,
      manifestYaml: editingManifestYaml,
    });
  }, [editingManifestYaml, editingPluginId, updateManifestMutation]);

  const { reset: resetManifestLoad } = editManifestLoadMutation;
  const cancelEdit = useCallback(() => {
    manifestRequest.current += 1;
    resetManifestLoad();
    setEditingPluginId(null);
    setEditingManifestYaml('');
    setEditingSecrets([]);
    setSecretDrafts({});
  }, [resetManifestLoad]);

  const updateSecretDraft = useCallback((scopeKey: string, value: string) => {
    setSecretDrafts((prev) => ({ ...prev, [scopeKey]: value }));
  }, []);

  const handleSetSecret = useCallback(
    (scopeKind: string, scopeName: string) => {
      if (!editingPluginId) {
        return;
      }
      const scopeKey = `${scopeKind}:${scopeName}`;
      const rawSecret = secretDrafts[scopeKey]?.trim() ?? '';
      if (!rawSecret) {
        showToast('Paste a secret value before saving.', 'error');
        return;
      }
      setSecretMutation.mutate({
        pluginId: editingPluginId,
        scopeKind,
        scopeName,
        rawSecret,
      });
    },
    [editingPluginId, secretDrafts, setSecretMutation],
  );

  const plugins = pluginsQuery.data ?? [];

  const statusCounts = {
    total: plugins.length,
    enabled: plugins.filter((p) => p.status === 'enabled').length,
    disabled: plugins.filter((p) => p.status === 'disabled').length,
    invalid: plugins.filter((p) => p.status === 'invalid').length,
    missing: plugins.filter((p) => p.status === 'missing').length,
    approvalRequired: plugins.filter((p) => (p.pending_capabilities?.length ?? 0) > 0 || (p.pending_scopes?.length ?? 0) > 0).length,
  };

  const handleInstalled = useCallback((plugin: PluginRecord) => {
    queryClient.setQueryData<PluginRecord[]>(PLUGINS_QUERY_KEY, (current = []) => [...current.filter((item) => item.plugin_id !== plugin.plugin_id), plugin]);
    setSelectedPluginId(plugin.plugin_id);
    setShowInstall(false);
    setSetupTarget({ pluginId: plugin.plugin_id, enable: true });
    void queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: ['plugin-sources'] });
  }, [queryClient]);

  const handleUninstalled = useCallback((pluginId: string) => {
    cancelEdit();
    queryClient.setQueryData<PluginRecord[]>(PLUGINS_QUERY_KEY, (current = []) => current.filter((item) => item.plugin_id !== pluginId));
    setUninstallTarget(null);
    setSetupTarget(null);
    void queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: ['active-plugins-webui'] });
    void queryClient.invalidateQueries({ queryKey: ['plugin-sources'] });
    queryClient.removeQueries({ queryKey: ['plugin-settings', pluginId] });
    queryClient.removeQueries({ queryKey: ['plugin-setup', pluginId] });
  }, [cancelEdit, queryClient]);

  return {
    plugins,
    showInstall, setShowInstall, closeInstall, handleInstalled,
    uninstallTarget, setUninstallTarget, closeUninstall, handleUninstalled,
    selectedPluginId, setSelectedPluginId,
    setupTarget,
    setSetupTarget,
    closeSetup,
    stagedPackage,
    setStagedPackage,
    capabilityOptions: metadataQuery.data?.capabilities ?? [...DEFAULT_PLUGIN_CAPABILITIES],
    eventFamilyOptions: metadataQuery.data?.event_families ?? [...DEFAULT_EVENT_FAMILIES],
    isMetadataFallback: metadataQuery.isError,
    statusCounts,
    isLoading: pluginsQuery.isLoading,
    isError: pluginsQuery.isError,
    showCreateForm,
    setShowCreateForm,
    editingPluginId,
    editingManifestYaml,
    editingSecrets,
    secretDrafts,
    setEditingManifestYaml,
    toast,
    handleCreate,
    handleEnable,
    handleDisable,
    handleReload,
    handleApproveCapabilities,
    handlePurge,
    handleEdit,
    handleManifestSave,
    handleSetSecret,
    updateSecretDraft,
    cancelEdit,
    isCreating: createMutation.isPending,
    createError: createMutation.error,
    isLoadingManifest: editManifestLoadMutation.isPending,
    loadingManifestPluginId: editManifestLoadMutation.variables?.pluginId ?? null,
    isSavingManifest: updateManifestMutation.isPending,
    isSavingSecret: setSecretMutation.isPending,
    isPurging: purgeMutation.isPending,
  };
}
