export type ComputeMode = 'install' | 'none';
export type StoreMode = 'install' | 'existing' | 'none';
export type WebUIMode = 'reuse' | 'install';

export interface ComponentSelection {
  backend: ComputeMode;
  worker: ComputeMode;
  postgres: StoreMode;
  redis: StoreMode;
  webui: WebUIMode;
}

export const DEFAULT_COMPONENTS: ComponentSelection = {
  backend: 'install',
  worker: 'install',
  postgres: 'install',
  redis: 'install',
  webui: 'reuse',
};

export type ComponentErrorCode =
  | 'nothing_installed'
  | 'postgres_required'
  | 'redis_required'
  | 'worker_needs_existing_stores'
  | 'unused_existing_store';

export const ERROR_MESSAGES: Record<ComponentErrorCode, string> = {
  nothing_installed: 'Choose at least one component to install.',
  postgres_required: 'Without the bundled PostgreSQL, give the database URL to use.',
  redis_required: 'Without the bundled Redis, give the Redis host to use.',
  worker_needs_existing_stores:
    "A worker installed without a backend must use that backend's existing PostgreSQL and Redis.",
  unused_existing_store: 'Existing PostgreSQL or Redis can only be used when installing a backend or worker.',
};

export interface CardRule<M extends string> {
  allowed: M[];
  disabled_reasons: Partial<Record<M, string>>;
  shared_stores_with_backend?: boolean;
  requires_backend_connection?: boolean;
  publishes_port_when_installed?: boolean;
}

export interface AllCardRules {
  backend: CardRule<ComputeMode>;
  worker: CardRule<ComputeMode>;
  postgres: CardRule<StoreMode>;
  redis: CardRule<StoreMode>;
  webui: CardRule<WebUIMode>;
}

export const CARD_RULES_BY_COMPUTE: Record<string, AllCardRules> = {
  'install:install': {
    backend: { allowed: ['install', 'none'], disabled_reasons: {} },
    worker: { allowed: ['install', 'none'], disabled_reasons: {}, shared_stores_with_backend: true },
    postgres: {
      allowed: ['install', 'existing'],
      disabled_reasons: { none: 'Backend needs PostgreSQL' },
    },
    redis: {
      allowed: ['install', 'existing'],
      disabled_reasons: { none: 'Backend needs Redis' },
    },
    webui: { allowed: ['reuse', 'install'], disabled_reasons: {} },
  },
  'install:none': {
    backend: { allowed: ['install', 'none'], disabled_reasons: {} },
    worker: { allowed: ['install', 'none'], disabled_reasons: {}, shared_stores_with_backend: false },
    postgres: {
      allowed: ['install', 'existing'],
      disabled_reasons: { none: 'Backend needs PostgreSQL' },
    },
    redis: {
      allowed: ['install', 'existing'],
      disabled_reasons: { none: 'Backend needs Redis' },
    },
    webui: { allowed: ['reuse', 'install'], disabled_reasons: {} },
  },
  'none:install': {
    backend: { allowed: ['install', 'none'], disabled_reasons: {} },
    worker: {
      allowed: ['install', 'none'],
      disabled_reasons: {},
      shared_stores_with_backend: false,
      requires_backend_connection: true,
    },
    postgres: {
      allowed: ['existing'],
      disabled_reasons: {
        install: "Worker without a backend must use the existing backend's PostgreSQL",
        none: 'Worker needs PostgreSQL',
      },
    },
    redis: {
      allowed: ['existing'],
      disabled_reasons: {
        install: "Worker without a backend must use the existing backend's Redis",
        none: 'Worker needs Redis',
      },
    },
    webui: { allowed: ['reuse', 'install'], disabled_reasons: {} },
  },
  'none:none': {
    backend: { allowed: ['install', 'none'], disabled_reasons: {} },
    worker: { allowed: ['install', 'none'], disabled_reasons: {}, shared_stores_with_backend: false },
    postgres: {
      allowed: ['install', 'none'],
      disabled_reasons: { existing: 'Existing PostgreSQL is only used with Backend or Worker' },
      publishes_port_when_installed: true,
    },
    redis: {
      allowed: ['install', 'none'],
      disabled_reasons: { existing: 'Existing Redis is only used with Backend or Worker' },
      publishes_port_when_installed: true,
    },
    webui: { allowed: ['reuse', 'install'], disabled_reasons: {} },
  },
};

