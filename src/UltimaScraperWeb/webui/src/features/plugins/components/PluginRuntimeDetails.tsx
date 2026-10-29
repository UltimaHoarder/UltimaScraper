import { useMutation, useQueryClient } from '@tanstack/react-query';
import { rollbackPluginPackage, runPluginSchedule } from '../../../api/plugins';
import type { PluginRecord } from '../../../api/types/plugins';

export function PluginRuntimeDetails({ plugin }: { plugin: PluginRecord }) {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ['plugins'] });
    void client.invalidateQueries({ queryKey: ['active-plugins-webui'] });
  };
  const rollback = useMutation({ mutationFn: () => rollbackPluginPackage(plugin.plugin_id), onSuccess: refresh });
  const run = useMutation({ mutationFn: (scheduleId: string) => runPluginSchedule(plugin.plugin_id, scheduleId), onSuccess: refresh });
  return <details>
    <summary>Runtime details</summary>
    {plugin.schedules?.map((schedule) => <div key={schedule.schedule_id}>
      <p>Next sync: {plugin.status === 'enabled' ? schedule.next_at ? new Date(schedule.next_at).toLocaleString() : 'Due now' : 'Paused'}</p>
      {(schedule.job_id || schedule.blocked_by_job) && <p>Sync job: {schedule.job_id ?? schedule.blocked_by_job}</p>}
      {schedule.last_result && <p>Last sync: {schedule.last_result.status ?? 'unknown'}{schedule.last_result.status === 'completed' || schedule.last_result.status === 'success' ? ` · ${['added', 'adopted', 'updated', 'deleted', 'disabled', 'retained_assigned', 'conflicts'].filter((key) => typeof schedule.last_result?.[key] === 'number').map((key) => `${schedule.last_result![key]} ${key.replaceAll('_', ' ')}`).join(', ')}` : ''}</p>}
      <button type="button" disabled={plugin.status !== 'enabled' || run.isPending || !!schedule.job_id || !!schedule.blocked_by_job} onClick={() => run.mutate(schedule.schedule_id)}>Sync now</button>
    </div>)}
    {run.error && <p role="alert">{run.error.message}</p>}
    <p>{plugin.delivery_queue?.pending ?? 0} pending deliveries; {plugin.delivery_queue?.counts.exhausted ?? 0} exhausted</p>
    {plugin.delivery_queue?.oldest_pending_at && <p>Oldest pending: {new Date(plugin.delivery_queue.oldest_pending_at).toLocaleString()}</p>}
    <p>UI access: {plugin.ui_mode === 'native' ? 'Trusted application code' : plugin.ui_mode === 'sandbox' ? 'Isolated custom UI' : 'Host-rendered contributions'}</p>
    {plugin.active_package?.previous_digest && <button type="button" disabled={rollback.isPending} onClick={() => rollback.mutate()}>Restore previous version</button>}
    {rollback.error && <p role="alert">{rollback.error.message}</p>}
  </details>;
}
