import { readSSE } from "./sse";
import type {
  AccountOverview,
  AuditEntry,
  ChatStreamEvent,
  Conversation,
  DemoAccount,
  QueueStats,
  Refund,
  Ticket,
  TicketStatus,
  TokenResponse,
  TranscriptMessage,
  User,
} from "./types";

const BASE = "/api/v1";
const TOKEN_KEY = "nimbus.token";

/** An error carrying the server's RFC 7807 detail, safe to show to the user. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export const tokenStore = {
  get: (): string | null => {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string | null) => {
    try {
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable: session only lasts this page */
    }
  },
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 401) onUnauthorized();
  if (res.status === 429) {
    const after = res.headers.get("retry-after");
    if (after) message = `${message} Try again in ${after}s.`;
  }
  return new ApiError(res.status, message);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const res = await fetch(BASE + path, { ...init, headers });
  if (!res.ok) throw await errorFrom(res);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  login: (email: string, password: string) => post<TokenResponse>("/auth/login", { email, password }),
  me: () => request<User>("/auth/me"),
  demoAccounts: () => request<DemoAccount[]>("/auth/demo-accounts"),

  account: () => request<AccountOverview>("/me/account"),
  conversations: () => request<Conversation[]>("/conversations"),
  createConversation: () => post<Conversation>("/conversations"),
  transcript: (id: string) => request<TranscriptMessage[]>(`/conversations/${id}/messages`),

  /** Streams one turn. Yields typed events until the server sends `done`. */
  async *sendMessage(id: string, content: string, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    const res = await fetch(`${BASE}/conversations/${id}/messages`, {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${tokenStore.get() ?? ""}`,
      },
      body: JSON.stringify({ content }),
    });
    if (!res.ok || !res.body) throw await errorFrom(res);
    for await (const msg of readSSE(res.body)) {
      yield { type: msg.event, data: JSON.parse(msg.data) } as ChatStreamEvent;
    }
  },

  admin: {
    stats: () => request<QueueStats>("/admin/stats"),
    refunds: (status?: Refund["status"]) =>
      request<Refund[]>(`/admin/refunds${status ? `?status=${status}` : ""}`),
    decideRefund: (id: string, approve: boolean, note?: string) =>
      post<Refund>(`/admin/refunds/${id}/decision`, { approve, note: note || null }),
    tickets: (status?: TicketStatus) => request<Ticket[]>(`/admin/tickets${status ? `?status=${status}` : ""}`),
    setTicketStatus: (id: string, status: TicketStatus) =>
      request<Ticket>(`/admin/tickets/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    audit: (limit = 100) => request<AuditEntry[]>(`/admin/audit?limit=${limit}`),
  },
};