export function getCardRules(selection: Pick<ComponentSelection, 'backend' | 'worker'>): AllCardRules {
  const key = `${selection.backend}:${selection.worker}`;
  return CARD_RULES_BY_COMPUTE[key] ?? CARD_RULES_BY_COMPUTE['install:install'];
}

export interface ValidationResult {
  valid: boolean;
  error_code: ComponentErrorCode | null;
  message: string | null;
}

export function validateComponentModes(selection: ComponentSelection): ValidationResult {
  const { backend, worker, postgres, redis, webui } = selection;
  const hasCompute = backend === 'install' || worker === 'install';

  if (hasCompute && postgres === 'none') {
    return { valid: false, error_code: 'postgres_required', message: ERROR_MESSAGES.postgres_required };
  }
  if (hasCompute && redis === 'none') {
    return { valid: false, error_code: 'redis_required', message: ERROR_MESSAGES.redis_required };
  }
  if (backend === 'none' && worker === 'install' && (postgres !== 'existing' || redis !== 'existing')) {
    return {
      valid: false,
      error_code: 'worker_needs_existing_stores',
      message: ERROR_MESSAGES.worker_needs_existing_stores,
    };
  }
  if (!hasCompute && (postgres === 'existing' || redis === 'existing')) {
    return {
      valid: false,
      error_code: 'unused_existing_store',
      message: ERROR_MESSAGES.unused_existing_store,
    };
  }
  const anyInstalled =
    backend === 'install' ||
    worker === 'install' ||
    postgres === 'install' ||
    redis === 'install' ||
    webui === 'install';
  if (!anyInstalled) {
    return { valid: false, error_code: 'nothing_installed', message: ERROR_MESSAGES.nothing_installed };
  }
  return { valid: true, error_code: null, message: null };
}

export const validateComponents = validateComponentModes;

/**
 * Updates a component mode and coerces dependent PostgreSQL/Redis modes when
 * switching Backend or Worker makes their previous mode disallowed.
 */
export function applyComponentChange(
  current: ComponentSelection,
  card: keyof ComponentSelection,
  nextMode: string,
  defaults: { postgres: StoreMode; redis: StoreMode } = { postgres: 'install', redis: 'install' },
): ComponentSelection {
  const updated: ComponentSelection = { ...current, [card]: nextMode } as ComponentSelection;
  const rules = getCardRules(updated);

  if (!rules.postgres.allowed.includes(updated.postgres)) {
    updated.postgres = rules.postgres.allowed.includes(defaults.postgres)
      ? defaults.postgres
      : rules.postgres.allowed[0];
  }
  if (!rules.redis.allowed.includes(updated.redis)) {
    updated.redis = rules.redis.allowed.includes(defaults.redis)
      ? defaults.redis
      : rules.redis.allowed[0];
  }
  return updated;
}

/**
 * The wizard shows Backend and Worker as one card. They stay separate
 * containers (workers scale out to other hosts); the card picks the pair:
 *   backend: backend + worker here · worker: a worker joining an existing
 *   backend · none: neither on this host.
 */
export type ComputeChoice = 'backend' | 'worker' | 'none';

export const COMPUTE_CHOICES: ComputeChoice[] = ['backend', 'worker', 'none'];

export const COMPUTE_LABELS: Record<ComputeChoice, string> = {
  backend: 'Install here',
  worker: 'Worker only',
  none: 'Not here',
};

export function computeChoice(selection: Pick<ComponentSelection, 'backend' | 'worker'>): ComputeChoice {
  if (selection.backend === 'install') return 'backend';
  return selection.worker === 'install' ? 'worker' : 'none';
}

export function applyComputeChoice(
  current: ComponentSelection,
  choice: ComputeChoice,
  defaults?: { postgres: StoreMode; redis: StoreMode },
): ComponentSelection {
  const backend: ComputeMode = choice === 'backend' ? 'install' : 'none';
  const worker: ComputeMode = choice === 'none' ? 'none' : 'install';
  return applyComponentChange({ ...current, backend }, 'worker', worker, defaults);
}
