import { connectionScopedKey } from '../../api/http';
import { readStorage, writeStorage } from '../../shared/lib/browserStorage';

const STARTUP_MIGRATION_KEY = 'usr_migration_done_startup_id';
// Each backend has its own startup id; switching between them keeps both.
const migrationKey = () => connectionScopedKey(STARTUP_MIGRATION_KEY);

export function hasMigrationCheckForStartup(startupId: string): boolean {
  return (
    readStorage(migrationKey()) === startupId ||
    readStorage(migrationKey(), 'session') === startupId
  );
}

/** Whether this browser has passed the migration gate for any backend startup. */
export function hasAnyMigrationCheck(): boolean {
  return Boolean(readStorage(migrationKey()) || readStorage(migrationKey(), 'session'));
}

export function recordMigrationCheckForStartup(startupId: string): void {
  writeStorage(migrationKey(), startupId);
  writeStorage(migrationKey(), startupId, 'session');
}

export function subscribeToMigrationChecks(listener: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === migrationKey()) listener();
  };
  window.addEventListener('storage', onStorage);
  return () => window.removeEventListener('storage', onStorage);
}
