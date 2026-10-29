import { createHttpClient } from './http';
import type {
  AssignSpenderRequest,
  CalculateOrderResponse,
  ListOrdersParams,
  OrderedPerformerActionResponse,
  OrderedPerformerCreateRequest,
  OrderedPerformerCreateResponse,
  OrderDetailResponse,
  OrderListResponse,
} from './types/orders';

const http = createHttpClient();

export async function listOrders(
  params?: ListOrdersParams,
): Promise<OrderListResponse> {
  const response = await http.get<OrderListResponse>('/api/v1/orders/', { params });
  return response.data;
}

export async function getOrder(orderId: number): Promise<OrderDetailResponse> {
  const response = await http.get<OrderDetailResponse>(`/api/v1/orders/${orderId}`);
  return response.data;
}

export async function createOrderedPerformer(
  request: OrderedPerformerCreateRequest,
): Promise<OrderedPerformerCreateResponse> {
  const response = await http.post<OrderedPerformerCreateResponse>(
    '/api/v1/orders/performers',
    request,
  );
  return response.data;
}

export async function assignOrderedPerformerSpender(
  id: number,
  request: AssignSpenderRequest,
): Promise<OrderedPerformerActionResponse> {
  const response = await http.patch<OrderedPerformerActionResponse>(
    `/api/v1/orders/performers/${id}/spender`,
    request,
  );
  return response.data;
}

export async function checkOrder(orderId: number): Promise<OrderDetailResponse> {
  const response = await http.post<OrderDetailResponse>(
    `/api/v1/orders/${orderId}/check`,
    undefined,
    { timeout: 90_000 },
  );
  return response.data;
}

export async function calculateOrder(
  orderId: number,
): Promise<CalculateOrderResponse> {
  const response = await http.post<CalculateOrderResponse>(
    `/api/v1/orders/${orderId}/calculate`,
    undefined,
    { timeout: 120_000 },
  );
  return response.data;
}

export async function executeOrder(orderId: number): Promise<OrderDetailResponse> {
  const response = await http.post<OrderDetailResponse>(
    `/api/v1/orders/${orderId}/execute`,
    undefined,
    { timeout: 300_000 },
  );
  return response.data;
}

export async function deleteOrderedPerformer(
  id: number,
): Promise<OrderDetailResponse> {
  const response = await http.delete<OrderDetailResponse>(`/api/v1/orders/performers/${id}`);
  return response.data;
}

export async function deleteOrderPerformers(
  orderId: number,
): Promise<OrderDetailResponse> {
  const response = await http.post<OrderDetailResponse>(
    `/api/v1/orders/${orderId}/performers/clear`,
  );
  return response.data;
}

export async function deleteOrder(orderId: number): Promise<OrderDetailResponse> {
  const response = await http.post<OrderDetailResponse>(
    `/api/v1/orders/${orderId}/delete`,
  );
  return response.data;
}
