import * as SecureStore from "expo-secure-store";

// Point this at the FastAPI backend (app/main.py). For a physical device on
// the same network as a locally-run backend, use the machine's LAN IP
// instead of localhost (the device can't resolve the dev machine's
// localhost). Override at build time via EXPO_PUBLIC_API_BASE_URL.
export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const TOKEN_KEY = "worker_access_token";
const ROLE_KEY = "worker_role";

export type Role = "tradie" | "sales" | "owner";

export async function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function setToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function clearToken(): Promise<void> {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
  await SecureStore.deleteItemAsync(ROLE_KEY);
}

// An account is exactly one role (app/auth.py::require_owner/require_sales)
// — persisted alongside the token so RootNavigator can pick the right
// stack immediately on app restart, not just right after a fresh login.
export async function getRole(): Promise<Role> {
  return ((await SecureStore.getItemAsync(ROLE_KEY)) as Role | null) ?? "tradie";
}

export async function setRole(role: Role): Promise<void> {
  await SecureStore.setItemAsync(ROLE_KEY, role);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiPostJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>(path, { method: "POST", body: form });
}
