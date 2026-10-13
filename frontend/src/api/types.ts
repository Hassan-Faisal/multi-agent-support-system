// Mirrors backend/src/support/api/schemas.py and domain/schemas.py.

export type Role = "customer" | "agent";
export type AgentName = "billing" | "technical" | "orders" | "escalation";
export type Speaker = AgentName | "triage" | "guardrail";

export interface User {
  id: string;
  role: Role;
  display_name: string;
  customer_id: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface DemoAccount {
  email: string;
  password: string;
  role: Role;
  display_name: string;
  blurb: string;
}

export interface Source {
  source: string;
  title: string;
  url: string;
}

export interface TranscriptMessage {
  id: string | null;
  role: "customer" | "assistant";
  agent: Speaker | null;
  content: string;
  sources: Source[];
}

export interface Conversation {
  id: string;
  customer_id: string;
  title: string;
  active_agent: AgentName | null;
  created_at: string;
  updated_at: string;
}

// ---- trace events (backend/src/support/agents/graph.py)
export type TraceEvent =
  | { type: "route"; agent: AgentName | "none"; reason: string }
  | { type: "handoff"; source: AgentName; target: AgentName; reason: string }
  | {
      type: "tool";
      agent: AgentName;
      tool: string;
      args: Record<string, unknown>;
      outcome: string;
      ms: number;
    }
  | { type: "sources"; agent: AgentName; sources: Source[] }
  | { type: "guardrail"; kind: string; detail?: unknown; score?: number };

// ---- SSE events (backend/src/support/api/chat.py)
export type ChatStreamEvent =
  | { type: "token"; data: { agent: AgentName; text: string } }
  | { type: "trace"; data: TraceEvent }
  | { type: "message"; data: { message: TranscriptMessage; active_agent: AgentName | null } }
  | { type: "error"; data: { message: string } }
  | { type: "done"; data: Record<string, never> };

// ---- account
export interface ReturnOut {
  id: string;
  order_id: string;
  reason: string;
  status: string;
  created_at: string;
}

export interface Order {
  id: string;
  status: "processing" | "in_transit" | "delayed" | "delivered" | "cancelled";
  total: string;
  items: string[];
  placed_at: string;
  carrier: string | null;
  tracking_number: string | null;
  eta: string | null;
  delivered_at: string | null;
  returns: ReturnOut[];
}

export interface Refund {
  id: string;
  invoice_id: string;
  customer_id: string;
  amount: string;
  reason: string;
  status: "approved" | "pending_approval" | "rejected";
  ticket_id: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface Invoice {
  id: string;
  amount: string;
  status: "paid" | "overdue" | "void";
  description: string;
  issued_at: string;
  refunds: Refund[];
}

export type TicketStatus = "open" | "in_progress" | "resolved";

export interface Ticket {
  id: string;
  customer_id: string;
  conversation_id: string | null;
  category: string;
  priority: "low" | "normal" | "high" | "urgent";
  status: TicketStatus;
  summary: string;
  created_at: string;
  updated_at: string;
}

export interface AccountOverview {
  customer: { id: string; name: string; email: string; plan: string; member_since: string };
  orders: Order[];
  invoices: Invoice[];
  tickets: Ticket[];
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  customer_id: string | null;
  data: Record<string, unknown>;
}

export interface QueueStats {
  open_tickets: number;
  urgent_tickets: number;
  pending_refunds: number;
  conversations: number;
}
