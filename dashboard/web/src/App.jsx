import { useEffect, useState } from "react";

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch("/api/status");
        if (!response.ok) {
          throw new Error(`api ${response.status}`);
        }
        const payload = await response.json();
        if (!cancelled) {
          setData(payload);
          setError(null);
          setNow(Date.now());
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <header className="masthead">
        <h1>ALMA</h1>
        <p className="deck">
          <span>A LIGHTWEIGHT</span>
          <span>MACROECONOMIC</span>
          <span>ANALYST</span>
        </p>
      </header>
      <p>read-only. cron still writes.</p>
      {error ? <p className="notice">api: {error}</p> : null}
      {data && !data.db_exists ? (
        <p className="notice">
          database file is not there yet: {data.db_path}. the cron job creates it on the first run.
        </p>
      ) : null}
      {data?.error ? (
        <p className="notice">
          could not read the database ({data.db_path}): {data.error}
        </p>
      ) : null}
      <h2>latest snapshot</h2>
      <table>
        <thead>
          <tr>
            <th>key</th>
            <th>label</th>
            <th className="num">value</th>
            <th>unit</th>
            <th>date</th>
          </tr>
        </thead>
        <tbody>
          {snapshotRows(data)}
        </tbody>
      </table>
      <h2>status</h2>
      <table className="readout">
        <tbody>
          <Row label="indicators" value={indicatorText(data)} />
          <Row label="observations" value={data ? formatCount(data.observation_count) : "—"} />
          <Row label="last_run" value={data ? runText(data, now) : "—"} />
          <Row label="freshness" value={freshText(data)} />
          <Row label="ingestion" value={data ? (data.ingestion_running ? "running" : "idle") : "—"} />
          <Row label="database" value={data ? formatBytes(data.db_size_bytes) : "—"} />
          <Row label="path" value={data?.db_path ?? "—"} path />
          <Row label="newest" value={data?.newest_observation_date || "—"} />
        </tbody>
      </table>
      <footer>
        localhost only. this page does not write the database. stale when
        last_run_at is older than 2 hours. ingestion is idle between cron runs.
      </footer>
    </main>
  );
}

function Row({ label, value, path = false }) {
  return (
    <tr>
      <th>{label}</th>
      <td className={path ? "path" : "num"}>{value}</td>
    </tr>
  );
}

function snapshotRows(data) {
  const rows = data?.snapshot ?? [];
  if (!data) {
    return (
      <tr>
        <td colSpan={5}>waiting for /api/status</td>
      </tr>
    );
  }
  if (rows.length === 0) {
    return (
      <tr>
        <td colSpan={5}>no snapshot. series_metadata has no rows, or the database could not be read.</td>
      </tr>
    );
  }
  return rows.map((row) => (
    <tr key={row.key}>
      <td>{row.key}</td>
      <td>{row.label}</td>
      <td className="num">{formatValue(row.value)}</td>
      <td>{row.unit ?? ""}</td>
      <td>{row.date ?? "—"}</td>
    </tr>
  ));
}

function indicatorText(data) {
  if (!data || data.indicator_count == null) {
    return "—";
  }
  const observed = data.indicators_with_observations == null ? "—" : String(data.indicators_with_observations);
  return `${data.indicator_count} / ${observed} with data`;
}

function formatCount(value) {
  if (value == null) {
    return "—";
  }
  return Number(value).toLocaleString("en-US");
}

function runText(data, now) {
  if (!data.db_exists || data.error) {
    return "—";
  }
  const when = data.last_run_at || "missing";
  const state = data.last_run_status || "missing";
  const age = agePhrase(data.last_run_at, now);
  return age ? `${when} UTC  ${state}  ${age}` : `${when} UTC  ${state}`;
}

function freshText(data) {
  if (!data || data.stale == null) {
    return "—";
  }
  return data.stale ? "stale" : "current";
}

function agePhrase(lastRunAt, now) {
  const parsed = parseUtc(lastRunAt);
  if (parsed == null) {
    return "";
  }
  const seconds = Math.floor((now - parsed) / 1000);
  if (seconds < 0) {
    return "clock is behind this timestamp";
  }
  if (seconds < 90) {
    return `${seconds} seconds ago`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 90) {
    return `${minutes} minutes ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return `${hours} hours ago`;
  }
  return `${Math.floor(hours / 24)} days ago`;
}

function parseUtc(value) {
  if (!value) {
    return null;
  }
  const text = String(value).trim();
  if (!text) {
    return null;
  }
  const iso = text.includes("T") ? text : text.replace(" ", "T");
  const zoned = /(?:Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`;
  const parsed = Date.parse(zoned);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatBytes(n) {
  if (n == null) {
    return "—";
  }
  let size = n;
  const units = ["B", "KB", "MB", "GB"];
  let unit = units[0];
  for (let i = 0; i < units.length; i += 1) {
    unit = units[i];
    if (size < 1024 || unit === "GB") {
      break;
    }
    size /= 1024;
  }
  const shown = unit === "B" ? `${n} B` : `${size.toFixed(1)} ${unit}`;
  return `${shown} (${Number(n).toLocaleString("en-US")} bytes)`;
}

function formatValue(value) {
  if (value == null) {
    return "—";
  }
  const text = Number(value).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  return text || "0";
}
