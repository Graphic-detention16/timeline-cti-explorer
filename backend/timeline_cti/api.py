from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

import structlog
import uvicorn
from fastapi import Depends, FastAPI, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .clickhouse import ClickHouseRepository, InvalidCursorError
from .config import Settings, get_settings
from .logging import configure_logging
from .models import ApiEnvelope, CtiLevel, SearchMode, SearchSort
from .normalization import query_terms
from .security import AuthManager, SessionPrincipal, SlidingWindowRateLimiter
from .state import StateStore
from .x_client import XApiError, XClient

logger = structlog.get_logger()
SESSION_COOKIE = "timeline_cti_session"


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class Problem(RuntimeError):
    def __init__(self, status_code: int, code: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail


@dataclass(frozen=True)
class Principal:
    subject: str
    csrf_token: str | None
    method: Literal["session", "api_key"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.LOG_LEVEL)
    state_store = StateStore(settings.STATE_DATABASE_PATH, settings.token_encryption_key_bytes)
    repository = ClickHouseRepository(
        settings,
        role="api",
        session_secret=settings.SESSION_SECRET.get_secret_value(),
    )
    auth = AuthManager(
        settings.ADMIN_PASSWORD_HASH.get_secret_value(),
        settings.SESSION_SECRET.get_secret_value(),
        settings.API_KEY_SHA256.get_secret_value(),
        settings.SESSION_MAX_AGE_SECONDS,
    )
    limiter = SlidingWindowRateLimiter()
    x_client = XClient(settings, state_store)
    metrics_registry = CollectorRegistry()
    request_counter = Counter(
        "timeline_cti_http_requests_total",
        "HTTP requests handled by the API",
        ["method", "route", "status"],
        registry=metrics_registry,
    )
    request_duration = Histogram(
        "timeline_cti_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "route"],
        registry=metrics_registry,
    )

    app = FastAPI(
        title="Timeline CTI Explorer API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        description="Private, explainable CTI search over an authenticated X home timeline.",
    )
    app.state.settings = settings
    app.state.state_store = state_store
    app.state.repository = repository
    app.state.auth = auth
    app.state.limiter = limiter
    app.state.x_client = x_client
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("X-Request-ID", secrets.token_hex(12))[:64]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = cast(Response, await call_next(request))
        route = request.scope.get("route")
        route_name = getattr(route, "path", "unmatched")
        duration = time.perf_counter() - started
        request_counter.labels(request.method, route_name, str(response.status_code)).inc()
        request_duration.labels(request.method, route_name).observe(duration)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        logger.info(
            "http_request",
            request_id=request_id,
            method=request.method,
            route=request.url.path,
            status=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        return response

    @app.exception_handler(Problem)
    async def handle_problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(request, exc.status_code, exc.code, exc.title, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning(
            "request_validation_failed",
            request_id=request.state.request_id,
            fields=[{"location": error["loc"], "type": error["type"]} for error in exc.errors()],
        )
        return problem_response(
            request,
            422,
            "validation_error",
            "Request validation failed",
            "One or more request fields are invalid.",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_request_error",
            request_id=request.state.request_id,
            error_type=type(exc).__name__,
        )
        return problem_response(
            request,
            500,
            "internal_error",
            "Internal server error",
            "The request could not be completed safely.",
        )

    async def current_principal(request: Request) -> Principal:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer ") and auth.verify_api_key(authorization[7:]):
            return Principal("api", None, "api_key")
        session_token = request.cookies.get(SESSION_COOKIE, "")
        session: SessionPrincipal | None = (
            auth.verify_session(session_token) if session_token else None
        )
        if session:
            return Principal(session.subject, session.csrf_token, "session")
        raise Problem(401, "authentication_required", "Authentication required", "Sign in first.")

    async def state_change_principal(
        request: Request,
        principal: Principal = Depends(current_principal),
    ) -> Principal:
        if principal.method == "session":
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or not secrets.compare_digest(supplied, principal.csrf_token or ""):
                raise Problem(403, "csrf_failed", "CSRF validation failed", "Refresh the session.")
        return principal

    def rate_limit(request: Request, scope: str, limit: int) -> None:
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(f"{scope}:{client}", limit):
            raise Problem(429, "rate_limited", "Too many requests", "Try again later.")

    def envelope(request: Request, data: Any, **meta: Any) -> ApiEnvelope:
        return ApiEnvelope(
            data=data,
            meta={"request_id": request.state.request_id, **meta},
            error=None,
        )

    @app.get("/api/v1/health/live", include_in_schema=False)
    async def health_live(request: Request) -> ApiEnvelope:
        return envelope(request, {"status": "ok"})

    @app.get("/internal/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(metrics_registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/v1/health/ready", include_in_schema=False)
    async def health_ready(request: Request) -> JSONResponse:
        try:
            clickhouse_ready = await run_in_threadpool(repository.ping)
        except Exception:  # noqa: BLE001
            clickhouse_ready = False
        scoring_mode = state_store.get_value("worker_scoring_mode", "unknown")
        compliance_stale = (
            settings.COLLECTOR_BACKEND == "api"
            and settings.X_USE_CASE_APPROVED
            and timestamp_is_stale(state_store.get_value("last_compliance_success"))
        )
        oauth_connected = state_store.get_oauth_token() is not None
        session_connected = state_store.browser_session_connected()
        if settings.COLLECTOR_BACKEND == "selenium":
            ingest_connected = session_connected
        else:
            ingest_connected = oauth_connected or not settings.X_USE_CASE_APPROVED
        ready = (
            clickhouse_ready
            and scoring_mode == "hybrid"
            and not compliance_stale
            and ingest_connected
        )
        status_value = "ok" if ready else "degraded"
        body = envelope(
            request,
            {
                "status": status_value,
                "clickhouse": clickhouse_ready,
                "oauth_connected": oauth_connected,
                "session_connected": session_connected,
                "collector_backend": settings.COLLECTOR_BACKEND,
                "scoring_mode": scoring_mode,
                "compliance_stale": compliance_stale,
            },
        )
        return JSONResponse(body.model_dump(mode="json"), status_code=200 if ready else 503)

    @app.post("/api/v1/auth/login", response_model=ApiEnvelope)
    async def login(request: Request, body: LoginRequest, response: Response) -> ApiEnvelope:
        rate_limit(request, "login", 5)
        if not auth.verify_password(body.password):
            state_store.audit("login_failed", {"request_id": request.state.request_id})
            raise Problem(401, "invalid_credentials", "Invalid credentials", "Sign in failed.")
        token, principal = auth.issue_session()
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=settings.SESSION_MAX_AGE_SECONDS,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )
        state_store.audit("login_success", {"request_id": request.state.request_id})
        return envelope(request, {"authenticated": True, "csrf_token": principal.csrf_token})

    @app.post("/api/v1/auth/logout", response_model=ApiEnvelope)
    async def logout(
        request: Request,
        response: Response,
        _principal: Principal = Depends(state_change_principal),
    ) -> ApiEnvelope:
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True)
        return envelope(request, {"authenticated": False})

    @app.get("/api/v1/auth/session", response_model=ApiEnvelope)
    async def session(
        request: Request,
        principal: Principal = Depends(current_principal),
    ) -> ApiEnvelope:
        return envelope(
            request,
            {
                "authenticated": True,
                "method": principal.method,
                "csrf_token": principal.csrf_token,
            },
        )

    @app.get("/api/v1/auth/x/start")
    async def x_auth_start(
        _principal: Principal = Depends(current_principal),
    ) -> RedirectResponse:
        if not settings.X_USE_CASE_APPROVED:
            raise Problem(
                409,
                "x_use_case_not_approved",
                "Live collection is disabled",
                "Approve and disclose the use case before enabling X OAuth.",
            )
        return RedirectResponse(x_client.build_authorization_url(), status_code=302)

    @app.get("/api/v1/auth/x/callback", include_in_schema=False)
    async def x_auth_callback(code: str, state: str) -> RedirectResponse:
        try:
            await x_client.exchange_code(code, state)
        except XApiError as exc:
            logger.warning("oauth_callback_failed", error_type=type(exc).__name__)
            return RedirectResponse("/?oauth=error", status_code=302)
        return RedirectResponse("/?oauth=success", status_code=302)

    @app.get("/api/v1/search", response_model=ApiEnvelope)
    async def search(
        request: Request,
        q: Annotated[str, Query(min_length=3, max_length=256)],
        _principal: Principal = Depends(current_principal),
        mode: SearchMode = SearchMode.ALL,
        sort: SearchSort = SearchSort.RELEVANCE,
        from_date: Annotated[datetime | None, Query(alias="from")] = None,
        to_date: Annotated[datetime | None, Query(alias="to")] = None,
        lang: Annotated[str | None, Query(min_length=2, max_length=12)] = None,
        cti_min: Annotated[int | None, Query(ge=0, le=100)] = None,
        cti_level: CtiLevel | None = None,
        cti_category: Annotated[str | None, Query(max_length=64)] = None,
        ioc_type: Literal["ip", "domain", "url", "hash", "cve", "attack"] | None = None,
        author: Annotated[str | None, Query(max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        cursor: Annotated[str | None, Query(max_length=1024)] = None,
    ) -> ApiEnvelope:
        rate_limit(request, "search", 60)
        if len(query_terms(q)) > 5:
            raise Problem(422, "too_many_terms", "Too many terms", "Use at most five terms.")
        if from_date and to_date and from_date > to_date:
            raise Problem(
                422,
                "invalid_date_range",
                "Invalid date range",
                "The from value must not be later than the to value.",
            )
        started = time.perf_counter()
        try:
            items, next_cursor = await run_in_threadpool(
                repository.search,
                q,
                mode,
                sort,
                limit,
                cursor,
                from_date,
                to_date,
                lang,
                cti_min,
                cti_level,
                cti_category,
                ioc_type,
                author,
            )
        except InvalidCursorError as exc:
            raise Problem(422, "invalid_cursor", "Invalid cursor", str(exc)) from exc
        return envelope(
            request,
            [item.model_dump(mode="json") for item in items],
            took_ms=round((time.perf_counter() - started) * 1000, 2),
            next_cursor=next_cursor,
            limit=limit,
        )

    @app.get("/api/v1/posts/recent", response_model=ApiEnvelope)
    async def recent_posts(
        request: Request,
        _principal: Principal = Depends(current_principal),
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> ApiEnvelope:
        items = await run_in_threadpool(repository.recent_posts, limit)
        return envelope(
            request,
            [item.model_dump(mode="json") for item in items],
            limit=limit,
        )

    @app.get("/api/v1/posts/{post_id}", response_model=ApiEnvelope)
    async def get_post(
        request: Request,
        post_id: Annotated[str, Path(pattern=r"^[0-9]{1,20}$")],
        _principal: Principal = Depends(current_principal),
    ) -> ApiEnvelope:
        item = await run_in_threadpool(repository.get_post, post_id)
        if item is None:
            raise Problem(404, "post_not_found", "Post not found", "No matching post exists.")
        return envelope(request, item.model_dump(mode="json"))

    @app.get("/api/v1/cti/top", response_model=ApiEnvelope)
    async def top_cti(
        request: Request,
        _principal: Principal = Depends(current_principal),
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> ApiEnvelope:
        items = await run_in_threadpool(repository.top_cti, limit)
        return envelope(request, [item.model_dump(mode="json") for item in items], limit=limit)

    @app.get("/api/v1/stats/overview", response_model=ApiEnvelope)
    async def stats_overview(
        request: Request,
        _principal: Principal = Depends(current_principal),
    ) -> ApiEnvelope:
        data = await run_in_threadpool(repository.stats)
        return envelope(request, data)

    @app.get("/api/v1/collector/status", response_model=ApiEnvelope)
    async def collector_status(
        request: Request,
        _principal: Principal = Depends(current_principal),
    ) -> ApiEnvelope:
        data = state_store.status()
        raw_compliance = data.get("last_compliance_success")
        data["compliance_stale"] = (
            settings.COLLECTOR_BACKEND == "api"
            and settings.X_USE_CASE_APPROVED
            and timestamp_is_stale(raw_compliance if isinstance(raw_compliance, str) else "")
        )
        data["live_collection_enabled"] = (
            settings.COLLECTOR_BACKEND == "selenium" or settings.X_USE_CASE_APPROVED
        )
        data["collector_backend"] = settings.COLLECTOR_BACKEND
        data["session_connected"] = state_store.browser_session_connected()
        data["daily_read_budget"] = settings.X_DAILY_READ_BUDGET
        data["rate_limit_remaining"] = state_store.get_value("x_rate_limit_remaining") or None
        data["rate_limit_reset"] = state_store.get_value("x_rate_limit_reset") or None
        data["scoring_mode"] = state_store.get_value("worker_scoring_mode", "unknown")
        return envelope(request, data)

    @app.post(
        "/api/v1/collector/run", response_model=ApiEnvelope, status_code=status.HTTP_202_ACCEPTED
    )
    async def collector_run(
        request: Request,
        _principal: Principal = Depends(state_change_principal),
    ) -> ApiEnvelope:
        state_store.set_value("collector_run_requested", datetime.now(UTC).isoformat())
        state_store.audit("collector_run_requested", {"request_id": request.state.request_id})
        return envelope(request, {"accepted": True})

    @app.get("/api/openapi.json", include_in_schema=False)
    async def protected_openapi(
        _request: Request,
        _principal: Principal = Depends(current_principal),
    ) -> JSONResponse:
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=[route for route in app.routes if isinstance(route, APIRoute)],
        )
        return JSONResponse(schema)

    @app.get("/api/docs", include_in_schema=False)
    async def protected_docs(
        _request: Request,
        _principal: Principal = Depends(current_principal),
    ) -> Response:
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json",
            title="Timeline CTI API",
            swagger_js_url="/swagger/swagger-ui-bundle.js",
            swagger_css_url="/swagger/swagger-ui.css",
            swagger_favicon_url="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>",
        )

    return app


def problem_response(
    request: Request,
    status_code: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    return JSONResponse(
        {
            "type": f"https://timeline-cti.local/problems/{code}",
            "title": title,
            "status": status_code,
            "detail": detail,
            "code": code,
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
        status_code=status_code,
        media_type="application/problem+json",
    )


def timestamp_is_stale(raw: str, hours: int = 24) -> bool:
    if not raw:
        return True
    try:
        timestamp = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return datetime.now(UTC) - timestamp > timedelta(hours=hours)


def run() -> None:
    uvicorn.run(
        "timeline_cti.api:create_app",
        factory=True,
        # API container'ı yalnız internal Docker ağına bağlıdır.
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=8000,
        proxy_headers=True,
    )


if __name__ == "__main__":
    run()
