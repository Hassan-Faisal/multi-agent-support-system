"""Serve the built single-page app from the API process.

Used for single-service deployments (one free container hosts UI and API on the same
origin, so no CORS and no second service). Behind nginx in docker-compose it's unused.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Mirrors frontend/nginx.conf. Google Fonts are the only third-party origin.
CSP = (
    "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
)
_RESERVED = ("api/", "healthz", "readyz", "metrics")


def mount_spa(app: FastAPI, static_dir: str | Path) -> None:
    root = Path(static_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"SUPPORT_STATIC_DIR={root} has no index.html; build the frontend first")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith(_RESERVED):
            raise HTTPException(404)  # unknown API route: never answer with HTML
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):  # blocks ../ traversal
            immutable = target.parent.name == "assets"  # Vite fingerprints these filenames
            cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        # Client-side route (e.g. /chat): let React Router handle it.
        return FileResponse(index, headers={"Cache-Control": "no-cache", "Content-Security-Policy": CSP})
