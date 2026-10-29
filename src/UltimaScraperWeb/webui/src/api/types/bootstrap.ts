export interface SupportMatrix {
  ui_mode: 'webui';
  tui_supported: boolean;
  runtime_database: 'postgresql';
  postgres_required: boolean;
  sqlite_runtime_supported: boolean;
  sqlite_import_supported: boolean;
}

export interface BootstrapFeatures {
  webhook_stream: boolean;
  startup_migrations: boolean;
  distributed_mode: boolean;
  remote_backends: boolean;
  system_bootstrap: boolean;
}

export interface SetupSummary {
  is_configured: boolean;
  has_config: boolean;
  has_database: boolean;
  data_directory: string;
  startup_id: string;
}

export interface SystemBootstrapResponse {
  backend_id: string;
  hostname: string;
  version: string;
  supported_sites: string[];
  setup: SetupSummary;
  features: BootstrapFeatures;
  support_matrix: SupportMatrix;
}
