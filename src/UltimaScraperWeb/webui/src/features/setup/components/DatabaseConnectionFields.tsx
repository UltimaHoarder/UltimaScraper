import type { DatabaseConnectionRequest } from '../../../api/types/setup';
import { SetupHint } from './SetupHint';

export interface DatabaseConnectionFieldsProps {
  dbConfig: DatabaseConnectionRequest;
  onChange: (cfg: DatabaseConnectionRequest) => void;
}

export function DatabaseConnectionFields({ dbConfig, onChange }: DatabaseConnectionFieldsProps) {
  const update = (field: keyof DatabaseConnectionRequest, value: string | number) =>
    onChange({ ...dbConfig, [field]: value });

  return (
    <>
      <div className="setup-form-row">
        <div className="setup-form-group">
          <label className="setup-form-label" htmlFor="setup-db-host">
            Host
            <SetupHint text="Address of the PostgreSQL server, as the backend sees it." />
          </label>
          <input
            id="setup-db-host"
            type="text"
            className="setup-form-input"
            value={dbConfig.host}
            onChange={(event) => update('host', event.target.value)}
            placeholder="localhost"
          />
        </div>
        <div className="setup-form-group">
          <label className="setup-form-label" htmlFor="setup-db-port">
            Port
            <SetupHint text="PostgreSQL listens on 5432 unless it was changed." />
          </label>
          <input
            id="setup-db-port"
            type="number"
            className="setup-form-input"
            value={dbConfig.port}
            onChange={(event) => update('port', parseInt(event.target.value, 10) || 5432)}
          />
        </div>
      </div>

      <div className="setup-form-group">
        <label className="setup-form-label" htmlFor="setup-db-name">
          Database Name
          <SetupHint text="Created for you if it does not exist yet, when the user is allowed to." />
        </label>
        <input
          id="setup-db-name"
          type="text"
          className="setup-form-input"
          value={dbConfig.name}
          onChange={(event) => update('name', event.target.value)}
          placeholder="ultima_archive"
        />
      </div>

      <div className="setup-form-group">
        <label className="setup-form-label" htmlFor="setup-db-username">
          Username
          <SetupHint text="Needs permission to create tables, because the test also prepares the schema." />
        </label>
        <input
          id="setup-db-username"
          type="text"
          className="setup-form-input"
          value={dbConfig.username}
          onChange={(event) => update('username', event.target.value)}
          placeholder="ultimascraper"
        />
      </div>

      <div className="setup-form-group">
        <label className="setup-form-label" htmlFor="setup-db-password">
          Password
        </label>
        <input
          id="setup-db-password"
          type="password"
          className="setup-form-input"
          value={dbConfig.password}
          onChange={(event) => update('password', event.target.value)}
          placeholder="••••••••"
        />
      </div>
    </>
  );
}
