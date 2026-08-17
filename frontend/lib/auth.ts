import { getApiBaseUrl } from "@/lib/api";

export type SessionProfile = {
  id: string;
  email?: string;
  role?: string;
  tenant_id?: string;
  status?: string;
  full_name?: string;
  organisation?: string;
};

export async function authFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {});
  return fetch(input, {
    ...init,
    credentials: "include",
    headers,
  });
}

export async function loginWithPassword(email: string, password: string) {
  const response = await authFetch(`${getApiBaseUrl()}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || "Invalid email or password.");
  }
  return response.json();
}

export async function logoutSession() {
  await authFetch(`${getApiBaseUrl()}/api/auth/logout`, { method: "POST" }).catch(() => undefined);
}

export async function getSessionProfile(): Promise<SessionProfile | null> {
  const response = await authFetch(`${getApiBaseUrl()}/api/profile`);
  if (!response.ok) return null;
  return response.json();
}

export async function changePassword(password: string) {
  const response = await authFetch(`${getApiBaseUrl()}/api/auth/change-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || "Failed to update password.");
  }
  return response.json();
}
