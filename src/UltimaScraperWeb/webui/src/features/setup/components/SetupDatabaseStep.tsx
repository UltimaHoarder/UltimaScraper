import { useEffect, useRef } from 'react';
import { useMutation } from '@tanstack/react-query';

import { testConfiguredDatabase } from '../../../api/setup';
import type {
  DatabaseConnectionRequest,
  DatabaseConnectionResponse,
} from '../../../api/types/setup';
import { getSetupErrorMessage } from '../lib/setupUtils';
import { DatabaseConnectionFields } from './DatabaseConnectionFields';
import { SetupHint } from './SetupHint';

interface SetupDatabaseStepProps {
  dbConfig: DatabaseConnectionRequest;
  setDbConfig: (cfg: DatabaseConnectionRequest) => void;
  dbTestResult: DatabaseConnectionResponse | null;
  onTest: () => void;
  isTesting: boolean;
  onNext: () => void;
  skipDb: boolean;
  setSkipDb: (value: boolean) => void;
  /** The deployment environment already supplies a database connection. */
  hasConfiguredDatabase: boolean;
}

function TestResult({ result }: { result: DatabaseConnectionResponse }) {
  return (
    <div className={`setup-test-result ${result.success ? 'success' : 'error'}`}>
      <span className="icon">{result.success ? '✓' : '✗'}</span>
      <div className="details">
        <div>{result.message}</div>
        {result.latency_ms != null && (
          <div className="latency">{result.latency_ms.toFixed(1)} ms</div>
        )}
      </div>
    </div>
  );
}

export function SetupDatabaseStep({
  dbConfig,
  setDbConfig,
  dbTestResult,
  onTest,
  isTesting,
  onNext,
  skipDb,
  setSkipDb,
  hasConfiguredDatabase,
}: SetupDatabaseStepProps) {
  // The configured connection still needs its schema prepared before setup
  // can store anything, so it is tested (and migrated) automatically.
  const configuredTest = useMutation({
    mutationFn: testConfiguredDatabase,
  });
  const { mutate: prepareConfigured } = configuredTest;
  // Strict Mode runs effects twice; two schema migrations must not race.
  const preparationStarted = useRef(false);
  useEffect(() => {
    if (!skipDb || preparationStarted.current) return;
    preparationStarted.current = true;
    prepareConfigured();
  }, [skipDb, prepareConfigured]);
  const configuredResult: DatabaseConnectionResponse | null = configuredTest.data
    ?? (configuredTest.error
      ? {
          success: false,
          message: getSetupErrorMessage(configuredTest.error, 'Could not reach the database'),
          latency_ms: null,
        }
      : null);

  const canContinue = skipDb ? Boolean(configuredResult?.success) : Boolean(dbTestResult?.success);

  return (
    <>
      <div className="setup-card-header">
        <h2>Database Configuration</h2>
        <p>
          {hasConfiguredDatabase
            ? 'This deployment already supplies a PostgreSQL connection. Use it, or enter a different one below.'
            : 'UltimaScraper uses PostgreSQL for site data. Configure your connection below.'}
        </p>
      </div>

      <div className="setup-card-body">
        {hasConfiguredDatabase && (
          <label className="setup-skip-toggle">
            <input
              type="checkbox"
              checked={skipDb}
              onChange={(event) => setSkipDb(event.target.checked)}
            />
            <span>Use the configured database connection</span>
            <SetupHint text="Docker installs bring their own PostgreSQL. Leave this on unless you want to use a different server." />
          </label>
        )}

        {skipDb && (
          <>
            {configuredTest.isPending && (
              <div className="setup-test-result pending">
                <span className="icon">⋯</span>
                <div className="details">Connecting and preparing the database…</div>
              </div>
            )}
            {configuredResult && <TestResult result={configuredResult} />}
            {configuredResult && !configuredResult.success && (
              <button
                onClick={() => prepareConfigured()}
                className="btn-secondary btn-lg"
                style={{ width: '100%', marginTop: 'var(--space-3)' }}
              >
                Try again
              </button>
            )}
          </>
        )}

        {!skipDb && (
          <>
            <DatabaseConnectionFields dbConfig={dbConfig} onChange={setDbConfig} />

            <button
              onClick={onTest}
              disabled={isTesting}
              className="btn-secondary btn-lg"
              style={{ width: '100%' }}
              title="Connect, then create or update the database schema"
            >
              {isTesting ? 'Testing connection…' : 'Test Connection'}
            </button>

            {dbTestResult && <TestResult result={dbTestResult} />}
          </>
        )}
      </div>

      <div className="setup-card-footer">
        <div />
        <button onClick={onNext} disabled={!canContinue} className="btn-primary btn-lg">
          Continue
        </button>
      </div>
    </>
  );
}
