"""Localhost JSON for the React dashboard.

GET /api/status is the only data route. The page lives in dashboard/web and
calls this API. SQLite stays here, opened read-only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dashboard.read import DashboardStatus, load_status, resolve_db_path

DEFAULT_PORT = 8765
HOST = "127.0.0.1"

# Fields the React page reads. Keep this list in sync with dashboard/web.
STATUS_FIELDS = (
    "db_path",
    "db_exists",
    "db_size_bytes",
    "error",
    "indicator_count",
    "indicators_with_observations",
    "observation_count",
    "last_run_at",
    "last_run_status",
    "stale",
    "newest_observation_date",
    "ingestion_running",
    "snapshot",
)
SNAPSHOT_FIELDS = ("key", "label", "value", "unit", "date")


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True


def make_server(port: int, db_path: Path) -> ThreadingHTTPServer:
    """Bind 127.0.0.1 only. Each request opens the database read-only."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if route == "/api/status":
                body = json.dumps(status_payload(load_status(db_path))).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
                return
            if route in ("/", "/index.html"):
                message = (
                    "macrobot api. the page is the react app: "
                    "npm --prefix dashboard/web run dev\n"
                )
                self._send(200, message.encode("utf-8"), "text/plain; charset=utf-8")
                return
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return _Server((HOST, port), Handler)


def status_payload(status: DashboardStatus) -> dict:
    """JSON object the React page renders. Stats first, then the snapshot."""
    payload = {
        "db_path": status.db_path,
        "db_exists": status.db_exists,
        "db_size_bytes": status.db_size_bytes,
        "error": status.error,
        "indicator_count": status.indicator_count,
        "indicators_with_observations": status.indicators_with_observations,
        "observation_count": status.observation_count,
        "last_run_at": status.last_run_at,
        "last_run_status": status.last_run_status,
        "stale": status.stale,
        "newest_observation_date": status.newest_observation_date,
        "ingestion_running": status.ingestion_running,
        "snapshot": [
            {
                "key": row.key,
                "label": row.label,
                "value": row.value,
                "unit": row.unit,
                "date": row.date,
            }
            for row in status.snapshot
        ],
    }
    missing = [name for name in STATUS_FIELDS if name not in payload]
    if missing:
        raise RuntimeError(f"status payload missing {missing}")
    return payload


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Read-only Macrobot API (localhost).")
    parser.add_argument(
        "--port",
        type=int,
        default=_port_from_env(),
        help=f"port on 127.0.0.1 (default {DEFAULT_PORT}, or DASHBOARD_PORT)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="sqlite file (default: SQLITE_DB_PATH from the environment or .env, else data/macrobot.db)",
    )
    args = parser.parse_args(argv)
    db_path = resolve_db_path(args.db)
    server = make_server(args.port, db_path)
    print(f"Macrobot API reading {db_path}", flush=True)
    print(f"http://{HOST}:{args.port}/api/status", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        server.server_close()


def _port_from_env() -> int:
    raw = os.environ.get("DASHBOARD_PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        print(f"DASHBOARD_PORT={raw!r} is not a port; using {DEFAULT_PORT}", file=sys.stderr)
        return DEFAULT_PORT
    return port


if __name__ == "__main__":
    main()
