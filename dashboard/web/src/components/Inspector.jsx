import { DASH, rawText } from "../lib/format.js";
import { RULE_TEXT } from "./Toolbar.jsx";

export function Inspector({ row, total, stale, rule, groups }) {
  return (
    <div className="inspector" aria-live="polite">
      {row ? <RowDetail row={row} /> : <Hint total={total} stale={stale} rule={rule} groups={groups} />}
    </div>
  );
}

function RowDetail({ row }) {
  const state = row.noData ? "NO DATA" : row.stale ? "STALE" : "FRESH";
  return (
    <>
      <b className="i-label">{row.label}</b> <span className="i-dim">{row.key}</span>{" "}
      <span>
        <span className="i-dim">raw</span> <b className="i-v">{rawText(row.value)}</b>
        {row.unit ? <span className="i-dim"> {row.unit}</span> : null}
      </span>{" "}
      <span>
        <span className="i-dim">obs</span> <b className="i-v">{row.date ?? DASH}</b>
      </span>{" "}
      <span className="i-dim i-cadence">
        {row.cadence} · age {row.age == null ? DASH : `${row.age}d`} / limit {row.limit}d
      </span>{" "}
      <b className={row.stale ? "i-state is-stale" : "i-state"}>{state}</b>{" "}
      <span className="i-dim i-end i-cat">{row.cat.name}</span>
    </>
  );
}

function Hint({ total, stale, rule, groups }) {
  return (
    <>
      <span>
        <span className="on-hover">hover or j/k to inspect a series</span>
        <span className="on-touch">tap a row to inspect</span>
      </span>{" "}
      {total == null ? null : (
        <span>
          {total} series · {stale} stale ({RULE_TEXT[rule]})
        </span>
      )}{" "}
      <span className="i-dim i-end i-hints">
        / filter · 0-{groups} group · j/k move · s stale rule · o sort · esc clear
      </span>
    </>
  );
}
