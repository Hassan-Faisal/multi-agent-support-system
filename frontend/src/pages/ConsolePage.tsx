import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuditEntry, QueueStats, Refund, Ticket, TicketStatus } from "../api/types";
import { useAuth } from "../auth";
import { fmtAgo, fmtMoney, humanize } from "../format";

const TABS: { id: TicketStatus; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "in_progress", label: "In progress" },
  { id: "resolved", label: "Resolved" },
];

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function RefundRow({ refund, onDone }: { refund: Refund; onDone: (msg: string) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decide = async (approve: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api.admin.decideRefund(refund.id, approve, note);
      onDone(`${approve ? "Approved" : "Declined"} ${fmtMoney(refund.amount)} refund on ${refund.invoice_id}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't go through.");
      setBusy(false);
    }
  };

  return (
    <li className="approval">
      <p className="approval-amount num">{fmtMoney(refund.amount)}</p>
      <div className="approval-body">
        <p>
          <strong>{refund.invoice_id}</strong> for customer {refund.customer_id}, requested {fmtAgo(refund.created_at)}
        </p>
        <p className="quiet">Customer's reason: {refund.reason}</p>
        <label className="approval-note">
          <span className="visually-hidden">Note for {refund.id}</span>
          <input placeholder="Note for the record (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && <p className="notice notice-error">{error}</p>}
      </div>
      <div className="approval-actions">
        <button className="btn btn-ink" disabled={busy} onClick={() => void decide(true)}>
          Approve refund
        </button>
        <button className="btn btn-outline" disabled={busy} onClick={() => void decide(false)}>
          Decline
        </button>
      </div>
    </li>
  );
}

export function ConsolePage() {
  const { user, logout } = useAuth();
  const [stats, setStats] = useState<QueueStats | null>(null);
  const [refunds, setRefunds] = useState<Refund[]>([]);
  const [tab, setTab] = useState<TicketStatus>("open");
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [flash, setFlash] = useState<string | null>(null);

  const [version, setVersion] = useState(0); // bump to reload after an action

  useEffect(() => {
    let cancelled = false;
    const fetchQueue = () =>
      Promise.all([api.admin.stats(), api.admin.refunds("pending_approval"), api.admin.tickets(tab), api.admin.audit(40)])
        .then(([s, r, t, a]) => {
          if (cancelled) return;
          setStats(s);
          setRefunds(r);
          setTickets(t);
          setAudit(a);
        })
        .catch(() => {
          /* transient; the next poll retries */
        });
    fetchQueue();
    const id = setInterval(fetchQueue, 15000); // the queue is shared with other staff; keep it fresh
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [tab, version]);

  const done = (msg: string) => {
    setFlash(msg);
    setVersion((v) => v + 1);
  };

  const setStatus = async (t: Ticket, status: TicketStatus) => {
    await api.admin.setTicketStatus(t.id, status);
    done(`${t.id} moved to ${humanize(status).toLowerCase()}.`);
  };

  return (
    <div className="console">
      <header className="topbar">
        <p className="wordmark">Nimbus Help, support console</p>
        <nav className="topbar-actions">
          <span className="who">{user?.display_name}</span>
          <button className="btn btn-quiet" onClick={logout}>
            Sign out
          </button>
        </nav>
      </header>

      <main className="console-main">
        <section className="console-summary">
          <h1>
            {stats
              ? stats.pending_refunds
                ? `${plural(stats.pending_refunds, "refund")} waiting for approval.`
                : "No refunds waiting."
              : "Loading the queue"}
          </h1>
          {stats && (
            <p className="lede">
              {plural(stats.open_tickets, "open ticket")}
              {stats.urgent_tickets ? `, ${stats.urgent_tickets} urgent` : ""}. {plural(stats.conversations, "conversation")}{" "}
              handled by the assistants so far.
            </p>
          )}
          {flash && (
            <p className="notice notice-ok" role="status">
              {flash}
            </p>
          )}
        </section>

        <section aria-labelledby="refunds-title" className="console-refunds">
          <h2 id="refunds-title">Refunds over the auto-approval limit</h2>
          {refunds.length === 0 ? (
            <p className="quiet">
              Nothing to review. Refunds of $50 or less are approved by the billing assistant on its own; anything larger
              lands here.
            </p>
          ) : (
            <ul className="approvals">
              {refunds.map((r) => (
                <RefundRow key={r.id} refund={r} onDone={done} />
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="tickets-title" className="console-tickets">
          <div className="section-head">
            <h2 id="tickets-title">Tickets</h2>
            <div role="tablist" className="tabs">
              {TABS.map((t) => (
                <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          {tickets.length === 0 ? (
            <p className="quiet">No {TABS.find((t) => t.id === tab)?.label.toLowerCase()} tickets.</p>
          ) : (
            <ul className="tickets">
              {tickets.map((t) => (
                <li key={t.id} className="ticket">
                  <span className={`pill pill-${t.priority}`}>{t.priority}</span>
                  <div className="ticket-body">
                    <p>
                      <strong>{t.id}</strong> {humanize(t.category)}, customer {t.customer_id}, opened{" "}
                      {fmtAgo(t.created_at)}
                    </p>
                    <p className="ticket-summary">{t.summary}</p>
                  </div>
                  <label>
                    <span className="visually-hidden">Status of {t.id}</span>
                    <select value={t.status} onChange={(e) => void setStatus(t, e.target.value as TicketStatus)}>
                      {TABS.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside aria-labelledby="audit-title" className="console-audit">
          <h2 id="audit-title">Activity</h2>
          <p className="quiet">Every change made by an assistant or a person, newest first.</p>
          <ol className="audit">
            {audit.map((a) => (
              <li key={a.id}>
                <p>
                  <strong>{a.actor.startsWith("agent:") ? `${humanize(a.actor.slice(6))} assistant` : a.actor.replace(/^user:/, "").replace(/<.*>$/, "")}</strong>{" "}
                  {humanize(a.action.replace(".", " ")).toLowerCase()} {a.entity_id}
                </p>
                <time dateTime={a.at}>{fmtAgo(a.at)}</time>
              </li>
            ))}
          </ol>
        </aside>
      </main>
    </div>
  );
}
