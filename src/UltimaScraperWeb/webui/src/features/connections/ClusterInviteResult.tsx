import type { ClusterInvite } from '../../api/webui';

/** What a copied cluster invite holds, and how to use it. */
export function ClusterInviteResult({ invite, error }: { invite: ClusterInvite | null; error: string }) {
  return (
    <>
      {invite && (
        <div className="connections-hint" role="status">
          Invite for {invite.name} copied, with {invite.members.map((member) => member.name).join(', ')}. On the
          other WebUI, open <strong>Set up</strong>, choose <strong>Join a cluster</strong> and paste it.{' '}
          {invite.version === 2 ? (
            <>
              It works once
              {invite.expires_at ? `, until ${new Date(invite.expires_at).toLocaleString()}` : ''}, and gives that
              WebUI its own access, which you can revoke.
            </>
          ) : (
            <>{invite.warning ?? 'It contains admin tokens: share it like a password.'}</>
          )}
          {invite.excluded.length > 0 && (
            <ul>
              {invite.excluded.map((item) => (
                <li key={item.name}>
                  Left out {item.name}: {item.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && (
        <p className="connections-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
