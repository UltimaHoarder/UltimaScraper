import type { RedisConnectionRequest } from '../../../api/types/setup';
import { SetupHint } from './SetupHint';

export interface RedisConnectionFieldsProps {
  redisConfig: RedisConnectionRequest;
  onChange: (cfg: RedisConnectionRequest) => void;
  showDbIndex?: boolean;
}

export function RedisConnectionFields({
  redisConfig,
  onChange,
  showDbIndex = true,
}: RedisConnectionFieldsProps) {
  const update = (field: keyof RedisConnectionRequest, value: string | number) =>
    onChange({ ...redisConfig, [field]: value });

  return (
    <>
      <div className="setup-form-row">
        <div className="setup-form-group">
          <label className="setup-form-label" htmlFor="setup-redis-host">
            Host
            <SetupHint text="Address of the Redis server, as the backend sees it. In Docker the bundled server is called redis, not localhost." />
          </label>
          <input
            id="setup-redis-host"
            type="text"
            className="setup-form-input"
            value={redisConfig.host}
            onChange={(event) => update('host', event.target.value)}
            placeholder="localhost"
          />
        </div>
        <div className="setup-form-group">
          <label className="setup-form-label" htmlFor="setup-redis-port">
            Port
            <SetupHint text="Redis listens on 6379 unless it was changed." />
          </label>
          <input
            id="setup-redis-port"
            type="number"
            className="setup-form-input"
            value={redisConfig.port}
            onChange={(event) => update('port', parseInt(event.target.value, 10) || 6379)}
          />
        </div>
      </div>

      {showDbIndex && (
        <div className="setup-form-group">
          <label className="setup-form-label" htmlFor="setup-redis-db">
            Database Index
            <SetupHint text="Redis keeps numbered databases. Use a separate one if other apps share this server." />
          </label>
          <input
            id="setup-redis-db"
            type="number"
            className="setup-form-input"
            value={redisConfig.db}
            onChange={(event) => update('db', parseInt(event.target.value, 10) || 0)}
          />
        </div>
      )}

      <div className="setup-form-group">
        <label className="setup-form-label" htmlFor="setup-redis-password">
          Password (Optional)
        </label>
        <input
          id="setup-redis-password"
          type="password"
          className="setup-form-input"
          value={redisConfig.password || ''}
          onChange={(event) => update('password', event.target.value)}
          placeholder="••••••••"
        />
      </div>
    </>
  );
}
