"""Hermes Web View - Dashboard module."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

# Get the web directory path
WEB_DIR = Path(__file__).parent

# Create router
router = APIRouter(tags=["web"])


def _asset_version() -> str:
    """Return a simple cache-busting version from the built asset mtimes."""
    static_root = WEB_DIR / "static"
    candidates = [
        static_root / "index.html",
        static_root / "css" / "dashboard.css",
        static_root / "js" / "dashboard.js",
    ]
    mtimes = [str(int(path.stat().st_mtime)) for path in candidates if path.exists()]
    return max(mtimes) if mtimes else "0"


def _render_dashboard_html() -> str:
    html_path = WEB_DIR / "templates" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    return html.replace("{{ asset_version }}", _asset_version())


def get_web_router() -> APIRouter:
    """Return the web dashboard router."""
    return router


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard HTML."""
    return _render_dashboard_html()


@router.get("/dashboard/{path:path}", response_class=HTMLResponse)
async def dashboard_routes(path: str):
    """Serve dashboard HTML for client-side routes."""
    del path
    return _render_dashboard_html()
