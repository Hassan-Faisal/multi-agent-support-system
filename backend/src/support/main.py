"""FastAPI application factory.

uvicorn support.main:create_app --factory --port 8000
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from support.api.chat import ChatRunner
from support.api.container import Container, build_container
from support.api.routes import admin, auth, conversations, health
from support.api.spa import mount_spa
from support.domain.errors import DomainError
from support.observability.logs import configure_logging, get_logger
from support.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS
from support.settings import Settings, get_settings

log = get_logger(__name__)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        c = container or await build_container(settings)
        _install(app, c)
        log.info(
            "app.started", env=settings.env, model=settings.llm_model, embeddings=settings.embedding_provider
        )
        yield
        await app.state.chat_runner.drain()
        if owned:
            await c.aclose()

    app = FastAPI(
        title="Nimbus Support API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    if container is not None:  # tests drive the app without a lifespan
        _install(app, container)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, path, response.status_code).inc()
        HTTP_LATENCY.labels(request.method, path).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if path not in ("/healthz", "/metrics"):
            log.info(
                "http.request",
                method=request.method,
                path=path,
                status=response.status_code,
                ms=round(elapsed * 1000),
            )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        """RFC 7807 problem details."""
        return JSONResponse(
            status_code=exc.http_status,
            media_type="application/problem+json",
            content={
                "type": f"https://errors.nimbus.example/{exc.code}",
                "title": exc.code.replace("_", " "),
                "status": exc.http_status,
                "detail": exc.message,
                "instance": request.url.path,
            },
        )

    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(conversations.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)
    app.include_router(health.router)
    if settings.static_dir:  # last: the SPA catch-all must not shadow API routes
        mount_spa(app, settings.static_dir)
    return app


def _install(app: FastAPI, c: Container) -> None:
    app.state.container = c
    app.state.chat_runner = ChatRunner(c)
