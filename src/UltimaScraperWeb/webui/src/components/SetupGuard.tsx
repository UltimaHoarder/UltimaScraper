import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { StartupSequence } from './StartupSequence';
import { useAppBootstrap } from '../app/bootstrap/AppBootstrapProvider';
import {
  hasAnyMigrationCheck,
  hasMigrationCheckForStartup,
  subscribeToMigrationChecks,
} from '../app/bootstrap/startupMigrationState';

export function SetupGuard({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    bootstrap,
    isLoading,
    isFetching,
    failureCount,
    error,
    retryBootstrap,
  } = useAppBootstrap();
  const [migrationGateDismissedForStartup, setMigrationGateDismissedForStartup] =
    useState<string | null>(null);
  const setupStatus = bootstrap?.setup;

  useEffect(() => {
    if (!isLoading && setupStatus) {
      if (!setupStatus.is_configured && location.pathname !== '/setup') {
        navigate('/setup', { replace: true });
      } else if (setupStatus.is_configured && location.pathname === '/setup') {
        navigate('/', { replace: true });
      }
    }
  }, [setupStatus, isLoading, navigate, location.pathname]);

  const startupId = setupStatus?.startup_id;
  useEffect(() => {
    if (!startupId) return;
    return subscribeToMigrationChecks(() => {
      if (hasMigrationCheckForStartup(startupId)) {
        setMigrationGateDismissedForStartup(startupId);
      }
    });
  }, [startupId]);
  const migrationCheckedForStartup = Boolean(
    startupId &&
      (hasMigrationCheckForStartup(startupId) ||
        migrationGateDismissedForStartup === startupId),
  );

  // A refresh of an app that already passed the gate renders straight away and
  // confirms the bootstrap in the background. If the backend has restarted
  // since, its new startup id brings the migration gate back once it arrives.
  if (isLoading && !setupStatus && hasAnyMigrationCheck() && location.pathname !== '/setup') {
    return <>{children}</>;
  }

  // Otherwise keep one startup gate mounted until the backend's setup state
  // is known, so a first visit never flashes the dashboard before its check.
  if (isLoading && !setupStatus) {
    return (
      <StartupSequence
        error={null}
        backendStartupId={null}
        canRunMigrationCheck={false}
        connectionAttempt={Math.max(1, failureCount + (isFetching ? 1 : 0))}
        isRetrying={isFetching}
        onRetry={retryBootstrap}
      />
    );
  }

  if (error && !setupStatus) {
    return (
      <StartupSequence
        error={error}
        backendStartupId={null}
        canRunMigrationCheck={false}
        connectionAttempt={Math.max(1, failureCount + (isFetching ? 1 : 0))}
        isRetrying={isFetching}
        onRetry={retryBootstrap}
      />
    );
  }

  // Even when already configured, run migration preview gate once per backend startup.
  if (setupStatus?.is_configured && !migrationCheckedForStartup) {
    return (
      <StartupSequence
        error={null}
        backendStartupId={startupId ?? null}
        canRunMigrationCheck
        onReady={() => {
          if (startupId) {
            setMigrationGateDismissedForStartup(startupId);
          }
          if (location.pathname === '/setup') {
            navigate('/', { replace: true });
          }
        }}
      />
    );
  }

  // If we're about to redirect, don't render children to avoid flash
  if (!setupStatus?.is_configured && location.pathname !== '/setup') {
    return null;
  }

  if (setupStatus?.is_configured && location.pathname === '/setup') {
    return null;
  }

  return <>{children}</>;
}
