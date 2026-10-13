from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from support.api.spa import mount_spa
from support.db.urls import to_asyncpg_url, to_libpq_url

NEON = "postgresql://u:p%40ss@ep-cool-1.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def test_hosted_provider_url_is_translated_for_both_drivers() -> None:
    assert (
        to_asyncpg_url(NEON)
        == "postgresql+asyncpg://u:p%40ss@ep-cool-1.eu-central-1.aws.neon.tech/neondb?ssl=require"
    )
    assert to_libpq_url(NEON) == NEON  # psycopg takes libpq options as they are


def test_asyncpg_style_urls_round_trip() -> None:
    url = "postgresql+asyncpg://support:support@db:5432/support"
    assert to_asyncpg_url(url) == url
    assert to_libpq_url(url) == "postgresql://support:support@db:5432/support"
    assert to_libpq_url("postgresql+asyncpg://h/db?ssl=require") == "postgresql://h/db?sslmode=require"
    assert (
        to_asyncpg_url("postgres://h/db?host=/tmp&port=5433")
        == "postgresql+asyncpg://h/db?host=%2Ftmp&port=5433"
    )


def test_non_postgres_urls_are_rejected() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        to_asyncpg_url("mysql://h/db")


@pytest.fixture
def spa_app(tmp_path: Path) -> FastAPI:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app-123.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("top secret")
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    mount_spa(app, tmp_path)
    return app


async def test_spa_serves_assets_routes_and_never_shadows_the_api(spa_app: FastAPI) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=spa_app), base_url="http://t") as c:
        assert (await c.get("/api/v1/ping")).json() == {"ok": "yes"}
        asset = await c.get("/assets/app-123.js")
        assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
        page = await c.get("/chat")  # client-side route
        assert (
            page.text == "<html>app</html>"
            and "frame-ancestors 'none'" in page.headers["content-security-policy"]
        )
        assert (await c.get("/api/v1/nope")).status_code == 404  # JSON 404, not the app shell
        assert (await c.head("/chat")).status_code == 200  # link previewers and uptime checks use HEAD
        traversal = await c.get("/assets/%2e%2e/%2e%2e/secret.txt")
        assert "top secret" not in traversal.text


def test_missing_build_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"index\.html"):
        mount_spa(FastAPI(), tmp_path)
