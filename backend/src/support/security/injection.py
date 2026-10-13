"""Heuristic prompt-injection detection for customer input.

This is a cheap first layer, not the security boundary. The real boundary is that
every side effect goes through a tool that enforces authorization and business
policy in code (see services/), so a model that *is* manipulated still can't act
outside what this customer is allowed to do. The detector exists to (a) refuse
blatant attacks without spending tokens and (b) flag attempts for review.

Retrieved documents are a second injection surface; they are wrapped as data in the
retrieval tool output (see rag/retriever.py) rather than scanned here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (pattern, weight). Weights add up and are capped at 1.0.
_SIGNALS: list[tuple[re.Pattern[str], float]] = [
    (
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all|your)\b.{0,20}"
            r"\b(instructions?|rules|prompts?|guidelines)\b",
            re.I,
        ),
        0.6,
    ),
    (re.compile(r"\b(system|developer)\s*(prompt|message|instructions?)\b", re.I), 0.35),
    (re.compile(r"\b(reveal|print|show|repeat|output)\b.{0,30}\b(prompt|instructions|rules)\b", re.I), 0.35),
    (re.compile(r"\byou are (now|no longer)\b|\bact as (an? )?(admin|developer|system|root)\b", re.I), 0.4),
    (re.compile(r"\b(jailbreak|DAN mode|developer mode|god mode)\b", re.I), 0.6),
    (re.compile(r"</?\s*(system|assistant|tool|instructions?)\s*>", re.I), 0.5),
    (
        re.compile(
            r"\b(approve|issue|process)\b.{0,30}\brefund\b.{0,40}\b(without|bypass|skip|override)\b", re.I
        ),
        0.5,
    ),
    (re.compile(r"\b(other|another) customer'?s?\b.{0,30}\b(orders?|invoices?|data|account)\b", re.I), 0.3),
]


@dataclass(frozen=True)
class InjectionVerdict:
    score: float
    signals: list[str]

    def blocked(self, threshold: float) -> bool:
        return self.score >= threshold


def score_injection(text: str) -> InjectionVerdict:
    score, hits = 0.0, []
    for pattern, weight in _SIGNALS:
        m = pattern.search(text)
        if m:
            score += weight
            hits.append(m.group(0)[:60])
    return InjectionVerdict(round(min(score, 1.0), 2), hits)
