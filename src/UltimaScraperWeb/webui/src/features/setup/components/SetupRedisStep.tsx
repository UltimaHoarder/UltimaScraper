import { useEffect, useState } from 'react';

import { testConfiguredRedis, testSetupRedisConnection } from '../../../api/setup';
import type { RedisConnectionRequest, RedisConnectionResponse } from '../../../api/types/setup';
import { getSetupErrorMessage } from '../lib/setupUtils';
import { RedisConnectionFields } from './RedisConnectionFields';
import { SetupHint } from './SetupHint';

interface SetupRedisStepProps {
  redisConfig: RedisConnectionRequest;
  setRedisConfig: (cfg: RedisConnectionRequest) => void;
  /** host:port of the deployment's own Redis, when it configures one. */
  redisTarget: string | null;
  useConfigured: boolean;
  setUseConfigured: (value: boolean) => void;
  onBack?: () => void;
  onNext: () => void;
}

export function SetupRedisStep({
  redisConfig,
  setRedisConfig,
  redisTarget,
  useConfigured,
  setUseConfigured,
  onBack,
  onNext,
}: SetupRedisStepProps) {
  const [testResult, setTestResult] = useState<RedisConnectionResponse | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  useEffect(() => {
    setTestResult(null);
    // Typing re-tests after a short pause; the configured connection once.
    const timer = setTimeout(
      async () => {
        setIsTesting(true);
        try {
          setTestResult(
            useConfigured ? await testConfiguredRedis() : await testSetupRedisConnection(redisConfig),
          );
        } catch (error: unknown) {
          setTestResult({
            success: false,
            message: getSetupErrorMessage(error, 'Connection failed'),
            latency_ms: null,
          });
        } finally {
          setIsTesting(false);
        }
      },
      useConfigured ? 0 : 500,
    );

    return () => clearTimeout(timer);
  }, [redisConfig, useConfigured]);

  return (
    <>
      <div className="setup-card-header">
        <h2>Redis Configuration</h2>
        <p>
          {redisTarget
            ? 'This deployment already supplies a Redis connection. Use it, or enter a different one below.'
            : 'UltimaScraper uses Redis for its job queues and live updates.'}
        </p>
      </div>

      <div className="setup-card-body">
        {redisTarget && (
          <label className="setup-skip-toggle">
            <input
              type="checkbox"
              checked={useConfigured}
              onChange={(event) => setUseConfigured(event.target.checked)}
            />
            <span>
              Use the configured Redis connection (<code>{redisTarget}</code>)
            </span>
            <SetupHint text="Docker installs bring their own Redis, with a generated password. Leave this on unless you run Redis elsewhere." />
          </label>
        )}

        {!useConfigured && (
          <RedisConnectionFields redisConfig={redisConfig} onChange={setRedisConfig} />
        )}

        {isTesting ? (
          <div className="setup-test-result pending">
            <span className="icon">⋯</span>
            <div className="details">Testing connection…</div>
          </div>
        ) : testResult ? (
          <div className={`setup-test-result ${testResult.success ? 'success' : 'error'}`}>
            <span className="icon">{testResult.success ? '✓' : '✗'}</span>
            <div className="details">
              <div>{testResult.message}</div>
              {testResult.latency_ms != null && (
                <div className="latency">{testResult.latency_ms.toFixed(1)} ms</div>
              )}
            </div>
          </div>
        ) : null}
      </div>

      <div className="setup-card-footer">
        {onBack ? (
          <button onClick={onBack} className="btn-secondary btn-lg">
            Back
          </button>
        ) : (
          <span />
        )}
        <button
          onClick={onNext}
          className="btn-primary btn-lg"
          disabled={!testResult?.success}
        >
          Continue
        </button>
      </div>
    </>
  );
}
