import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { activatePluginPackage } from '../../../api/plugins';
import type { PluginStagedPackage } from '../../../api/types/plugins';

export function PluginPackageReview({ staged, onClose }: { staged: PluginStagedPackage; onClose: () => void }) {
  const client = useQueryClient();
  const [approved, setApproved] = useState(false);
  const needsApproval = staged.added_capabilities.length > 0 || staged.scope_changes;
  const activation = useMutation({
    mutationFn: () => activatePluginPackage(staged.plugin_id, staged.package_digest, approved),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['plugins'] });
      void client.invalidateQueries({ queryKey: ['active-plugins-webui'] });
      onClose();
    },
  });
  return <section className="plugin-contribution" aria-label="Review plugin upgrade">
    <h3>Review {staged.plugin_id} upgrade</h3>
    <p>Version {staged.previous_version ?? 'new installation'} → {staged.plugin_version}</p>
    <p>Requested capabilities: {staged.requested_capabilities.join(', ') || 'none'}</p>
    {staged.added_capabilities.length > 0 && <p>New capabilities: {staged.added_capabilities.join(', ')}</p>}
    {staged.scope_changes && <dl>
      <dt>Profile fields</dt><dd>{staged.requested_scopes.profile_fields?.join(', ') || 'none'}</dd>
      <dt>Task types</dt><dd>{staged.requested_scopes.task_types?.join(', ') || 'none'}</dd>
      <dt>Outbound hosts</dt><dd>{staged.requested_scopes.outbound_domains?.join(', ') || 'none'}</dd>
      <dt>State keys</dt><dd>{staged.requested_scopes.state_keys?.join(', ') || 'none'}</dd>
      <dt>Profile suggestions</dt><dd>{staged.requested_scopes.propose_profile_changes ? 'allowed' : 'disabled'}</dd>
    </dl>}
    {needsApproval && <label><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} /> Approve the requested permissions</label>}
    {activation.error && <p role="alert">{activation.error.message}</p>}
    <div>
      <button type="button" disabled={activation.isPending || (needsApproval && !approved)} onClick={() => activation.mutate()}>Activate version {staged.plugin_version}</button>
      <button type="button" disabled={activation.isPending} onClick={onClose}>Keep current version</button>
    </div>
  </section>;
}
