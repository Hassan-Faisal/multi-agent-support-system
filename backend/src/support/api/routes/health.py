from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from support.api.deps import ContainerDep

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    """Process is up. Never touches dependencies, so it can't cause restart storms."""
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(c: ContainerDep, response: Response) -> dict[str, str]:
    """Ready to take traffic: database reachable and knowledge base indexed."""
    try:
        async with c.engine.connect() as conn:
            chunks = (await conn.execute(text("SELECT count(*) FROM kb_chunks"))).scalar_one()
    except Exception:
        response.status_code = 503
        return {"status": "unavailable", "database": "down"}
    if not chunks:
        response.status_code = 503
        return {"status": "unavailable", "knowledge_base": "empty; run support-ingest"}
    return {"status": "ready"}


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
