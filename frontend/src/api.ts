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
