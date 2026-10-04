// node --test dashboard/web/src/lib/spec.test.js
import assert from "node:assert/strict";
import { test } from "node:test";
import { ago, ageDays, fmtBytes, fmtCount, fmtValue, jobTone, parseUtc, period, utcStamp, utcTime } from "./format.js";
import { arrangeColumns } from "./columns.js";
import { buildRows, cadenceLetters, cadenceSummary, countStale, freshnessBand, freshnessLabel, groupsOf, matches, sortRows, splitMatch } from "./rows.js";
import { cadenceOf } from "./series.js";

// Spec 6.6: key, raw unit, raw value, date, rendered value + unit, period.
const SPEC_ROWS = [
  ["effr", "%", 3.88, "2026-10-01", "3.88 %", "Oct 1"],
  ["sofr", "%", 3.87, "2026-10-01", "3.87 %", "Oct 1"],
  ["sofr_effr_spread", "%", -0.01, "2026-10-01", "−0.01 %", "Oct 1"],
  ["usblr", "%", 7, "2026-10-01", "7.0 %", "Oct 1"],
  ["us10y", "%", 5.24, "2026-10-01", "5.24 %", "Oct 1"],
  ["t10y2y", "%", 0.45, "2026-10-02", "0.45 %", "Oct 2"],
  ["t10y3m", "%", 1.09, "2026-10-02", "1.09 %", "Oct 2"],
  ["cpi", "%", 3.4, "2026-08-01", "3.4 %", "Aug 2026"],
  ["core_cpi", "%", 2.4, "2026-08-01", "2.4 %", "Aug 2026"],
  ["pce", "%", 3.4, "2026-08-01", "3.4 %", "Aug 2026"],
  ["core_pce", "%", 3, "2026-08-01", "3.0 %", "Aug 2026"],
  ["ppi", "%", 5.4, "2026-08-01", "5.4 %", "Aug 2026"],
  ["t5yie", "%", 2.37, "2026-10-02", "2.37 %", "Oct 2"],
  ["t5yifr", "%", 2.35, "2026-10-02", "2.35 %", "Oct 2"],
  ["unrate", "%", 4.2, "2026-09-01", "4.2 %", "Sep 2026"],
  ["payems", " K", 159044, "2026-09-01", "159,044 K", "Sep 2026"],
  ["icsa", "", 197000, "2026-09-26", "197,000", "Sep 26"],
  ["ccsa", "", 1701000, "2026-09-19", "1,701,000", "Sep 19"],
  ["ahe", "%", 3, "2026-09-01", "3.0 %", "Sep 2026"],
  ["real_gdp", " B", 24408.011, "2026-04-01", "24,408 B", "Q2 2026"],
  ["real_pce", " B", 16955.3, "2026-08-01", "16,955.3 B", "Aug 2026"],
  ["rsafs", " B", 737.763, "2026-08-01", "737.76 B", "Aug 2026"],
  ["indpro", "%", 1.4, "2026-08-01", "1.4 %", "Aug 2026"],
  ["cfnai", "", -0.04, "2026-08-01", "−0.04", "Aug 2026"],
  ["permit", " K", 1403, "2026-08-01", "1,403 K", "Aug 2026"],
  ["fed_net_liquidity", " B", 5847.831, "2026-10-02", "5,847.8 B", "Oct 2"],
  ["walcl", " B", 6743.031, "2026-09-30", "6,743 B", "Sep 30"],
  ["wresbal", " B", 2948.09, "2026-09-30", "2,948.1 B", "Sep 30"],
  ["rrp", " B", 1.501, "2026-10-02", "1.5 B", "Oct 2"],
  ["tga", " B", 893.699, "2026-10-01", "893.7 B", "Oct 1"],
  ["tga_weekly", " B", 984.046, "2026-09-30", "984.05 B", "Sep 30"],
  ["m2sl", " B", 23342.8, "2026-08-01", "23,342.8 B", "Aug 2026"],
  ["hy_spread", " bps", 324, "2026-10-01", "324 bps", "Oct 1"],
  ["ig_spread", " bps", 86, "2026-10-01", "86 bps", "Oct 1"],
  ["ccc_spread", " bps", 1215, "2026-10-01", "1,215 bps", "Oct 1"],
  ["drtscilm", "%", 0, "2026-07-01", "0.0 %", "Q3 2026"],
  ["totbkcr", " B", 19862.5105, "2026-09-23", "19,862.5 B", "Sep 23"],
  ["nfci", "", -0.548, "2026-09-25", "−0.548", "Sep 25"],
  ["stlfsi4", "", -0.8074, "2026-09-25", "−0.807", "Sep 25"],
  ["vix", "", 15.31, "2026-10-02", "15.31", "Oct 2"],
  ["move", "", 107.29, "2026-10-02", "107.29", "Oct 2"],
  ["skew", "", 144.88, "2026-10-02", "144.88", "Oct 2"],
  ["dtwexbgs", "", 120.33, "2026-09-25", "120.33", "Sep 25"],
];

