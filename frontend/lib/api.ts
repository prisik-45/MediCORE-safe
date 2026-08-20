const CHAT_WS_PATH = "/ws/chat";

function isLocalHostname(hostname: string) {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "0.0.0.0" ||
    hostname.startsWith("192.168.") ||
    hostname.startsWith("10.") ||
    hostname.startsWith("172.") ||
    hostname.endsWith(".local")
  );
}

function normalizeBrowserUrl(url: string) {
  if (typeof window === "undefined") {
    return url;
  }

  try {
    const parsed = new URL(url);
    if (
      isLocalHostname(window.location.hostname) &&
      (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" || parsed.hostname === "api")
    ) {
      return "";
    }

    if (window.location.protocol === "https:" && url.startsWith("http://") && !isLocalHostname(parsed.hostname)) {
      parsed.protocol = "https:";
      return parsed.toString().replace(/\/$/, "");
    }
  } catch {
    return url;
  }

  return url;
}

export function getApiBaseUrl() {
  if (process.env.NEXT_PUBLIC_API_URL) {
    const envUrl = process.env.NEXT_PUBLIC_API_URL.trim();
    if (typeof window !== "undefined") {
      try {
        const parsed = new URL(envUrl);
        // If NEXT_PUBLIC_API_URL points to port 8000 or internal docker hostname 'api', use relative path
        if (parsed.port === "8000" || parsed.hostname === "api" || parsed.hostname === "backend") {
          return "";
        }
      } catch {
        // Relative URL format
      }
    }
    return normalizeBrowserUrl(envUrl).replace(/\/$/, "");
  }

  // In browser, return empty string so browser requests use relative paths /api/...
  if (typeof window !== "undefined") {
    return "";
  }

  // Next.js SSR inside Docker container
  return "http://api:8000";
}

export function getApiErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") {
    return fallback;
  }

  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === "object") {
          const entry = item as { msg?: unknown; message?: unknown };
          if (typeof entry.msg === "string") return entry.msg;
          if (typeof entry.message === "string") return entry.message;
        }
        return "";
      })
      .filter(Boolean);

    if (messages.length > 0) {
      return messages.join(" ");
    }
  }

  if (detail && typeof detail === "object") {
    const entry = detail as { msg?: unknown; message?: unknown };
    if (typeof entry.msg === "string") return entry.msg;
    if (typeof entry.message === "string") return entry.message;
  }

  return fallback;
}

export function getChatWsUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL.trim();
    if (typeof window !== "undefined") {
      try {
        const parsed = new URL(wsUrl);
        if (parsed.port === "8000" || parsed.hostname === "api" || parsed.hostname === "backend") {
          const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
          return `${protocol}//${window.location.host}${CHAT_WS_PATH}`;
        }
      } catch {
        // Relative WS path
      }
    }
    return wsUrl;
  }

  if (typeof window === "undefined") {
    return "ws://api:8000/ws/chat";
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${CHAT_WS_PATH}`;
}
