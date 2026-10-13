"""Markdown-aware chunking.

Splits on `##` sections first so a chunk never straddles two topics, then packs
paragraphs/list blocks up to `max_chars`, carrying a tail of the previous chunk as
overlap. Every chunk gets a heading path ("Doc title › Section") which is prepended
when embedding — a cheap form of contextual retrieval that markedly helps short
chunks like "Wait 5 minutes before requesting another link."
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CHUNKER_VERSION = "md-v1"  # bump to force re-indexing when the algorithm changes

_SECTION = re.compile(r"^##\s+(.+)$", re.M)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    index: int
    heading: str
    content: str

    @property
    def embedding_text(self) -> str:
        return f"{self.heading}\n\n{self.content}"


def _sections(title: str, body: str) -> list[tuple[str, str]]:
    parts = _SECTION.split(body)
    out: list[tuple[str, str]] = []
    intro = parts[0].strip()
    if intro:
        out.append((title, intro))
    for name, text in zip(parts[1::2], parts[2::2], strict=True):
        if text.strip():
            out.append((f"{title} › {name.strip()}", text.strip()))
    return out


def _blocks(text: str, max_chars: int) -> list[str]:
    """Paragraphs and list blocks; anything still too long is split on sentences."""
    blocks: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            blocks.append(para)
            continue
        current = ""
        for sentence in _SENTENCE.split(para):
            if current and len(current) + len(sentence) + 1 > max_chars:
                blocks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            blocks.append(current)
    return blocks


def chunk_markdown(title: str, body: str, *, max_chars: int = 1200, overlap_chars: int = 200) -> list[Chunk]:
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")
    chunks: list[Chunk] = []
    for heading, text in _sections(title, body):
        current: list[str] = []
        size = 0
        for block in _blocks(text, max_chars):
            if current and size + len(block) + 2 > max_chars:
                chunks.append(Chunk(len(chunks), heading, "\n\n".join(current)))
                # overlap: keep trailing blocks that fit in the overlap budget
                tail: list[str] = []
                tail_size = 0
                for prev in reversed(current):
                    if tail_size + len(prev) > overlap_chars:
                        break
                    tail.insert(0, prev)
                    tail_size += len(prev) + 2
                current, size = tail, tail_size
            current.append(block)
            size += len(block) + 2
        if current:
            chunks.append(Chunk(len(chunks), heading, "\n\n".join(current)))
    return chunks
