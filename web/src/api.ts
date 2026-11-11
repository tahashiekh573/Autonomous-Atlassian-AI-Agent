import type {
  CatalogEntry, Connection, ConnectionTest, Overview, RunDetail, RunSummary, User,
} from "./types";

const PREFIX = "/api/v1";
const TOKEN_KEY = "aaa.token";

export const UNREACHABLE = "api_unreachable";
const UNREACHABLE_MESSAGE =
  "The backend is not running. Start it with `npm start` (or `npm run api`) in the project folder.";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token lives only in memory for this page */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(path.startsWith("/health") ? path : PREFIX + path, { ...init, headers });
  } catch {
    throw new ApiError(0, UNREACHABLE, UNREACHABLE_MESSAGE);
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    // A non-JSON 5xx comes from the dev proxy, not our API: the backend is not running.
    if (body === null && response.status >= 500) {
      throw new ApiError(response.status, UNREACHABLE, UNREACHABLE_MESSAGE);
    }
    const err = body?.error ?? {};
    let message: string = err.message ?? response.statusText;
    // Validation errors: say which field and why, not just "Request validation failed."
    const fieldErrors: { loc?: unknown[]; msg?: string }[] = err.details?.errors ?? [];
    if (fieldErrors.length) {
      message += " " + fieldErrors
        .map((e) => `${(e.loc ?? []).filter((p) => p !== "body").join(".")}: ${e.msg}`)
        .join("; ");
    }
    throw new ApiError(response.status, err.code ?? "error", message);
  }
  return body as T;
}

const json = (data: unknown) => JSON.stringify(data);

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: json({ email, password }) }),
  me: () => request<User>("/auth/me"),

  connections: () => request<Connection[]>("/connections"),
  createConnection: (data: { name: string; site_url: string; email: string; api_token: string }) =>
    request<Connection>("/connections", { method: "POST", body: json(data) }),
  testConnection: (id: string) => request<ConnectionTest>(`/connections/${id}/test`, { method: "POST" }),
  overview: (id: string) => request<Overview>(`/connections/${id}/overview`),

  catalog: () => request<CatalogEntry[]>("/operations"),
  runs: (limit = 50) => request<RunSummary[]>(`/runs?limit=${limit}`),
  run: (id: string) => request<RunDetail>(`/runs/${id}`),
  createRun: (connectionId: string, text: string) =>
    request<RunDetail>("/runs", {
      method: "POST",
      body: json({ connection_id: connectionId, text }),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
  voiceCommand: (connectionId: string, audio: Blob) => {
    const form = new FormData();
    form.append("audio", audio, "command.webm");
    form.append("connection_id", connectionId);
    return request<RunDetail>("/voice/command", {
      method: "POST", body: form, headers: { "Idempotency-Key": crypto.randomUUID() },
    });
  },
  voiceCapabilities: () => request<{ stt: string | null; tts: string | null }>("/voice/capabilities"),
  approve: (id: string, operationIds?: string[]) =>
    request<RunDetail>(`/runs/${id}/approve`, { method: "POST", body: json({ operation_ids: operationIds ?? null }) }),
  reject: (id: string, reason: string) =>
    request<RunDetail>(`/runs/${id}/reject`, { method: "POST", body: json({ reason }) }),
  clarify: (id: string, answer: string) =>
    request<RunDetail>(`/runs/${id}/clarify`, { method: "POST", body: json({ answer }) }),
  health: () => request<{ status: string; database?: string }>("/health/ready"),
};