test("every 6.6 row renders its value, unit and period", () => {
  assert.equal(SPEC_ROWS.length, 43);
  for (const [key, unit, value, date, rendered, when] of SPEC_ROWS) {
    const trimmed = unit.trim();
    const shown = trimmed ? `${fmtValue(value, unit)} ${trimmed}` : fmtValue(value, unit);
    assert.equal(shown, rendered, key);
    assert.equal(period(date, cadenceOf(key)), when, key);
  }
});

test("minus signs are U+2212 and null is an em dash", () => {
  assert.equal(fmtValue(-0.01, "%"), "\u22120.01");
  assert.ok(!fmtValue(-1234.5, "").includes("-"));
  assert.equal(fmtValue(null, "%"), "—");
  assert.equal(period(null, "daily"), "—");
});

test("age counts whole days from UTC midnight", () => {
  const now = Date.UTC(2026, 9, 4, 16, 47);
  assert.equal(ageDays("2026-10-02", now), 2);
  assert.equal(ageDays("2026-08-01", now), 64);
  assert.equal(ageDays("2026-04-01", now), 186);
  assert.equal(ageDays("2026-10-05", now), 0);
  assert.equal(ageDays(null, now), null);
});

test("last_run_at without a zone is UTC", () => {
  const at = parseUtc("2026-10-04 15:00:58");
  assert.equal(at, Date.UTC(2026, 9, 4, 15, 0, 58));
  assert.equal(parseUtc("2026-10-04T15:00:58Z"), at);
  assert.equal(utcTime(at), "15:00:58Z");
  assert.equal(utcStamp(at), "2026-10-04 15:00:58 UTC");
  assert.equal(parseUtc(null), null);
  assert.equal(parseUtc("not a time"), null);
});

test("relative time thresholds", () => {
  const now = Date.UTC(2026, 9, 4, 18, 0, 0);
  assert.equal(ago(now - 89_000, now), "89s ago");
  assert.equal(ago(now - 90_000, now), "1 min ago");
  assert.equal(ago(now - 89 * 60_000, now), "89 min ago");
  assert.equal(ago(now - 90 * 60_000, now), "1 h ago");
  assert.equal(ago(now - 47 * 3_600_000, now), "47 h ago");
  assert.equal(ago(now - 48 * 3_600_000, now), "2 d ago");
  assert.equal(ago(null, now), "—");
});

test("bytes and counts", () => {
  assert.equal(fmtBytes(2232320), "2.1 MB");
  assert.equal(fmtBytes(512), "512 B");
  assert.equal(fmtBytes(null), "—");
  assert.equal(fmtCount(20418), "20,418");
});

test("RUN tone takes the first matching rule", () => {
  const job = {
    db_path: "data/macrobot.db",
    db_exists: true,
    error: null,
    last_run_at: "2026-10-04 15:00:58",
    last_run_status: "ok",
    stale: false,
    ingestion_running: false,
  };
  const tone = (overrides, extra = {}) =>
    jobTone({ ...job, ...overrides }, extra.stats ?? {}, extra.snapshot ?? {}, extra.error ?? null);

  assert.deepEqual(tone({}, { error: "api 502" }), { tone: "bad", label: "API ERROR", banner: "api: api 502" });
  assert.equal(tone({ db_exists: false, ingestion_running: true }).label, "NO DB");
  assert.equal(
    tone({ db_exists: false }).banner,
    "database file is not there yet: data/macrobot.db. the cron job creates it on the first run.",
  );
  assert.equal(
    tone({}, { stats: { db_path: "x.db", error: "file is not a database" } }).banner,
    "could not read the database (x.db): file is not a database",
  );
  assert.deepEqual(tone({ ingestion_running: true, last_run_status: "failed" }), {
    tone: "run",
    label: "RUNNING",
    banner: null,
  });
  assert.equal(tone({ last_run_at: null, last_run_status: null }).label, "NO RUN YET");
  assert.deepEqual(tone({ last_run_status: "failed", stale: true }), { tone: "bad", label: "FAILED", banner: null });
  assert.deepEqual(tone({ stale: true, last_run_status: "partial" }), { tone: "warn", label: "STALE", banner: null });
  assert.deepEqual(tone({ last_run_status: "partial" }), { tone: "warn", label: "PARTIAL", banner: null });
  assert.deepEqual(tone({}), { tone: "ok", label: "OK", banner: null });
  assert.deepEqual(tone({ last_run_status: "skipped" }), { tone: "warn", label: "SKIPPED", banner: null });
  assert.equal(jobTone(null, null, null, null).label, "LOADING");
});

