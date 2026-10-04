import { useEffect, useState } from "react";

export default function App() {
  const [job, setJob] = useState(null);
  const [stats, setStats] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [jobPayload, statsPayload, snapshotPayload] = await Promise.all([
          getJson("/api/job"),
          getJson("/api/stats"),
          getJson("/api/snapshot"),
        ]);
        if (!cancelled) {
          setJob(jobPayload);
          setStats(statsPayload);
          setSnapshot(snapshotPayload);
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
      <p>powered by <a href="https://github.com/voidvexa/macrobot" target="_blank" rel="noopener noreferrer">macrobot</a></p>
      {error ? <p className="notice">api: {error}</p> : null}
      {readNotice(job, stats, snapshot)}
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
          {snapshotRows(snapshot)}
        </tbody>
      </table>
      <h2>status</h2>
      <table className="readout">
        <tbody>
          <Row label="indicators" value={indicatorText(stats)} />
          <Row label="observations" value={stats ? formatCount(stats.observation_count) : "—"} />
          <Row label="last_run" value={job ? runText(job, now) : "—"} />
          <Row label="freshness" value={freshText(job)} />
          <Row label="ingestion" value={job ? (job.ingestion_running ? "running" : "idle") : "—"} />
          <Row label="database" value={stats ? formatBytes(stats.db_size_bytes) : "—"} />
          <Row label="path" value={stats?.db_path ?? "—"} path />
          <Row label="newest" value={stats?.newest_observation_date || "—"} />
        </tbody>
      </table>
      <p className="credit">powered by ©<a href="https://github.com/voidvexa" target="_blank" rel="noopener noreferrer">voidvexa</a></p>
    </main>
  );
}

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`api ${response.status}`);
  }
  return response.json();
}

function readNotice(job, stats, snapshot) {
  const parts = [job, stats, snapshot].filter(Boolean);
  const missing = parts.find((item) => item.db_exists === false);
  if (missing) {
    return (
      <p className="notice">
        database file is not there yet: {missing.db_path}. the cron job creates it on the first run.
      </p>
    );
  }
  const failed = parts.find((item) => item.error);
  if (!failed) {
    return null;
  }
  return (
    <p className="notice">
      could not read the database ({failed.db_path}): {failed.error}
    </p>
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

function snapshotRows(snapshot) {
  const rows = snapshot?.snapshot ?? [];
  if (!snapshot) {
    return (
      <tr>
        <td colSpan={5}>waiting for /api/snapshot</td>
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

function indicatorText(stats) {
  if (!stats || stats.indicator_count == null) {
    return "—";
  }
  const observed = stats.indicators_with_observations == null ? "—" : String(stats.indicators_with_observations);
  return `${stats.indicator_count} / ${observed} with data`;
}

function formatCount(value) {
  if (value == null) {
    return "—";
  }
  return Number(value).toLocaleString("en-US");
}

function runText(job, now) {
  if (!job.db_exists || job.error) {
    return "—";
  }
  const when = job.last_run_at || "missing";
  const state = job.last_run_status || "missing";
  const age = agePhrase(job.last_run_at, now);
  return age ? `${when} UTC  ${state}  ${age}` : `${when} UTC  ${state}`;
}

function freshText(job) {
  if (!job || job.stale == null) {
    return "—";
  }
  return job.stale ? "stale" : "current";
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
  return Number(value).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
}
