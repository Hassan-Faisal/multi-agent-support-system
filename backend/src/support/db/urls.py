"""Database URL translation between drivers.

Hosted Postgres providers (Neon, Supabase, Render…) hand out libpq-style URLs such as
`postgresql://user:pw@host/db?sslmode=require&channel_binding=require`. This app uses
two drivers that disagree on that format:

- SQLAlchemy + asyncpg wants `postgresql+asyncpg://…?ssl=require` and rejects libpq-only
  options like `channel_binding`.
- psycopg (LangGraph's checkpointer) wants plain libpq: `postgresql://…?sslmode=require`.

Accepting any of these forms and deriving both means a provider's URL can be pasted
unchanged into SUPPORT_DATABASE_URL.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SCHEMES = {"postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg", "postgresql+psycopg2"}
# libpq connection options asyncpg doesn't understand; SSL itself is carried by `ssl`.
_LIBPQ_ONLY = {"channel_binding", "sslrootcert", "sslcert", "sslkey", "gssencmode", "target_session_attrs"}


def _split(url: str) -> tuple[str, list[tuple[str, str]], tuple[str, str, str, str, str]]:
    parts = urlsplit(url)
    if parts.scheme not in _SCHEMES:
        raise ValueError(f"unsupported database URL scheme {parts.scheme!r}; expected a PostgreSQL URL")
    return parts.scheme, parse_qsl(parts.query, keep_blank_values=True), parts


def to_asyncpg_url(url: str) -> str:
    """URL for SQLAlchemy's asyncpg dialect."""
    _, query, parts = _split(url)
    out: list[tuple[str, str]] = []
    for key, value in query:
        if key == "sslmode":
            out.append(("ssl", value))
        elif key not in _LIBPQ_ONLY:
            out.append((key, value))
    return urlunsplit(("postgresql+asyncpg", parts[1], parts[2], urlencode(out), parts[4]))


def to_libpq_url(url: str) -> str:
    """Plain libpq URL for psycopg."""
    _, query, parts = _split(url)
    out = [("sslmode", v) if k == "ssl" else (k, v) for k, v in query]
    return urlunsplit(("postgresql", parts[1], parts[2], urlencode(out), parts[4]))
