from __future__ import annotations

import httpx
import pytest

from timeline_cti.api import create_app


@pytest.mark.asyncio
async def test_health_and_login(settings) -> None:  # type: ignore[no-untyped-def]
    # ASGI taşıyıcısı gerçek ağ açmadan tüm middleware zincirini çalıştırır.
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost") as client:
        live = await client.get("/api/v1/health/live")
        assert live.status_code == 200
        assert live.json()["data"]["status"] == "ok"

        private_search = await client.get("/api/v1/search", params={"q": "CVE"})
        assert private_search.status_code == 401

        denied = await client.post("/api/v1/auth/login", json={"password": "wrong"})
        assert denied.status_code == 401
        assert denied.headers["content-type"].startswith("application/problem+json")

        accepted = await client.post(
            "/api/v1/auth/login",
            json={"password": "correct horse battery staple"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["data"]["authenticated"] is True
        assert "timeline_cti_session" in accepted.cookies

        docs = await client.get("/api/docs")
        assert docs.status_code == 200, docs.text
        assert "/swagger/swagger-ui-bundle.js" in docs.text
        assert "cdn.jsdelivr.net" not in docs.text

        missing_csrf = await client.post("/api/v1/auth/logout")
        assert missing_csrf.status_code == 403
        logout = await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": accepted.json()["data"]["csrf_token"]},
        )
        assert logout.status_code == 200
