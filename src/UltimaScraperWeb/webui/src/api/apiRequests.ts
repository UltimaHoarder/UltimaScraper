import { createHttpClient } from './http';

const http = createHttpClient();

export interface ApiMethodArg {
  type: string;
  description: string;
  required: boolean;
  default?: unknown;
  options?: string[];
}

export interface ApiMethodSpec {
  method: string;
  description: string;
  args: Record<string, ApiMethodArg>;
}

export interface ApiMethodsResponse {
  methods: Record<string, ApiMethodSpec>;
}

export interface ApiRequestExecutePayload {
  site: string;
  auth_id: number;
  method: string;
  args: Record<string, unknown>;
}

export interface ApiRequestResponse {
  success: boolean;
  method: string;
  data?: unknown;
  error?: string | null;
}

export async function getApiMethods(): Promise<ApiMethodsResponse> {
  const response = await http.get<ApiMethodsResponse>('/api/v1/api-requests/methods');
  return response.data;
}

export async function executeApiMethod(
  payload: ApiRequestExecutePayload,
): Promise<ApiRequestResponse> {
  const response = await http.post<ApiRequestResponse>(
    '/api/v1/api-requests/execute',
    payload,
  );
  return response.data;
}
