"""Main FastAPI application."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    chat,
    config,
    cron,
    digest,
    harness,
    hindsight_bank,
    memory,
    memory_ingest,
    provider_status,
    status,
    tokens,
    websocket,
    workers,
)
from app.core.config import get_settings
from app.core.constants import API_PREFIX
from app.web import router as web_router, WEB_DIR

settings = get_settings()
docs_enabled = settings.is_development or settings.debug or settings.expose_docs


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return ""
    return auth_header.replace("Bearer ", "", 1).strip()


def _bearer_is_valid(request: Request) -> bool:
    token = _extract_bearer_token(request)
    return bool(token) and token == settings.bearer_token


def _dashboard_cloudflare_authorized(request: Request) -> bool:
    """Validate that dashboard traffic came via Cloudflare Access."""
    if settings.dashboard_shared_secret:
        shared = request.headers.get("X-Hermes-Origin-Secret", "").strip()
        if shared != settings.dashboard_shared_secret:
            return False

    # Human browser flow (Access) and service-token flow are both accepted.
    has_access_identity = bool(
        request.headers.get("CF-Access-Authenticated-User-Email", "").strip()
        or request.headers.get("CF-Access-Jwt-Assertion", "").strip()
    )
    has_service_token = bool(
        request.headers.get("CF-Access-Client-Id", "").strip()
        and request.headers.get("CF-Access-Client-Secret", "").strip()
    )
    return has_access_identity or has_service_token


def _dashboard_auth_ok(request: Request) -> bool:
    if _request_is_loopback(request):
        return True
    if settings.dashboard_auth_mode == "public":
        return True
    if settings.dashboard_auth_mode == "bearer":
        return _bearer_is_valid(request)
    if settings.dashboard_auth_mode == "cloudflare":
        return _dashboard_cloudflare_authorized(request)
    return False


def _request_is_loopback(request: Request) -> bool:
    client_host = (request.client.host if request.client else "") or ""
    if client_host in {"127.0.0.1", "::1", "localhost"}:
        return True

    configured_host = (
        os.environ.get("MC_HOST")
        or os.environ.get("HOST")
        or settings.host
        or ""
    ).strip().lower()
    return configured_host in {"127.0.0.1", "::1", "localhost"}


def _api_cloudflare_auth_ok(request: Request) -> bool:
    """Allow API auth via Cloudflare Access when the origin path is sufficiently trusted."""
    if settings.dashboard_auth_mode != "cloudflare":
        return False
    if not settings.dashboard_shared_secret and not _request_is_loopback(request):
        return False
    return _dashboard_cloudflare_authorized(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    print(f"Starting {settings.app_name} v{settings.app_version}")
    yield
    # Shutdown
    print("Shutting down...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="FastAPI backend for Hermes Web View (Mission Control dashboard)",
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Auth middleware
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Simple Bearer token authentication."""
    if request.method == "OPTIONS":
        return await call_next(request)

    request_path = request.url.path
    dashboard_request = request_path == "/" or request_path == "/dashboard" or request_path.startswith("/dashboard/")
    static_request = request_path.startswith("/static/")

    if (dashboard_request or static_request) and settings.dashboard_auth_mode != "public":
        if not _dashboard_auth_ok(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "Dashboard access denied"},
            )

    # Skip auth for docs, health check, dashboard, and static files.
    # Keep exact and prefix matches separate to avoid broad bypasses.
    public_exact_paths: set[str] = {
        "/api",
        "/api/status/health",
        "/api/memory/ingest",
        "/api/memory/ingest/",
    }
    if settings.dashboard_auth_mode == "public":
        public_exact_paths.add("/")
        public_exact_paths.add("/dashboard")
    if docs_enabled:
        public_exact_paths.update({"/redoc", "/openapi.json"})
    public_prefix_paths = []
    if settings.dashboard_auth_mode == "public":
        public_prefix_paths.append("/static/")
    if docs_enabled:
        public_prefix_paths.append("/docs")
    protected_prefix_paths = [
        # Keep ingest observability endpoints private even though they are GETs.
        "/api/memory/ingest/",
        # Provider visibility reveals sensitive operational state; keep it authenticated.
        "/api/v1/provider-status",
    ]
    is_api_path = request_path.startswith(f"{API_PREFIX}/")

    is_public = (
        request_path in public_exact_paths
        or any(request_path.startswith(path) for path in public_prefix_paths)
    )

    if is_public:
        return await call_next(request)

    requires_auth = (
        request.method in ["POST", "PUT", "PATCH", "DELETE"]
        or any(request_path.startswith(path) for path in protected_prefix_paths)
        or (
            settings.auth_mode == "all"
            and is_api_path
            and not is_public
        )
    )

    if requires_auth:
        if _api_cloudflare_auth_ok(request):
            return await call_next(request)

        if not request.headers.get("Authorization", "").startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authorization header"},
            )

        if not _bearer_is_valid(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token"},
            )

    return await call_next(request)


# Include routers
app.include_router(status.router, prefix=API_PREFIX)
app.include_router(harness.router, prefix=API_PREFIX)
app.include_router(workers.router, prefix=API_PREFIX)
app.include_router(tokens.router, prefix=API_PREFIX)
app.include_router(config.router, prefix=API_PREFIX)
app.include_router(memory.router, prefix=API_PREFIX)
app.include_router(hindsight_bank.router, prefix=API_PREFIX)
app.include_router(memory_ingest.router, prefix=API_PREFIX)
app.include_router(cron.router, prefix=API_PREFIX)
app.include_router(digest.router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(websocket.router, prefix=API_PREFIX)
app.include_router(provider_status.router, prefix=API_PREFIX)

# Mount web dashboard static files
STATIC_DIR = WEB_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Include web dashboard router
app.include_router(web_router)


@app.get("/api")
async def api_root():
    """API Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs" if docs_enabled else None,
        "api": API_PREFIX,
    }


@app.get("/")
async def root():
    """Redirect root traffic to dashboard host page."""
    return RedirectResponse(url="/dashboard", status_code=307)
