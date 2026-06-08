// Thin REST client. Every call carries the bearer token the backend printed on
// startup; it is kept in localStorage and entered once via the TokenGate.
import type { InventoryPut, PermissionRule, ServerRow, TaskEntry } from "./types";

const TOKEN_KEY = "jarvis_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t.trim());
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(init.headers || {}),
    },
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  postures: () => req<string[]>("/api/postures"),
  getInventory: () => req<{ servers: ServerRow[] }>("/api/inventory"),
  putInventory: (servers: ServerRow[]) =>
    req<{ servers: ServerRow[] }>("/api/inventory", {
      method: "PUT",
      body: JSON.stringify({ servers } satisfies InventoryPut),
    }),
  getPermissions: () => req<PermissionRule[]>("/api/permissions"),
  addPermission: (rule: { server: string; match: string; value: string; note: string }) =>
    req<PermissionRule[]>("/api/permissions", { method: "POST", body: JSON.stringify(rule) }),
  deletePermission: (index: number) =>
    req<PermissionRule[]>(`/api/permissions/${index}`, { method: "DELETE" }),
  getMemory: (server: string) =>
    req<{ server: string; facts: string; tasks: TaskEntry[] }>(
      `/api/servers/${encodeURIComponent(server)}/memory`,
    ),
  addFact: (server: string, note: string) =>
    req<{ server: string; facts: string; tasks: TaskEntry[] }>(
      `/api/servers/${encodeURIComponent(server)}/memory`,
      { method: "POST", body: JSON.stringify({ note }) },
    ),
  getTasks: (limit = 50, server?: string) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (server) q.set("server", server);
    return req<TaskEntry[]>(`/api/tasks?${q.toString()}`);
  },
};
