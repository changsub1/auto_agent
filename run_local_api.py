"""Run the local-only FastAPI server for the desktop app."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from local_api import create_app


PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Orchestra local API server.")
    parser.add_argument("--host", default=os.environ.get("LOCAL_API_HOST", "127.0.0.1"), help="Bind host. Only localhost/127.0.0.1 is allowed.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCAL_API_PORT", "8765")), help="Bind port.")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload for development.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("The local API must bind to 127.0.0.1 or localhost.")
    target = "local_api:app" if args.reload else create_app(PROJECT_ROOT)
    uvicorn.run(target, host=args.host, port=args.port, reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
