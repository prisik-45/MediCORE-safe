import { getApiBaseUrl } from "@/lib/api";

type AuthResponse<T> = Promise<{ data: T; error: Error | null }>;

async function backendFetch(path: string, init: RequestInit = {}) {
  return fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    credentials: "include",
  });
}

async function profileSession() {
  const response = await backendFetch("/api/profile");
  if (!response.ok) {
    return { session: null };
  }
  const profile = await response.json();
  return {
    session: {
      access_token: "",
      user: {
        id: profile.id,
        email: profile.email,
        user_metadata: {
          full_name: profile.full_name,
          organisation: profile.organisation,
          role: profile.role,
        },
      },
    },
  };
}

export const supabase = {
  auth: {
    async signInWithPassword(payload: { email: string; password: string }): AuthResponse<any> {
      const response = await backendFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        return { data: {}, error: new Error(detail.detail || "Invalid email or password.") };
      }
      const data = await profileSession();
      return { data, error: null };
    },
    async getSession(): AuthResponse<{ session: any | null }> {
      const data = await profileSession();
      return { data, error: null };
    },
    onAuthStateChange(_callback?: (event: string, session: any | null) => void) {
      return {
        data: {
          subscription: {
            unsubscribe() {},
          },
        },
      };
    },
    async signOut(): AuthResponse<{}> {
      await backendFetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
      return { data: {}, error: null };
    },
    async updateUser(payload: { data?: { full_name?: string }; password?: string; current_password?: string }): AuthResponse<any> {
      if (payload.password) {
        const response = await backendFetch("/api/auth/change-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ current_password: payload.current_password, password: payload.password }),
        });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          return { data: null, error: new Error(detail.detail || "Failed to update password.") };
        }
      }
      if (payload.data?.full_name) {
        const response = await backendFetch("/api/profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ full_name: payload.data.full_name }),
        });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          return { data: null, error: new Error(detail.detail || "Failed to update profile.") };
        }
      }
      const data = await profileSession();
      return { data, error: null };
    },
  },
};
