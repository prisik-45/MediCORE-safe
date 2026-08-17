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
      (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1")
    ) {
      parsed.hostname = window.location.hostname === "127.0.0.1" ? "127.0.0.1" : "localhost";
      return parsed.toString().replace(/\/$/, "");
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
    return normalizeBrowserUrl(process.env.NEXT_PUBLIC_API_URL).replace(/\/$/, "");
  }

  if (typeof window === "undefined") {
    return "http://127.0.0.1:8000";
  }

  const hostname = window.location.hostname;
  if (isLocalHostname(hostname)) {
    return `${window.location.protocol}//${hostname}:8000`;
  }

  return `${window.location.origin}`;
}

export function getChatWsUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL;
    if (typeof window !== "undefined" && window.location.protocol === "https:" && wsUrl.startsWith("ws://")) {
      return `wss://${wsUrl.slice("ws://".length)}`;
    }
    return wsUrl;
  }

  if (typeof window === "undefined") {
    return "ws://127.0.0.1:8000/ws/chat";
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const hostname = window.location.hostname;
  if (isLocalHostname(hostname)) {
    return `${protocol}//${hostname}:8000${CHAT_WS_PATH}`;
  }

  return `${protocol}//${window.location.host}${CHAT_WS_PATH}`;
}
