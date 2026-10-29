import type { SetupAuthRequest } from '../../../api/types/setup';
import { SetupHint } from './SetupHint';

interface SetupAuthsStepProps {
  auths: SetupAuthRequest[];
  setAuths: (auths: SetupAuthRequest[]) => void;
  availableProxies: string[];
  onBack: () => void;
  onNext: () => void;
}

export function SetupAuthsStep({
  auths,
  setAuths,
  availableProxies,
  onBack,
  onNext,
}: SetupAuthsStepProps) {
  const addAuth = () => setAuths([...auths, { site: 'onlyfans', curl_command: '' }]);
  const removeAuth = (index: number) =>
    setAuths(auths.filter((_, currentIndex) => currentIndex !== index));
  const updateAuth = (index: number, field: keyof SetupAuthRequest, value: string) => {
    const nextAuths = [...auths];
    nextAuths[index] = { ...nextAuths[index], [field]: value };
    setAuths(nextAuths);
  };

  return (
    <>
      <div className="setup-card-header">
        <h2>Authentication</h2>
        <p>
          Optional. Add your accounts by pasting the cURL command from your browser&apos;s network
          tab.
          <SetupHint text="Sign in to the site in your browser, open developer tools, go to Network, right-click a request to the site's API and choose Copy, then Copy as cURL. Paste the whole command here." />
        </p>
      </div>

      <div className="setup-card-body">
        <div className="setup-form-group">
          <div className="setup-dir-list">
            {auths.map((auth, index) => (
              <div key={index} className="setup-dir-row" style={{ alignItems: 'flex-start' }}>
                <div
                  style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 'var(--space-2)',
                  }}
                >
                  <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                    <select
                      className="setup-form-input"
                      aria-label="Site"
                      title="The site this account belongs to"
                      value={auth.site}
                      onChange={(event) => updateAuth(index, 'site', event.target.value)}
                      style={{ flex: 1 }}
                    >
                      <option value="onlyfans">OnlyFans</option>
                      <option value="fansly">Fansly</option>
                    </select>
                    <select
                      className="setup-form-input"
                      aria-label="Proxy"
                      title="Route this account through one of the proxies from the previous step"
                      value={auth.proxy_id || ''}
                      onChange={(event) => updateAuth(index, 'proxy_id', event.target.value)}
                      style={{ flex: 1 }}
                    >
                      <option value="">No Proxy (Direct)</option>
                      {availableProxies
                        .filter((proxy) => proxy.trim())
                        .map((proxy, proxyIndex) => (
                          <option key={proxyIndex} value={proxy}>
                            {proxy}
                          </option>
                        ))}
                    </select>
                  </div>
                  <textarea
                    className="setup-form-input"
                    value={auth.curl_command}
                    onChange={(event) => updateAuth(index, 'curl_command', event.target.value)}
                    placeholder="Paste cURL command here..."
                    rows={3}
                    style={{ resize: 'vertical' }}
                  />
                </div>
                <button
                  onClick={() => removeAuth(index)}
                  className="setup-dir-remove"
                  title="Remove this account"
                  style={{ marginTop: 'var(--space-1)' }}
                >
                  ✕
                </button>
              </div>
            ))}
            <button onClick={addAuth} className="setup-dir-add" title="Add an account from a cURL command">
              + Add Account
            </button>
          </div>
        </div>
      </div>

      <div className="setup-card-footer">
        <button onClick={onBack} className="btn-secondary btn-lg">
          Back
        </button>
        <button onClick={onNext} className="btn-primary btn-lg">
          Continue
        </button>
      </div>
    </>
  );
}
