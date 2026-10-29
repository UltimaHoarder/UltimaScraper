import { useQuery } from '@tanstack/react-query';
import { getTaskTypes } from '../../../../api/jobs';
import { PluginCreateForm } from '../../../../features/plugins/components/PluginCreateForm';
import { PluginPackageReview } from '../../../../features/plugins/components/PluginPackageReview';
import { PluginSetupModal } from '../../../../features/plugins/components/PluginSetupModal';
import { PluginSplitWorkspace } from '../../../../features/plugins/components/PluginSplitWorkspace';
import { PluginInstallModal } from '../../../../features/plugins/components/PluginInstallModal';
import { PluginUninstallModal } from '../../../../features/plugins/components/PluginUninstallModal';
import { usePluginsPageController } from '../../../../features/plugins/hooks/usePluginsPageController';
import { useNativePluginTrust } from '../../../../features/plugins/lib/useNativePluginTrust';
import { OperationsNotice } from '../../../../shared/ui/operations/OperationsChrome';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import './PluginsPage.css';

export function PluginsPage() {
  const controller = usePluginsPageController();
  const taskTypesQuery = useQuery({
    queryKey: ['plugin-task-catalog'],
    queryFn: getTaskTypes,
    staleTime: 60_000,
  });
  const { plugins, statusCounts, setupTarget, stagedPackage } = controller;
  const setupPlugin = plugins.find((plugin) => plugin.plugin_id === setupTarget?.pluginId);
  const nativeTrust = useNativePluginTrust();
  const blockedNative = nativeTrust.known && !nativeTrust.allowed
    ? plugins.filter((plugin) => plugin.ui_mode === 'native' && plugin.status === 'enabled')
    : [];

  return (
    <div className="plugins-page plugins-page--split">
      <WorkspacePageHeader
        eyebrow="Platform"
        title="Plugins"
        subtitle="Inspect and manage your extensions."
        badges={[
          { label: 'Total', value: String(statusCounts.total), tone: 'neutral' },
          { label: 'Enabled', value: String(statusCounts.enabled), tone: 'success' },
          { label: 'Disabled', value: String(statusCounts.disabled), tone: 'neutral' },
          ...(statusCounts.invalid > 0 ? [{ label: 'Invalid', value: String(statusCounts.invalid), tone: 'danger' as const }] : []),
          ...(statusCounts.missing > 0 ? [{ label: 'Missing', value: String(statusCounts.missing), tone: 'warning' as const }] : []),
          ...(statusCounts.approvalRequired > 0 ? [{ label: 'Approval', value: String(statusCounts.approvalRequired), tone: 'warning' as const }] : []),
        ]}
        meta={<div className="plugin-actions"><button type="button" className="plugins-create-toggle" onClick={() => controller.setShowInstall(true)}>+ Install plugin</button>{!controller.showCreateForm && <button type="button" className="plugins-create-toggle" onClick={() => controller.setShowCreateForm(true)}>+ Create Plugin</button>}</div>}
        icon="⌘"
      />
      {blockedNative.length > 0 && <OperationsNotice tone="warning" title="Native plugin UI is not loaded">
        {blockedNative.map((plugin) => plugin.display_name).join(', ')} {blockedNative.length === 1 ? 'runs' : 'run'} code in the WebUI page, which holds every backend&apos;s session.
        Their screens stay hidden until you trust {nativeTrust.connectionName ?? 'this backend'}&apos;s plugins on the <a href="/connections">Backends</a> page.
      </OperationsNotice>}
      {controller.isError && <OperationsNotice tone="danger" title="Failed to load plugins">Could not retrieve the plugin list. Check connectivity and try again.</OperationsNotice>}
      {taskTypesQuery.isError && <OperationsNotice tone="warning" title="Task catalog unavailable">Task-type selection is unavailable until the runtime task catalog responds.</OperationsNotice>}
      {controller.isMetadataFallback && <OperationsNotice tone="warning" title="Plugin metadata unavailable">The editor is using bundled choices until backend metadata responds.</OperationsNotice>}
      {controller.showCreateForm && <PluginCreateForm
        onSubmit={controller.handleCreate} onCancel={() => controller.setShowCreateForm(false)}
        isCreating={controller.isCreating} createError={controller.createError}
        taskCatalog={taskTypesQuery.data ?? []} isTaskCatalogLoading={taskTypesQuery.isLoading}
        capabilityOptions={controller.capabilityOptions} eventFamilyOptions={controller.eventFamilyOptions}
      />}
      {stagedPackage && <PluginPackageReview key={stagedPackage.package_digest} staged={stagedPackage} onClose={() => controller.setStagedPackage(null)} />}
      {setupTarget && setupPlugin && <PluginSetupModal key={setupTarget.pluginId} plugin={setupPlugin} enable={setupTarget.enable} onClose={controller.closeSetup} />}
      {controller.showInstall && <PluginInstallModal onClose={controller.closeInstall} onInstalled={controller.handleInstalled} />}
      {controller.uninstallTarget && <PluginUninstallModal plugin={controller.uninstallTarget} onClose={controller.closeUninstall} onUninstalled={controller.handleUninstalled} />}
      {controller.isLoading ? (
        <OperationsNotice tone="info" title="Loading plugins…">Fetching plugin data from the backend.</OperationsNotice>
      ) : plugins.length === 0 ? (
        !controller.isError && <div className="plugins-empty"><p>No plugins discovered. Create one above to get started.</p></div>
      ) : <PluginSplitWorkspace controller={controller} />}
      {controller.toast && <div role={controller.toast.type === 'error' ? 'alert' : 'status'} className={`plugins-toast plugins-toast--${controller.toast.type}`}>{controller.toast.message}</div>}
    </div>
  );
}
