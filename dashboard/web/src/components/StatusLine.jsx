import { DASH, ago, clockTime, fmtBytes, fmtCount, localTime, parseUtc, utcStamp, utcTime } from "../lib/format.js";
import { useNow } from "../lib/useNow.js";

export function StatusLine({ job, stats, tone, children }) {
  const series =
    stats?.indicator_count == null ? DASH : `${stats.indicators_with_observations ?? DASH}/${stats.indicator_count}`;
  return (
    <header className="statusline">
      {children}
      <RunSegment job={job} tone={tone} />
      <Segment name="INGEST">{job ? (job.ingestion_running ? "running" : "idle") : DASH}</Segment>
      <Segment name="SERIES">{series}</Segment>
      <Segment name="OBS" className="seg-obs">
        {fmtCount(stats?.observation_count)}
      </Segment>
      <span className="seg seg-db">
        <span className="k">DB</span>
        <span className="v">{fmtBytes(stats?.db_size_bytes)}</span>
        {stats?.db_path ? <span className="path">{stats.db_path}</span> : null}
      </span>
      <Segment name="NEWEST">{stats?.newest_observation_date || DASH}</Segment>
      <span className="spacer" aria-hidden="true" />
      <Clock />
    </header>
  );
}

function Segment({ name, className = "", children }) {
  return (
    <span className={`seg ${className}`}>
      <span className="k">{name}</span>
      <span className="v">{children}</span>
    </span>
  );
}

function RunSegment({ job, tone }) {
  const now = useNow();
  const at = parseUtc(job?.last_run_at);
  return (
    <span
      className={`seg seg-run tone-${tone.tone}`}
      role="status"
      title={at == null ? undefined : utcStamp(at)}
    >
      <span className="dot" aria-hidden="true" />
      <span className="run-label">RUN {tone.label}</span>
      <span className="utc">{utcTime(at)}</span>
      <span className="local">· {localTime(at)} local</span>
      <span aria-live="off">· {ago(at, now)}</span>
    </span>
  );
}

function Clock() {
  const now = useNow();
  return <span className="seg seg-clock">{clockTime(now)}</span>;
}
