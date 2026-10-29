export interface OrderedPerformerInfo {
  id: number;
  order_id: number;
  site: string;
  user_id: number;
  username: string | null;
  price: number | null;
  status: string;
  spender_user_id: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface OrderSummary {
  id: number;
  status: string;
  total_price: number | null;
  created_at: string;
  updated_at: string | null;
  item_count: number;
}

export interface OrderItemInfo {
  id: number;
  user_id: number;
  username: string | null;
  price: number | null;
  status: string;
  spender_user_id: number | null;
  spender_username: string | null;
  error_message: string | null;
}

export interface OrderListResponse {
  success: boolean;
  orders: OrderSummary[];
  total: number;
  error?: string | null;
}

export interface OrderDetailResponse {
  success: boolean;
  order: OrderSummary | null;
  items: OrderItemInfo[];
  error?: string | null;
}

export interface SpenderAssignment {
  auth_id: number;
  username: string | null;
  spender_type: string;
  balance: number;
  assigned_count: number;
  assigned_cost: number;
}

export interface CalculateOrderResponse {
  success: boolean;
  order: OrderSummary | null;
  items: OrderItemInfo[];
  spenders: SpenderAssignment[];
  unassigned_count: number;
  total_cost: number;
  error?: string | null;
}

export interface OrderedPerformerActionResponse {
  success: boolean;
  item?: OrderedPerformerInfo | null;
  error?: string | null;
}

export interface AssignSpenderRequest {
  spender_user_id: number | null;
}

export interface OrderedPerformerCreateRequest {
  site: string;
  user_id?: number | null;
  username?: string | null;
  price?: number | null;
  post_id?: number | null;
  content_type?: string | null;
  auto_execute?: boolean;
}

export interface OrderedPerformerCreateResponse {
  success: boolean;
  order_id?: number | null;
  ordered_performer_id?: number | null;
  site?: string | null;
  user_id?: number | null;
  username?: string | null;
  price?: number | null;
  spender_user_id?: number | null;
  status?: string | null;
  error?: string | null;
  message?: string | null;
}

export interface ListOrdersParams {
  status?: string;
  limit?: number;
  offset?: number;
}
