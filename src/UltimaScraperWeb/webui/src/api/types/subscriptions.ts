export interface SubscriptionInfo {
  id: number;
  user_id: number;
  username: string | null;
  name: string | null;
  description: string | null;
  sex: number | null;
  gender?: number | null;
  profile_type?: number | null;
  sexual_content?: number | null;
  partner_sex?: number | null;
  partner_gender?: number | null;
  avatar_url: string | null;
  header_url: string | null;
  price: number;
  post_count: number;
  media_count: number;
  image_count: number;
  video_count: number;
  is_active: boolean;
  expires_at: string | null;
  watched?: boolean;
  ignored: boolean;
  site: string;
  favorite?: boolean;
  last_checked_at?: string | null;
}

export interface SubscriptionListResponse {
  success: boolean;
  subscriptions: SubscriptionInfo[];
  total: number;
  error?: string;
}

export interface SubscriptionStats {
  site: string;
  total: number;
  active: number;
  expired: number;
}
