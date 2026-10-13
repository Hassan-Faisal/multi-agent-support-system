import type { AccountOverview, Invoice, Order } from "../api/types";
import { fmtDay, fmtMoney, humanize } from "../format";

function orderNote(o: Order): string {
  const ret = o.returns[0];
  if (ret) return `Return ${humanize(ret.status).toLowerCase()}`;
  if (o.status === "delivered" && o.delivered_at) return `Delivered ${fmtDay(o.delivered_at)}`;
  if (o.eta) return `${humanize(o.status)}, due ${fmtDay(o.eta)}`;
  return humanize(o.status);
}

function invoiceNote(i: Invoice): string {
  const r = i.refunds[0];
  if (r) return r.status === "pending_approval" ? "Refund awaiting approval" : `Refund ${r.status}`;
  return `${humanize(i.status)}, ${fmtDay(i.issued_at)}`;
}

export function AccountPanel({ account }: { account: AccountOverview | null }) {
  if (!account) return <aside className="account" aria-busy="true" />;
  const { customer, orders, invoices, tickets } = account;
  return (
    <aside className="account" aria-label="Your account">
      <header className="account-head">
        <h2>{customer.name}</h2>
        <p>
          {customer.plan} plan, {customer.email}
        </p>
      </header>

      <h3>Orders</h3>
      <ul className="ledger">
        {orders.map((o) => (
          <li key={o.id}>
            <span className="ledger-main">
              {o.items.join(", ")}
              <small>
                {o.id}. {orderNote(o)}
              </small>
            </span>
            <span className="num">{fmtMoney(o.total)}</span>
          </li>
        ))}
      </ul>

      <h3>Invoices</h3>
      <ul className="ledger">
        {invoices.map((i) => (
          <li key={i.id} data-flag={i.refunds[0]?.status ?? i.status}>
            <span className="ledger-main">
              {i.description}
              <small>
                {i.id}. {invoiceNote(i)}
              </small>
            </span>
            <span className="num">{fmtMoney(i.amount)}</span>
          </li>
        ))}
      </ul>

      <h3>Requests with our team</h3>
      {tickets.length === 0 ? (
        <p className="quiet">Nothing open. If an assistant hands you to a person, it shows up here.</p>
      ) : (
        <ul className="ledger">
          {tickets.map((t) => (
            <li key={t.id}>
              <span className="ledger-main">
                {humanize(t.category)} request
                <small>
                  {t.id}. {humanize(t.status)}
                </small>
              </span>
              <span className={`pill pill-${t.priority}`}>{t.priority}</span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
