const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5726/api/v1";

export type AdminStatus = "active" | "restricted" | "disabled";
export type UserStatus = "active" | "restricted" | "disabled";

export type Admin = {
  id: string;
  email: string;
  display_name: string | null;
  status: AdminStatus;
  created_at: string;
  updated_at: string;
};

export type AdminTokenResponse = {
  access_token: string;
  token_type: "bearer";
  admin: Admin;
};

export type AdminCreatePayload = {
  email: string;
  password: string;
  display_name: string | null;
  status: AdminStatus;
};

export type AdminUpdatePayload = {
  display_name?: string | null;
  status?: AdminStatus;
  new_password?: string | null;
};

export type ConsoleUser = {
  id: string;
  email: string;
  display_name: string | null;
  status: UserStatus;
  created_at: string;
  updated_at: string;
  wechat_account: ConsoleWechatAccount | null;
};

export type ConsoleUserDetail = ConsoleUser & {
  wechat_accounts: ConsoleWechatAccount[];
  sources: ConsoleSource[];
};

export type ConsoleUserUpdatePayload = {
  display_name?: string | null;
  status?: UserStatus;
  new_password?: string | null;
};

export type ConsoleWechatAccount = {
  id: string;
  nickname: string;
  avatar_url: string | null;
  username: string | null;
  biz: string | null;
  token_status: "valid" | "expired" | "invalid" | "unknown";
  is_active: boolean;
  last_verified_at: string | null;
  expires_at: string | null;
};

export type ConsoleSource = {
  id: string;
  name: string;
  alias: string | null;
  avatar_url: string | null;
  description: string | null;
  status: "active" | "paused" | "failed";
  auto_fetch_enabled: boolean;
  last_list_fetched_at: string | null;
  article_count: number;
};

export type ConsoleArticleSource = {
  id: string;
  name: string;
  avatar_url: string | null;
  avatar_asset_url: string | null;
};

export type ConsoleArticle = {
  id: string;
  title: string;
  digest: string | null;
  cover_url: string | null;
  cover_asset_url: string | null;
  original_url: string;
  publish_time: string | null;
  content_status: "pending" | "running" | "fetched" | "failed";
  source: ConsoleArticleSource;
  created_at: string;
  updated_at: string;
};

export type ConsoleArticleDetail = ConsoleArticle & {
  content_clean_html: string | null;
  content_plain_text: string | null;
};

export type ConsoleArticleListResponse = {
  items: ConsoleArticle[];
  total: number;
  page: number;
  page_size: number;
};

export function getApiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  if (/^https?:\/\//i.test(API_BASE_URL)) {
    const baseUrl = new URL(API_BASE_URL);
    return `${baseUrl.origin}${path}`;
  }
  return path;
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    const message = errorBody?.detail || `Request failed with status ${response.status}`;
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export function getAuthHeaders(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
  };
}