const NOW = Date.UTC(2026, 9, 4);
const SNAPSHOT = SPEC_ROWS.map(([key, unit, value, date]) => ({ key, label: key.toUpperCase(), value, unit, date }));

test("stale counts on the Oct 4 2026 data: 0 by cadence, 16 when strict", () => {
  assert.equal(countStale(buildRows(SNAPSHOT, NOW, "cadence")), 0);
  const strict = buildRows(SNAPSHOT, NOW, "strict");
  assert.equal(countStale(strict), 16);
  const byCadence = Object.groupBy(strict.filter((row) => row.stale), (row) => row.cadence);
  assert.equal(byCadence.monthly.length, 14);
  assert.equal(byCadence.quarterly.length, 2);
});

test("panels, counts and cadence letters follow the spec order", () => {
  const groups = groupsOf(buildRows(SNAPSHOT, NOW, "cadence"));
  assert.deepEqual(
    groups.map((group) => [group.cat.id, group.rows.length, cadenceLetters(group.rows)]),
    [
      ["rates", 7, "D"],
      ["inflation", 7, "M/D"],
      ["labor", 5, "M/W"],
      ["growth", 6, "Q/M"],
      ["liquidity", 7, "D/W/M"],
      ["credit", 7, "D/Q/W"],
      ["markets", 4, "D/W"],
    ],
  );
});

test("status panel cadence rows", () => {
  const rows = buildRows(SNAPSHOT, NOW, "cadence");
  assert.deepEqual(cadenceSummary(rows, "cadence"), [
    { cadence: "daily", count: 18, oldest: 3, limit: 6, stale: 0 },
    { cadence: "weekly", count: 9, oldest: 15, limit: 21, stale: 0 },
    { cadence: "monthly", count: 14, oldest: 64, limit: 95, stale: 0 },
    { cadence: "quarterly", count: 2, oldest: 186, limit: 225, stale: 0 },
  ]);
  assert.deepEqual(
    cadenceSummary(buildRows(SNAPSHOT, NOW, "strict"), "strict").map((group) => [group.limit, group.stale]),
    [
      [30, 0],
      [30, 0],
      [30, 14],
      [30, 2],
    ],
  );
});

test("freshness marker uses half the active limit, including the 30-day preview", () => {
  const cadence = Object.fromEntries(buildRows(SNAPSHOT, NOW, "cadence").map((row) => [row.key, row]));
  assert.equal(cadence.effr.age, 3);
  assert.equal(freshnessBand(cadence.effr), "ok");
  assert.equal(freshnessLabel(cadence.effr), "fresh, 3d of 6d");
  assert.equal(freshnessBand(cadence.t10y2y), "ok");
  assert.equal(freshnessLabel(cadence.ccsa), "aging, 15d of 21d");
  assert.equal(freshnessBand(cadence.totbkcr), "aging");
  assert.equal(freshnessBand(cadence.cpi), "aging");
  assert.equal(freshnessBand(cadence.unrate), "ok");
  assert.equal(freshnessBand(cadence.real_gdp), "aging");
  assert.equal(freshnessBand(cadence.drtscilm), "ok");

  const [dailyEdge] = buildRows(
    [{ key: "effr", label: "EFFR", value: 1, unit: "%", date: "2026-09-28" }],
    NOW,
    "cadence",
  );
  assert.equal(dailyEdge.age, 6);
  assert.equal(dailyEdge.stale, false);
  assert.equal(freshnessBand(dailyEdge), "aging");
  const [dailyOver] = buildRows(
    [{ key: "effr", label: "EFFR", value: 1, unit: "%", date: "2026-09-27" }],
    NOW,
    "cadence",
  );
  assert.equal(dailyOver.age, 7);
  assert.equal(freshnessBand(dailyOver), "stale");

  const strict = Object.fromEntries(buildRows(SNAPSHOT, NOW, "strict").map((row) => [row.key, row]));
  assert.equal(strict.ccsa.limit, 30);
  assert.equal(freshnessBand(strict.ccsa), "ok");
  assert.equal(freshnessLabel(strict.ccsa), "fresh, 15d of 30d");
  assert.equal(freshnessBand(strict.unrate), "stale");
  assert.equal(freshnessLabel(strict.unrate), "stale, 33d of 30d");
  const [aging] = buildRows(
    [{ key: "cpi", label: "CPI", value: 1, unit: "%", date: "2026-09-04" }],
    NOW,
    "strict",
  );
  assert.equal(aging.age, 30);
  assert.equal(freshnessBand(aging), "aging");
  assert.equal(freshnessLabel(aging), "aging, 30d of 30d");
  const [justOver] = buildRows(
    [{ key: "cpi", label: "CPI", value: 1, unit: "%", date: "2026-09-03" }],
    NOW,
    "strict",
  );
  assert.equal(justOver.age, 31);
  assert.equal(freshnessBand(justOver), "stale");

  const [empty] = buildRows([{ key: "cpi", label: "CPI", value: null, unit: "%", date: null }], NOW, "cadence");
  assert.equal(freshnessBand(empty), "empty");
  assert.equal(freshnessLabel(empty), "no data");
});

