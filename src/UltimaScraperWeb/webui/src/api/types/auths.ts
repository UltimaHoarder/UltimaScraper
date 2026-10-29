export interface AuthCredential {
  id: number;
  site: string;
  username: string | null;
  user_id: number;
  status: string;
  active: boolean;
  last_tested_at: string | null;
  created_at: string | null;
  cookie_preview: string | null;
  has_authorization: boolean;
  user_agent_preview: string | null;
  proxy_id: string | null;
  worker_shard: number | null;
  is_age_verified: boolean | null;
  age_verification_required: boolean | null;
  spend: boolean;
  spender_type: string | null;
}

export interface AuthListResponse {
  success: boolean;
  auths: AuthCredential[];
  total: number;
  error?: string;
}

export type AuthStatusFilter = 'valid' | 'invalid';

export interface AuthTestResult {
  success: boolean;
  status: string;
  message: string;
}

export interface AuthProxyTestResult {
  success: boolean;
  message: string;
  latency_ms?: number | null;
  skipped: boolean;
  return_ip?: string | null;
}

export interface AgeVerificationResponse {
  success: boolean;
  redirect_url: string | null;
  api_flow: string | null;
  error: string | null;
}

export interface AuthBalanceResponse {
  success: boolean;
  balance: number | null;
  error: string | null;
}

export interface AuthEditRequest {
  username?: string;
  cookie?: string;
  x_bc?: string;
  authorization?: string;
  user_agent?: string;
  active?: boolean;
  proxy_id?: string | null;
  spend?: boolean;
  spender_type?: string | null;
  email_notifications_enabled?: boolean | null;
}

export interface AuthActionResponse {
  success: boolean;
  message: string;
}

export interface AuthUpdateResponse {
  success: boolean;
  message: string;
  auth?: AuthCredential;
}

export interface ParsedCurlData {
  success: boolean;
  site: string;
  cookie: string | null;
  x_bc: string | null;
  authorization: string | null;
  user_agent: string | null;
  user_id: number | null;
  app_token: string | null;
  sess: string | null;
  auth_id: string | null;
  error: string | null;
  raw_headers: Record<string, string>;
}

export interface AddAuthFromCurlResponse {
  success: boolean;
  auth_id: number | null;
  username: string | null;
  user_id: number | null;
  error: string | null;
}
