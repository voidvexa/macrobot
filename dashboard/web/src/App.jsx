import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { CategoryPanel } from "./components/CategoryPanel.jsx";
import { DeskGrid } from "./components/DeskGrid.jsx";
import { Inspector } from "./components/Inspector.jsx";
import { RegimeBrief } from "./components/RegimeBrief.jsx";
import { StatusLine } from "./components/StatusLine.jsx";
import { Toolbar } from "./components/Toolbar.jsx";
import {
  DASH,
  DAY,
  ago,
  fmtBytes,
  fmtCount,
  jobTone,
  localStamp,
  parseUtc,
  statusTone,
  utcStamp,
} from "./lib/format.js";
import { buildRows, cadenceSummary, countStale, groupsOf, matches, sortRows, toNeedle } from "./lib/rows.js";
import { CATEGORIES, SORTS } from "./lib/series.js";
import { useNow } from "./lib/useNow.js";

const params = new URLSearchParams(window.location.search);
const START = {
  cat: params.get("cat") || "all",
  query: params.get("q") ?? "",
  rule: params.get("rule") === "strict" ? "strict" : "cadence",
  sel: params.get("sel") || null,
};

// StrictMode mounts effects twice in development; sharing one promise keeps
// each route to a single request per load.
let pageLoad = null;

function loadPage() {
  pageLoad ??= Promise.all([
    getJson("/api/job"),
    getJson("/api/stats"),
    getJson("/api/snapshot"),
    getJson("/api/regime-brief"),
  ]);
  return pageLoad;
}

