"""Localhost JSON for the React dashboard.

Data routes, one feature each: GET /api/job, GET /api/stats,
GET /api/snapshot, GET /api/regime, and GET /api/regime-brief. The page
lives in dashboard/web and calls job, stats, snapshot, and the regime
brief. SQLite stays here, opened read-only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dashboard.read import (
    JobStatus,
    Regime,
    Snapshot,
    Stats,
    load_job,
    load_regime,
    load_snapshot,
    load_stats,
    resolve_db_path,
)
from dashboard.regime_brief import brief_payload, load_regime_brief

DEFAULT_PORT = 8765
HOST = "127.0.0.1"

# Fields the React page reads. Keep these lists in sync with dashboard/web.
JOB_FIELDS = (
    "db_path",
    "db_exists",
    "error",
    "last_run_at",
    "last_run_status",
    "stale",
    "ingestion_running",
)
STATS_FIELDS = (
    "db_path",
    "db_exists",
    "db_size_bytes",
    "error",
    "indicator_count",
    "indicators_with_observations",
    "observation_count",
    "newest_observation_date",
)
SNAPSHOT_FIELDS = ("key", "label", "value", "unit", "date")
SNAPSHOT_RESPONSE_FIELDS = (
    "db_path",
    "db_exists",
    "error",
    "snapshot",
)
REGIME_FIELDS = (
    "db_path",
    "db_exists",
    "error",
    "datetime",
    "regime",
)


def make_server(port: int, db_path: Path) -> ThreadingHTTPServer:
    """Bind 127.0.0.1 only. Each request opens the database read-only."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if route == "/api/job":
                body = json.dumps(job_payload(load_job(db_path))).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
                return
            if route == "/api/stats":
                body = json.dumps(stats_payload(load_stats(db_path))).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
                return
            if route == "/api/snapshot":
                body = json.dumps(snapshot_payload(load_snapshot(db_path))).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
                return
            if route == "/api/regime":
                body = json.dumps(regime_payload(load_regime(db_path))).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
                return
            if route == "/api/regime-brief":
                body = json.dumps(brief_payload(load_regime_brief(db_path))).encode("utf-8")
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

    return ThreadingHTTPServer((HOST, port), Handler)


def job_payload(job: JobStatus) -> dict:
    return {
        "db_path": job.db_path,
        "db_exists": job.db_exists,
        "error": job.error,
        "last_run_at": job.last_run_at,
        "last_run_status": job.last_run_status,
        "stale": job.stale,
        "ingestion_running": job.ingestion_running,
    }


def stats_payload(stats: Stats) -> dict:
    return {
        "db_path": stats.db_path,
        "db_exists": stats.db_exists,
        "db_size_bytes": stats.db_size_bytes,
        "error": stats.error,
        "indicator_count": stats.indicator_count,
        "indicators_with_observations": stats.indicators_with_observations,
        "observation_count": stats.observation_count,
        "newest_observation_date": stats.newest_observation_date,
    }


def regime_payload(regime: Regime) -> dict:
    return {
        "db_path": regime.db_path,
        "db_exists": regime.db_exists,
        "error": regime.error,
        "datetime": regime.datetime,
        "regime": regime.regime,
    }


def snapshot_payload(snapshot: Snapshot) -> dict:
    return {
        "db_path": snapshot.db_path,
        "db_exists": snapshot.db_exists,
        "error": snapshot.error,
        "snapshot": [
            {
                "key": row.key,
                "label": row.label,
                "value": row.value,
                "unit": row.unit,
                "date": row.date,
            }
            for row in snapshot.rows
        ],
    }


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
    base = f"http://{HOST}:{args.port}"
    print(f"{base}/api/job", flush=True)
    print(f"{base}/api/stats", flush=True)
    print(f"{base}/api/snapshot", flush=True)
    print(f"{base}/api/regime", flush=True)
    print(f"{base}/api/regime-brief", flush=True)
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
