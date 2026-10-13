"""Structured logging with structlog.

JSON lines in prod (ship to any log stack), pretty console in dev. Request-scoped
fields (request_id, user_id, conversation_id) are bound via contextvars and appear on
every log line emitted while handling that request.
"""

from __future__ import annotations

import logging
import sys

import structlog

from support.security.pii import redact_pii


def _redact(_: object, __: str, event_dict: structlog.types.EventDict) -> structlog.types.EventDict:
    """Last line of defence: scrub card numbers etc. from any string field."""
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = redact_pii(value).text
    return event_dict


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Route stdlib logging (uvicorn, sqlalchemy, httpx) through the same level.
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(name)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore", "openai", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
