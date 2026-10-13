"""SQLite data layer with seeded mock data.

Swap this module for your real systems later: the tools in app/tools.py only
call the functions defined here, so nothing else has to change.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY, name TEXT, email TEXT, plan TEXT, member_since TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, customer_id TEXT, status TEXT, total REAL,
    items TEXT, placed_at TEXT, carrier TEXT, tracking_number TEXT,
    eta TEXT, delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY, customer_id TEXT, amount REAL, status TEXT,
    description TEXT, issued_at TEXT
);
CREATE TABLE IF NOT EXISTS refunds (
    id TEXT PRIMARY KEY, invoice_id TEXT, customer_id TEXT, amount REAL,
    reason TEXT, status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS returns (
    id TEXT PRIMARY KEY, order_id TEXT, customer_id TEXT, reason TEXT,
    status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS kb_articles (
    id TEXT PRIMARY KEY, title TEXT, tags TEXT, body TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, customer_id TEXT, category TEXT, priority TEXT,
    summary TEXT, status TEXT, created_at TEXT
);
"""


@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _d(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def init_db(reset: bool = False) -> None:
    """Create tables and seed demo data (dates are relative to today)."""
    if reset and config.DB_PATH.exists():
        config.DB_PATH.unlink()
    with connect() as c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM customers").fetchone()[0]:
            return

        c.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", [
            ("C001", "Ayesha Khan", "ayesha@example.com", "Pro", _d(420)),
            ("C002", "Marcus Lee", "marcus@example.com", "Basic", _d(60)),
            ("C003", "Sofia Rossi", "sofia@example.com", "Enterprise", _d(900)),
        ])
        c.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?)", [
            ("ORD-1001", "C001", "delivered", 89.99,
             json.dumps(["Wireless Keyboard"]), _d(12), "DHL", "DHL123456", _d(7), _d(7)),
            ("ORD-1002", "C001", "in_transit", 249.00,
             json.dumps(["Noise-Cancelling Headphones"]), _d(4), "FedEx", "FX998877", _d(-2), None),
            ("ORD-1003", "C002", "processing", 34.50,
             json.dumps(["USB-C Cable x3"]), _d(1), None, None, _d(-5), None),
            ("ORD-1004", "C002", "delivered", 120.00,
             json.dumps(["Desk Lamp"]), _d(55), "UPS", "1Z999AA1", _d(50), _d(50)),
            ("ORD-1005", "C003", "delayed", 1499.00,
             json.dumps(["Standing Desk", "Monitor Arm"]), _d(15), "UPS", "1Z555BB2", _d(3), None),
        ])
        c.executemany("INSERT INTO invoices VALUES (?,?,?,?,?,?)", [
            ("INV-2001", "C001", 29.00, "paid", "Pro plan - monthly", _d(10)),
            ("INV-2002", "C001", 29.00, "paid", "Pro plan - monthly (duplicate charge)", _d(10)),
            ("INV-2003", "C002", 9.00, "paid", "Basic plan - monthly", _d(45)),
            ("INV-2004", "C002", 9.00, "overdue", "Basic plan - monthly", _d(15)),
            ("INV-2005", "C003", 499.00, "paid", "Enterprise plan - monthly", _d(5)),
        ])
        c.executemany("INSERT INTO kb_articles VALUES (?,?,?,?)", [
            ("KB-01", "Resetting your password", "login,password,account,locked",
             "Go to Settings > Security > Reset password. A reset link is emailed and is valid "
             "for 30 minutes. If the email doesn't arrive, check spam, then try again after 5 minutes. "
             "After 5 failed logins the account locks for 15 minutes."),
            ("KB-02", "App crashes on startup", "crash,startup,app,freeze,mobile",
             "1) Update to the latest version. 2) Clear the app cache (Settings > Storage > Clear cache). "
             "3) Restart the device. 4) Reinstall the app. If it still crashes, collect the app version "
             "and device model and escalate to engineering."),
            ("KB-03", "Sync not working between devices", "sync,devices,data,offline",
             "Confirm both devices are signed into the same account and online. Toggle Settings > Sync "
             "off and on. Sync can take up to 10 minutes for large libraries."),
            ("KB-04", "Connecting the API / API key errors", "api,key,401,403,integration,developer",
             "401 means the key is missing or invalid; regenerate it under Settings > Developer. "
             "403 means the plan doesn't include API access (Pro and Enterprise only). "
             "Rate limit is 100 req/min on Pro, 1000 req/min on Enterprise."),
            ("KB-05", "Two-factor authentication", "2fa,mfa,security,authenticator,login",
             "Enable 2FA under Settings > Security. If you lose your device, use a backup code. "
             "Without backup codes, identity must be verified by a human agent."),
        ])


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------- read helpers ----------
def get_customer(customer_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return dict(r) if r else None


def list_customers() -> list[dict]:
    with connect() as c:
        return _rows(c.execute("SELECT * FROM customers ORDER BY id"))


def get_orders(customer_id: str) -> list[dict]:
    with connect() as c:
        return _rows(c.execute(
            "SELECT * FROM orders WHERE customer_id=? ORDER BY placed_at DESC", (customer_id,)))


def get_order(order_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM orders WHERE id=?", (order_id.upper(),)).fetchone()
        return dict(r) if r else None


def get_invoices(customer_id: str) -> list[dict]:
    with connect() as c:
        return _rows(c.execute(
            "SELECT * FROM invoices WHERE customer_id=? ORDER BY issued_at DESC", (customer_id,)))


def get_invoice(invoice_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM invoices WHERE id=?", (invoice_id.upper(),)).fetchone()
        return dict(r) if r else None


def get_refunds_for_invoice(invoice_id: str) -> list[dict]:
    with connect() as c:
        return _rows(c.execute("SELECT * FROM refunds WHERE invoice_id=?", (invoice_id.upper(),)))


def get_returns_for_order(order_id: str) -> list[dict]:
    with connect() as c:
        return _rows(c.execute("SELECT * FROM returns WHERE order_id=?", (order_id.upper(),)))


def search_kb(query: str, limit: int = 3) -> list[dict]:
    """Naive keyword scoring. Replace with a vector store for production."""
    words = {w.strip(".,?!").lower() for w in query.split() if len(w) > 2}
    with connect() as c:
        articles = _rows(c.execute("SELECT * FROM kb_articles"))
    scored = []
    for a in articles:
        hay = f"{a['title']} {a['tags']} {a['body']}".lower()
        tags = set(a["tags"].split(","))
        score = sum(3 if w in tags else 1 for w in words if w in hay)
        if score:
            scored.append((score, a))
    scored.sort(key=lambda x: -x[0])
    return [a for _, a in scored[:limit]]


def list_tickets() -> list[dict]:
    with connect() as c:
        return _rows(c.execute("SELECT * FROM tickets ORDER BY created_at DESC"))


# ---------- write helpers ----------
def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_refund(invoice_id: str, customer_id: str, amount: float, reason: str, status: str) -> dict:
    row = dict(id=_new_id("RF"), invoice_id=invoice_id.upper(), customer_id=customer_id,
               amount=amount, reason=reason, status=status, created_at=_now())
    with connect() as c:
        c.execute("INSERT INTO refunds VALUES (:id,:invoice_id,:customer_id,:amount,:reason,:status,:created_at)", row)
    return row


def create_return(order_id: str, customer_id: str, reason: str) -> dict:
    row = dict(id=_new_id("RT"), order_id=order_id.upper(), customer_id=customer_id,
               reason=reason, status="label_sent", created_at=_now())
    with connect() as c:
        c.execute("INSERT INTO returns VALUES (:id,:order_id,:customer_id,:reason,:status,:created_at)", row)
    return row


def create_ticket(customer_id: str, category: str, priority: str, summary: str) -> dict:
    row = dict(id=_new_id("TKT"), customer_id=customer_id, category=category,
               priority=priority, summary=summary, status="open", created_at=_now())
    with connect() as c:
        c.execute("INSERT INTO tickets VALUES (:id,:customer_id,:category,:priority,:summary,:status,:created_at)", row)
    return row
