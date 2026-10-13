"""Load knowledge-base markdown files with YAML front matter."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SourceDocument:
    slug: str
    title: str
    url: str
    category: str
    body: str

    def fingerprint(self, *extra: str) -> str:
        """Changes whenever content, metadata or the indexing setup (`extra`) changes."""
        h = hashlib.sha256()
        for part in (self.title, self.url, self.category, self.body, *extra):
            h.update(part.encode())
            h.update(b"\x00")
        return h.hexdigest()


class DocumentError(ValueError):
    pass


def parse_markdown(slug: str, raw: str) -> SourceDocument:
    if not raw.startswith("---"):
        raise DocumentError(f"{slug}: missing YAML front matter")
    try:
        _, meta_raw, body = raw.split("---", 2)
    except ValueError as e:
        raise DocumentError(f"{slug}: unterminated front matter") from e
    meta = yaml.safe_load(meta_raw) or {}
    missing = {"title", "url", "category"} - meta.keys()
    if missing:
        raise DocumentError(f"{slug}: front matter missing {sorted(missing)}")
    return SourceDocument(
        slug=slug,
        title=str(meta["title"]),
        url=str(meta["url"]),
        category=str(meta["category"]),
        body=body.strip(),
    )


def load_directory(path: str | Path) -> list[SourceDocument]:
    root = Path(path)
    if not root.is_dir():
        raise DocumentError(f"knowledge base directory not found: {root}")
    return [parse_markdown(p.stem, p.read_text(encoding="utf-8")) for p in sorted(root.glob("*.md"))]
