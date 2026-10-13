"""PII redaction for text that leaves our trust boundary (LLM providers, logs).

We redact data we never need to answer a support question: payment card numbers
(Luhn-validated, so order ids and phone numbers aren't mangled), US SSNs and IBANs.
Emails and names are left alone because support genuinely needs them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass(frozen=True)
class Redaction:
    text: str
    findings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.findings)


def redact_pii(text: str) -> Redaction:
    findings: list[str] = []

    def card(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            findings.append("card_number")
            return f"[REDACTED_CARD_…{digits[-4:]}]"
        return m.group()

    def tag(kind: str) -> Callable[[re.Match[str]], str]:
        def sub(_: re.Match[str]) -> str:
            findings.append(kind)
            return f"[REDACTED_{kind.upper()}]"

        return sub

    out = _CARD.sub(card, text)
    out = _SSN.sub(tag("ssn"), out)
    out = _IBAN.sub(tag("iban"), out)
    return Redaction(out, findings)
