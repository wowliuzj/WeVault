const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5726/api/v1";

export type User = {
  id: string;
  email: string;
  display_name: string | null;
  status: "active" | "restricted" | "disabled";
};

export type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  user: User;
};

export type WechatAccount = {
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

export type WechatLoginSession = {
  login_id: string;
  status: "waiting_scan" | "scanned" | "confirmed" | "expired" | "failed";
  qr_url: string | null;
  expires_at: string;
  message: string | null;
};

export type WechatSource = {
  id: string;
  name: string;
  alias: string | null;
  fakeid: string | null;
  biz: string | null;
  avatar_url: string | null;
  avatar_asset_url: string | null;
  description: string | null;
  source_from: "search" | "article_url" | "manual";
  status: "active" | "paused" | "failed";
  auto_fetch_content: boolean;
  last_article_at: string | null;
  last_list_fetched_at: string | null;
  last_content_fetched_at: string | null;
  article_count: number;
};

export type SourceSearchItem = {
  name: string;
  alias: string | null;
  fakeid: string | null;
  biz: string | null;
  avatar_url: string | null;
  description: string | null;
  raw_data: Record<string, unknown> | null;
  already_added: boolean;
};

export type SourceSearchResponse = {
  keyword: string;
  items: SourceSearchItem[];
};

export type CollectionTask = {
  id: string;
  task_type: "fetch_source_articles" | "fetch_article_content" | "export_articles";
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  progress_current: number;
  progress_total: number;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown> | null;
  note: string;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type ArticleSource = {
  id: string;
  name: string;
  avatar_url: string | null;
  avatar_asset_url: string | null;
};

export type Article = {
  id: string;
  title: string;
  author: string | null;
  digest: string | null;
  cover_url: string | null;
  cover_asset_url: string | null;
  original_url: string;
  publish_time: string | null;
  content_status: "pending" | "running" | "fetched" | "failed";
  deleted_at: string | null;
  source: ArticleSource;
  created_at: string;
  updated_at: string;
};

export type ArticleDetail = Article & {
  content_clean_html: string | null;
  content_plain_text: string | null;
  content_markdown: string | null;
  content_fetched_at: string | null;
};

export type ArticleListResponse = {
  items: Article[];
  total: number;
  page: number;
  page_size: number;
};

export type ArticleSummaryResponse = {
  total: number;
  content_fetched: number;
  recent: Article[];
};

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

export function getApiUrl(path: string): string {
  const baseUrl = new URL(API_BASE_URL);
  return `${baseUrl.origin}${path}`;
}

export function getSourceAvatarUrl(
  source: { avatar_asset_url?: string | null; avatar_url: string | null },
): string {
  if (source.avatar_asset_url) {
    return getApiUrl(source.avatar_asset_url);
  }
  const url = source.avatar_url;
  if (!url) {
    return "";
  }
  return `${API_BASE_URL}/sources/avatar?url=${encodeURIComponent(url)}`;
}

export function getArticleCoverUrl(article: {
  cover_asset_url?: string | null;
  cover_url: string | null;
}): string {
  if (article.cover_asset_url) {
    return getApiUrl(article.cover_asset_url);
  }
  const url = article.cover_url;
  if (!url) {
    return "";
  }
  return `${API_BASE_URL}/articles/cover?url=${encodeURIComponent(url)}`;
}
