import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';

import { claimWebUI, getWebUISession, MIN_WEBUI_PASSWORD_LENGTH, signInToWebUI, WEBUI_ACCOUNT_NAME, type WebUISession } from '../../api/webui';
import './signInCard.css';

/**
 * Signs the browser in to the WebUI server. The first browser on the server's
 * own network creates the password; anywhere else also needs the setup code
 * that `docker compose logs webui` prints.
 */
export function WebUISignInGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<WebUISession | null>(null);
  const [loadError, setLoadError] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [code, setCode] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setSession(await getWebUISession());
      setLoadError('');
    } catch {
      setLoadError('The WebUI server is unavailable. Check the container status and try again.');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (session?.authenticated) {
    return children;
  }

  const creating = session !== null && !session.password_set;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage('');
    if (creating && password.length < MIN_WEBUI_PASSWORD_LENGTH) {
      setMessage(`Use at least ${MIN_WEBUI_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (creating && password !== confirmation) {
      setMessage('The passwords do not match.');
      return;
    }
    setSubmitting(true);
    try {
      if (creating) {
        await claimWebUI(password, session.can_claim ? undefined : code.trim());
      } else {
        await signInToWebUI(password);
      }
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Sign-in failed.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="admin-token-gate">
      <section className="admin-token-card" aria-labelledby="webui-sign-in-title">
        <p className="admin-token-eyebrow">UltimaScraper</p>
        <h1 id="webui-sign-in-title">{creating ? 'Create your password' : 'Sign in'}</h1>
        {session === null ? (
          <p className="admin-token-copy" role={loadError ? 'alert' : 'status'}>
            {loadError || 'Connecting…'}
          </p>
        ) : (
          <>
            <div className="admin-token-copy">
              {creating ? (
                <p>
                  This WebUI has no password yet. Choose one of at least {MIN_WEBUI_PASSWORD_LENGTH} characters;
                  you will use it to sign in from any browser.
                  {!session.can_claim && ' Because this browser is not on the server’s network, also enter the setup code from its log.'}
                </p>
              ) : (
                <p>Enter the WebUI password.</p>
              )}
              {creating && !session.can_claim && (
                <pre className="admin-token-command">
                  <code>docker compose logs webui</code>
                </pre>
              )}
            </div>
            <form onSubmit={submit}>
              <input type="text" name="username" autoComplete="username" value={WEBUI_ACCOUNT_NAME} readOnly hidden />
              <label htmlFor="webui-password">Password</label>
              <input
                id="webui-password"
                name={creating ? 'new-password' : 'password'}
                type="password"
                autoComplete={creating ? 'new-password' : 'current-password'}
                value={password}
                disabled={submitting}
                onChange={(event) => setPassword(event.target.value)}
                required
                autoFocus
              />
              {creating && (
                <>
                  <label htmlFor="webui-password-confirmation">Confirm password</label>
                  <input
                    id="webui-password-confirmation"
                    name="confirm-password"
                    type="password"
                    autoComplete="new-password"
                    value={confirmation}
                    disabled={submitting}
                    onChange={(event) => setConfirmation(event.target.value)}
                    required
                  />
                </>
              )}
              {creating && !session.can_claim && (
                <>
                  <label htmlFor="webui-setup-code">Setup code</label>
                  <input
                    id="webui-setup-code"
                    name="setup-code"
                    // Not a password field, so password managers leave it alone.
                    type="text"
                    autoComplete="one-time-code"
                    spellCheck={false}
                    value={code}
                    disabled={submitting}
                    onChange={(event) => setCode(event.target.value)}
                    required
                  />
                </>
              )}
              {message && <p className="admin-token-message" role="alert">{message}</p>}
              <button type="submit" disabled={submitting}>
                {submitting ? 'Please wait…' : creating ? 'Create password' : 'Sign in'}
              </button>
            </form>
          </>
        )}
      </section>
    </main>
  );
}
