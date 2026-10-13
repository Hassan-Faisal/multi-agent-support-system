"""Domain errors. The API maps them to RFC 7807 problem responses; agent tools turn
them into structured tool results the model can explain to the customer."""

from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"
    http_status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    code = "not_found"
    http_status = 404


class PolicyViolation(DomainError):
    """The request is understood but business policy forbids it."""

    code = "policy_violation"
    http_status = 422


class Conflict(DomainError):
    code = "conflict"
    http_status = 409


class Forbidden(DomainError):
    code = "forbidden"
    http_status = 403
