#!/usr/bin/env python3
"""Startup script for Mission Control API."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _load_runtime_env() -> None:
    """Load local and Hermes profile env files for direct/manual runs."""
    project_env = Path(__file__).resolve().parent / ".env"
    load_dotenv(project_env, override=False)

    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    hermes_env = hermes_home / ".env"
    load_dotenv(hermes_env, override=False)


def main():
    """Start the API server."""
    parser = argparse.ArgumentParser(description="Mission Control API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    # Set environment variables
    if args.debug:
        os.environ["DEBUG"] = "true"

    _load_runtime_env()

    # Import here to ensure env vars are set
    import uvicorn

    print(f"Starting Mission Control API on {args.host}:{args.port}")
    print(f"Docs available at http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="debug" if args.debug else "info",
    )


if __name__ == "__main__":
    main()