test("wide columns pack whole category panels as close as their heights allow", () => {
  const panels = [
    ["rates", 7],
    ["inflation", 7],
    ["labor", 5],
    ["growth", 6],
    ["liquidity", 7],
    ["credit", 7],
    ["markets", 4],
  ].map(([id, count]) => ({ cat: { id }, rows: Array(count), open: true }));
  const { place } = arrangeColumns(panels);
  assert.equal(place.get("rates").column, 0);
  assert.equal(place.get("inflation").column, 0);
  assert.equal(place.get("labor").column, 1);
  assert.equal(place.get("growth").column, 1);
  assert.equal(place.get("markets").column, 1);
  assert.equal(place.get("liquidity").column, 2);
  assert.equal(place.get("credit").column, 2);
  assert.equal(place.get("markets").top > place.get("growth").top, true);
  assert.equal(place.get("inflation").top > place.get("rates").top, true);
});

test("unknown keys go to Other, null rows are NO DATA and stale", () => {
  const rows = buildRows(
    [
      { key: "zz_new", label: "Zed", value: 1, unit: " pts", date: "2026-10-01" },
      { key: "aa_new", label: "Alpha", value: null, unit: "", date: null },
      { key: "vix", label: "VIX <script>", value: 20.5, unit: "", date: "2026-10-01" },
    ],
    NOW,
    "cadence",
  );
  const groups = groupsOf(rows);
  assert.deepEqual(
    groups.map((group) => group.cat.id),
    ["markets", "other"],
  );
  const other = sortRows(groups[1].rows, "group");
  assert.deepEqual(
    other.map((row) => row.label),
    ["Alpha", "Zed"],
  );
  assert.equal(other[0].noData, true);
  assert.equal(other[0].stale, true);
  assert.equal(other[0].age, null);
  assert.equal(other[1].unit, "pts");
  assert.equal(other[1].cadence, "monthly");
});

test("filter matches label or key, and the stale query", () => {
  const rows = buildRows(SNAPSHOT, NOW, "strict");
  const [t10y2y] = buildRows([{ key: "t10y2y", label: "10Y-2Y", value: 0.45, unit: "%", date: "2026-10-02" }], NOW, "strict");
  assert.ok(matches(t10y2y, "10y-2"));
  assert.ok(matches(t10y2y, "t10y2y"));
  assert.ok(!matches(t10y2y, "cpi"));
  assert.equal(rows.filter((row) => matches(row, "stale")).length, 16);
});

test("sorts break ties by label and put missing ages last", () => {
  const rows = buildRows(
    [
      { key: "b", label: "Bravo", value: 1, unit: "", date: "2026-10-01" },
      { key: "a", label: "Alpha", value: 1, unit: "", date: "2026-10-01" },
      { key: "n", label: "Null", value: null, unit: "", date: null },
      { key: "o", label: "Old", value: 1, unit: "", date: "2026-01-01" },
    ],
    NOW,
    "cadence",
  );
  const order = (sort) => sortRows(rows, sort).map((row) => row.key);
  assert.deepEqual(order("freshest"), ["a", "b", "o", "n"]);
  assert.deepEqual(order("oldest"), ["o", "a", "b", "n"]);
  assert.deepEqual(order("a-z"), ["a", "b", "n", "o"]);
});

test("match highlighting splits plain strings", () => {
  assert.deepEqual(splitMatch("10Y-2Y", "2y"), [
    { text: "10Y-", hit: false },
    { text: "2Y", hit: true },
  ]);
  assert.deepEqual(splitMatch("VIX <script>", "<scr"), [
    { text: "VIX ", hit: false },
    { text: "<scr", hit: true },
    { text: "ipt>", hit: false },
  ]);
  assert.deepEqual(splitMatch("CPI", ""), [{ text: "CPI", hit: false }]);
});