export default function App() {
  const [job, setJob] = useState(null);
  const [stats, setStats] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [brief, setBrief] = useState(null);
  const [briefOpen, setBriefOpen] = useState(true);
  const [mark, setMark] = useState(null);
  const [error, setError] = useState(null);
  const [cat, setCat] = useState(START.cat);
  const [query, setQuery] = useState(START.query);
  const [rule, setRule] = useState(START.rule);
  const [sort, setSort] = useState("group");
  const [sel, setSel] = useState(START.sel);
  const [hover, setHover] = useState(null);
  const [closed, setClosed] = useState(() => new Set());
  const filterRef = useRef(null);
  const today = Math.floor(useNow(60_000) / DAY) * DAY;

  useEffect(() => {
    let cancelled = false;
    loadPage().then(
      ([jobPayload, statsPayload, snapshotPayload, briefPayload]) => {
        if (!cancelled) {
          setJob(jobPayload);
          setStats(statsPayload);
          setSnapshot(snapshotPayload);
          setBrief(briefPayload);
        }
      },
      (err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const needle = toNeedle(query);
  const rows = useMemo(() => buildRows(snapshot?.snapshot ?? [], today, rule), [snapshot, today, rule]);
  const groups = useMemo(() => groupsOf(rows), [rows]);
  const matched = useMemo(() => rows.filter((row) => matches(row, needle)), [rows, needle]);
  const tabs = groups.map((group, index) => ({
    cat: group.cat,
    digit: index + 1,
    count: matched.filter((row) => row.cat === group.cat).length,
  }));
  const activeCat = tabs.some((tab) => tab.cat.id === cat) ? cat : "all";
  const panels = groups
    .filter((group) => activeCat === "all" || group.cat.id === activeCat)
    .map((group) => ({
      cat: group.cat,
      rows: sortRows(
        matched.filter((row) => row.cat === group.cat),
        sort,
      ),
      open: needle !== "" || !closed.has(group.cat.id),
    }))
    .filter((panel) => panel.rows.length > 0);
  const visible = panels.flatMap((panel) => (panel.open ? panel.rows : []));
  const active = visible.find((row) => row.key === hover) ?? visible.find((row) => row.key === sel) ?? null;
  const tone = jobTone(job, stats, snapshot, error);
  const loaded = snapshot != null;

  const select = useCallback((key) => setSel((current) => (current === key ? null : key)), []);
  const toggleRule = () => setRule((current) => (current === "strict" ? "cadence" : "strict"));
  const cycleSort = () => setSort((current) => SORTS[(SORTS.indexOf(current) + 1) % SORTS.length]);

  function togglePanel(id) {
    if (needle) return;
    setClosed((previous) => {
      const next = new Set(previous);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  function move(step) {
    if (visible.length === 0) return;
    const at = visible.findIndex((row) => row.key === sel);
    const next = at < 0 ? visible[0] : visible[Math.min(Math.max(at + step, 0), visible.length - 1)];
    setSel(next.key);
    setHover(null);
    const element = document.querySelector(`[data-key="${CSS.escape(next.key)}"]`);
    if (element) {
      element.focus({ preventScroll: true });
      element.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    }
  }

  const onKey = useEffectEvent((event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
    const input = filterRef.current;
    if (event.key === "Escape") {
      setQuery("");
      setSel(null);
      input?.blur();
      return;
    }
    if (document.activeElement === input) return;
    if (event.key === "/") {
      event.preventDefault();
      input?.focus();
    } else if (event.key === "0") {
      setCat("all");
    } else if (/^[1-9]$/.test(event.key)) {
      const tab = tabs[Number(event.key) - 1];
      if (tab) setCat(tab.cat.id);
    } else if (event.key === "j" || event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "k" || event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "s") {
      toggleRule();
    } else if (event.key === "o") {
      cycleSort();
    } else if (event.key === "b") {
      event.preventDefault();
      setBriefOpen((current) => !current);
    }
  });

  useEffect(() => {
    const listener = (event) => onKey(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  let note = null;
  if (!loaded && !error) {
    note = <Note>waiting for /api/snapshot</Note>;
  } else if (rows.length === 0) {
    note = <Note>no snapshot. series_metadata has no rows, or the database could not be read.</Note>;
  } else if (panels.length === 0) {
    note = <p className="empty">no match for "{query.trim()}" — esc to clear</p>;
  }

  return (
    <div className="desk">
      <StatusLine job={job} stats={stats} tone={tone}>
        <h1 className="seg logo">
          <b className="logo-mark">ALMA</b> <small>MACRO DESK</small>
        </h1>
      </StatusLine>
      <Toolbar
        inputRef={filterRef}
        query={query}
        onQuery={setQuery}
        tabs={tabs}
        total={matched.length}
        cat={activeCat}
        onCat={setCat}
        rule={rule}
        onRule={toggleRule}
        sort={sort}
        onSort={cycleSort}
      />
      <main className="page">
        {tone.banner ? (
          <p className="banner" role="alert">
            {tone.banner}
          </p>
        ) : null}
        <RegimeBrief brief={brief} open={briefOpen} onToggle={() => setBriefOpen((current) => !current)} onMark={setMark} />
        <DeskGrid
          panels={note ? [] : panels}
          renderPanel={(panel, slot) => (
            <CategoryPanel
              key={panel.cat.id}
              cat={panel.cat}
              rows={panel.rows}
              open={panel.open}
              onToggle={togglePanel}
              needle={needle}
              sel={sel}
              onSelect={select}
              onHover={setHover}
              marked={mark}
              slot={slot}
            />
          )}
          prelude={<h2 className="sr-only">latest snapshot</h2>}
          onPointerLeave={() => setHover(null)}
        >
          {note}
          {activeCat === "all" && needle === "" ? (
            <SystemPanel job={job} stats={stats} rows={rows} rule={rule} />
          ) : null}
        </DeskGrid>
      </main>
      <Inspector
        row={active}
        total={loaded ? rows.length : null}
        stale={countStale(rows)}
        rule={rule}
        groups={tabs.length || CATEGORIES.length}
      >
        <p className="credit">powered by ©voidvexa</p>
      </Inspector>
    </div>
  );
}

function SystemPanel({ job, stats, rows, rule }) {
  const now = useNow();
  const at = parseUtc(job?.last_run_at);
  const status = job?.last_run_status;
  const cadences = cadenceSummary(rows, rule);
  return (
    <section className="panel panel-system" aria-labelledby="system-head">
      <div className="panel-head" id="system-head">
        <span className="glyph" aria-hidden="true">
          #
        </span>{" "}
        <h2>status</h2> <span className="panel-name">· freshness</span>
        <span className="rule" aria-hidden="true" /> <span className="meta">read-only</span>
      </div>
      <div className="system-body">
        <dl className="facts">
          <Fact name="last run" value={utcStamp(at)} extra={status ?? DASH} tone={status ? statusTone(status) : null} />
          <Fact name="local" value={localStamp(at)} extra={ago(at, now)} />
          <Fact
            name="ingestion"
            value={job ? (job.ingestion_running ? "running" : "idle") : DASH}
            extra={job?.stale == null ? DASH : job.stale ? "job stale" : "job current"}
            tone={job?.stale ? "warn" : null}
          />
          <Fact name="database" value={stats?.db_path ?? job?.db_path ?? DASH} extra={fmtBytes(stats?.db_size_bytes)} />
          <Fact
            name="observations"
            value={fmtCount(stats?.observation_count)}
            extra={`newest ${stats?.newest_observation_date || DASH}`}
          />
        </dl>
        {cadences.length > 0 ? (
          <div className="system-cadence">
            <hr className="sep" />
            <dl className="facts">
              {cadences.map((group) => (
                <Fact
                  key={group.cadence}
                  name={group.cadence}
                  value={`${group.count} series · oldest ${group.oldest == null ? DASH : `${group.oldest}d`} · limit ${group.limit}d`}
                  extra={group.stale > 0 ? `${group.stale} stale` : "ok"}
                  tone={group.stale > 0 ? "warn" : "ok"}
                />
              ))}
            </dl>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Fact({ name, value, extra, tone }) {
  return (
    <div className="fact">
      <dt>{name}</dt>
      <dd className="v">{value}</dd>
      <dd className={tone ? `x tone-${tone}` : "x"}>{extra}</dd>
    </div>
  );
}

function Note({ children }) {
  return (
    <div className="panel panel-note">
      <p>{children}</p>
    </div>
  );
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`api ${response.status}`);
  }
  return response.json();
}
