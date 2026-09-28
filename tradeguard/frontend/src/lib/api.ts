function apiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined") return `${window.location.protocol}//${window.location.hostname}:8000`;
  return "http://127.0.0.1:8000";
}

const API = apiBase();

export type User = {
  id: string;
  email: string;
  full_name: string;
  organization_id: string;
  roles: string[];
};

function accessToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("tg_access");
}

export function saveSession(token: string) {
  sessionStorage.setItem("tg_access", token);
}

export function clearSession() {
  sessionStorage.removeItem("tg_access");
}

let refreshTask: Promise<boolean> | null = null;

function refreshAccess(): Promise<boolean> {
  if (refreshTask) return refreshTask;
  refreshTask = fetch(`${API}/api/v1/auth/refresh`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: { "X-Tradeguard-Request": "1" },
  })
    .then(async (refreshed) => {
      if (!refreshed.ok) return false;
      const body = await refreshed.json();
      if (typeof body.access_token === "string") saveSession(body.access_token);
      return typeof body.access_token === "string";
    })
    .catch(() => false)
    .finally(() => {
      refreshTask = null;
    });
  return refreshTask;
}

export async function api(path: string, options: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set("X-Tradeguard-Request", "1");
  headers.set("Cache-Control", "no-store");
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = accessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const method = (options.method || "GET").toUpperCase();
  const freshPath = method === "GET" ? `${path}${path.includes("?") ? "&" : "?"}_=${Date.now()}` : path;
  const response = await fetch(`${API}${freshPath}`, { ...options, headers, credentials: "include", cache: "no-store" });
  if (response.status === 401 && retry && !path.startsWith("/api/v1/auth/login") && !path.startsWith("/api/v1/auth/refresh")) {
    const refreshed = await refreshAccess();
    if (refreshed) return api(path, options, false);
  }
  return response;
}

export async function apiJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await api(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Request failed";
    throw new Error(detail);
  }
  return body as T;
}
