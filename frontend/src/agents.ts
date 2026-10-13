import type { AgentName, Speaker, TraceEvent } from "./api/types";

export type Line = AgentName | "desk";

export const LINES: { id: Line; name: string; handles: string }[] = [
  { id: "desk", name: "Front desk", handles: "Reads your message and picks a specialist" },
  { id: "billing", name: "Billing", handles: "Invoices, charges, refunds" },
  { id: "technical", name: "Technical", handles: "Sign-in, crashes, sync, API" },
  { id: "orders", name: "Orders", handles: "Shipping, returns, warranty" },
  { id: "escalation", name: "Human team", handles: "Hands off to support staff" },
];

const SPEAKER_NAMES: Record<Speaker, string> = {
  billing: "Billing",
  technical: "Technical support",
  orders: "Orders & shipping",
  escalation: "Human team liaison",
  triage: "Front desk",
  guardrail: "Nimbus Help",
};

export const speakerName = (s: Speaker | null) => (s ? SPEAKER_NAMES[s] : "Nimbus Help");

/** CSS custom property holding a speaker's line colour. */
export const lineColor = (s: Speaker | Line | null): string => {
  switch (s) {
    case "billing":
    case "technical":
    case "orders":
    case "escalation":
      return `var(--line-${s})`;
    default:
      return "var(--line-desk)";
  }
};

/** The switchboard path of a turn: where it entered and every handoff after that. */
export function pathOf(events: TraceEvent[], fallback: AgentName | null): Line[] {
  const path: Line[] = [];
  for (const e of events) {
    if (e.type === "route") {
      path.push("desk");
      if (e.agent !== "none") path.push(e.agent);
    } else if (e.type === "handoff") {
      if (!path.length) path.push(e.source);
      path.push(e.target);
    } else if (e.type === "guardrail" && (e.kind === "handoff_limit" || e.kind === "tool_step_limit")) {
      if (path.at(-1) !== "escalation") path.push("escalation");
    }
  }
  if (!path.length && fallback) path.push(fallback);
  return path;
}

const str = (v: unknown) => (typeof v === "string" ? v : "");

/** Plain-language description of one trace step, for the "How this was handled" list. */
export function describe(e: TraceEvent): string | null {
  switch (e.type) {
    case "route":
      return e.agent === "none"
        ? "The front desk answered directly."
        : `The front desk sent this to ${speakerName(e.agent)}. ${e.reason}`;
    case "handoff":
      return `${speakerName(e.source)} passed this to ${speakerName(e.target)}. ${e.reason}`;
    case "tool": {
      const blocked = e.outcome === "rejected" ? " Not allowed by policy." : "";
      const failed = e.outcome.startsWith("exception") ? " This step failed." : "";
      const base = {
        get_customer_profile: "Checked your profile.",
        list_invoices: "Looked up your invoices.",
        request_refund: `Requested a refund on ${str(e.args.invoice_id)}.`,
        list_orders: "Looked up your orders.",
        get_order_status: `Checked the status of ${str(e.args.order_id)}.`,
        start_return: `Started a return for ${str(e.args.order_id)}.`,
        search_help_center: `Searched the help center for “${str(e.args.query)}”.`,
        create_support_ticket: "Opened a ticket for the support team.",
      }[e.tool];
      return (base ?? `Used ${e.tool}.`) + blocked + failed;
    }
    case "guardrail":
      return (
        {
          pii_redacted: "Removed payment details from your message before any AI saw it.",
          injection_blocked: "Declined a request that tried to change the assistant's instructions.",
          injection_suspected: "Flagged unusual instructions in the message and kept to normal rules.",
          handoff_limit: "Too many transfers in one reply, so it went to the human team.",
          tool_step_limit: "The specialist needed too many steps, so it went to the human team.",
        }[e.kind] ?? null
      );
    case "sources":
      return null;
  }
}
