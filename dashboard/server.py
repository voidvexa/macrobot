"""One localhost page: database stats, then the latest snapshot."""

from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dashboard.read import DashboardStatus, SnapshotRow, load_status, parse_run_timestamp, resolve_db_path

DEFAULT_PORT = 8765
HOST = "127.0.0.1"

# Layout only. Colors, type, and status styling are unset on purpose.
# Class names (stat, ok, warn, bad, idle) are hooks for a later pass.
PAGE_CSS = """
main { max-width: 60rem; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 0.5rem; }
.stat { border: 1px solid; padding: 0.5rem; }
.stat .s { display: block; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid; padding: 0.25rem 0.5rem; text-align: left; }
td.num, th.num { text-align: right; }
"""


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
            if route not in ("/", "/index.html"):
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            body = render_page(load_status(db_path)).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return _Server((HOST, port), Handler)


def render_page(status: DashboardStatus, now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    rows = "\n".join(_row_html(row) for row in status.snapshot)
    if not rows:
        rows = '<tr><td colspan="5">No snapshot. series_metadata has no rows, or the database could not be read.</td></tr>'
    banner = _banner(status)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Macrobot</title>\n"
        '<meta http-equiv="refresh" content="60">\n'
        "<style>\n"
        f"{PAGE_CSS}"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        "<h1>Macrobot</h1>\n"
        '<p class="lead">Read-only view of the local database. Cron still owns ingestion.</p>\n'
        f"{banner}"
        '<section class="stats">\n'
        f"{_stats_html(status, moment)}"
        "</section>\n"
        "<h2>Latest snapshot</h2>\n"
        "<table>\n"
        "<thead><tr>"
        "<th>Key</th><th>Label</th><th class=\"num\">Value</th><th>Unit</th><th>Date</th>"
        "</tr></thead>\n"
        f"<tbody>\n{rows}\n</tbody>\n"
        "</table>\n"
        "<footer>Localhost only. This page does not write the database. Refresh is every 60 seconds.</footer>\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Read-only Macrobot dashboard (localhost).")
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
    print(f"Macrobot dashboard reading {db_path}", flush=True)
    print(f"http://{HOST}:{args.port}/", flush=True)
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


def _banner(status: DashboardStatus) -> str:
    if not status.db_exists:
        return (
            '<p class="notice">Database file is not there yet: '
            f"<code>{html.escape(status.db_path)}</code>. "
            "The cron job creates it on the first successful run.</p>\n"
        )
    if status.error:
        return (
            '<p class="notice">Could not read the database '
            f"(<code>{html.escape(status.db_path)}</code>): "
            f"{html.escape(status.error)}</p>\n"
        )
    return ""


def _stats_html(status: DashboardStatus, now: datetime) -> str:
    indicators = _pair(status.indicator_count, status.indicators_with_observations)
    observations = _num(status.observation_count)
    run_text, run_class = _run_text(status, now)
    fresh_text, fresh_class = _fresh_text(status)
    proc_text = "running" if status.ingestion_running else "idle"
    proc_class = "ok" if status.ingestion_running else "idle"
    size = _size_text(status)
    newest = html.escape(status.newest_observation_date or "—")
    return (
        _card("Indicators", indicators, "in series_metadata, and how many have an observation")
        + _card("Observations", observations, "rows in observations")
        + _card("Last run", run_text, "last_run_at and last_run_status", value_class=run_class)
        + _card("Freshness", fresh_text, "stale when last_run_at is older than 2 hours", value_class=fresh_class)
        + _card("Ingestion process", proc_text, "python main.py on this host; idle between cron runs", value_class=proc_class)
        + _card("Database", size, status.db_path)
        + _card("Newest observation", newest, "MAX(date) across observations")
    )


def _card(label: str, value: str, detail: str, value_class: str = "") -> str:
    klass = f" v {value_class}".rstrip() if value_class else "v"
    # value may already contain markup (spans). Callers pass either escaped
    # text or a small trusted fragment built in this module.
    return (
        '<div class="stat">'
        f'<div class="k">{html.escape(label)}</div>'
        f'<div class="{klass}">{value}</div>'
        f'<div class="s">{html.escape(detail)}</div>'
        "</div>\n"
    )


def _pair(total: int | None, with_obs: int | None) -> str:
    if total is None:
        return "—"
    observed = "—" if with_obs is None else str(with_obs)
    return f"{total} <span class=\"s\">/ {observed} with data</span>"


def _num(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def _run_text(status: DashboardStatus, now: datetime) -> tuple[str, str]:
    if not status.db_exists or status.error:
        return "—", ""
    when = status.last_run_at or "missing"
    state = status.last_run_status or "missing"
    age = _age_phrase(status.last_run_at, now)
    css = _status_class(status.last_run_status)
    text = f"{html.escape(when)} UTC · {html.escape(state)}"
    if age:
        text += f" · {html.escape(age)}"
    return text, css


def _fresh_text(status: DashboardStatus) -> tuple[str, str]:
    if status.stale is None:
        return "—", ""
    if status.stale:
        return "stale", "warn"
    return "current", "ok"


def _status_class(status: str | None) -> str:
    if status == "ok":
        return "ok"
    if status == "partial":
        return "warn"
    if status == "failed":
        return "bad"
    return ""


def _age_phrase(last_run_at: str | None, now: datetime) -> str:
    parsed = parse_run_timestamp(last_run_at)
    if parsed is None:
        return ""
    seconds = int((now - parsed).total_seconds())
    if seconds < 0:
        return "clock is behind this timestamp"
    if seconds < 90:
        return f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hours ago"
    return f"{hours // 24} days ago"


def _size_text(status: DashboardStatus) -> str:
    if status.db_size_bytes is None:
        return "—"
    return f"{_format_bytes(status.db_size_bytes)} ({status.db_size_bytes:,} bytes)"


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{n} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def _row_html(row: SnapshotRow) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(row.key)}</td>"
        f"<td>{html.escape(row.label)}</td>"
        f'<td class="num">{html.escape(_format_value(row.value))}</td>'
        f"<td>{html.escape(row.unit or '')}</td>"
        f"<td>{html.escape(row.date or '—')}</td>"
        "</tr>"
    )


def _format_value(value: float | None) -> str:
    if value is None:
        return "—"
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


if __name__ == "__main__":
    main()
