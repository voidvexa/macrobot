import { memo } from "react";
import { DASH, fmtValue, period, rawText } from "../lib/format.js";
import { freshnessBand, freshnessLabel, splitMatch } from "../lib/rows.js";

export const SeriesRow = memo(function SeriesRow({ row, needle, selected, tabStop, onSelect, onHover }) {
  const value = row.noData ? DASH : fmtValue(row.value, row.unit);
  const when = row.noData ? DASH : period(row.date, row.cadence);
  const age = row.age == null ? DASH : `${row.age}d`;
  const tag = row.noData ? "NO DATA" : row.stale ? "STALE" : null;
  const unit = row.unit ? ` ${row.unit}` : "";
  const band = freshnessBand(row);
  const freshText = freshnessLabel(row);
  const className = ["row", row.stale && "is-stale", selected && "is-sel"].filter(Boolean).join(" ");

  return (
    <li
      className={className}
      role="option"
      aria-selected={selected}
      aria-label={rowLabel(row, value, when)}
      tabIndex={tabStop ? 0 : -1}
      data-key={row.key}
      title={`${row.key} · raw ${rawText(row.value)}${unit}`}
      onClick={() => onSelect(row.key)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(row.key);
        }
      }}
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") onHover(row.key);
      }}
    >
      <span className={`sq sq-${band}`} role="img" title={freshText} aria-label={freshText} />
      <span className="label">
        <span className="text">
          {splitMatch(row.label, needle).map((part, index) =>
            part.hit ? <mark key={index}>{part.text}</mark> : part.text,
          )}
        </span>
        {tag ? <span className="tag"> {tag}</span> : null}
      </span>
      <span className={!row.noData && row.value < 0 ? "val neg" : "val"}>{value}</span>
      <span className="unit">{row.unit}</span>
      <span className="per" title={row.date ?? undefined}>
        {when}
      </span>
      <span className="age">{age}</span>
    </li>
  );
});

function rowLabel(row, value, when) {
  if (row.noData) return `${row.label} · no data`;
  const unit = row.unit ? ` ${row.unit}` : "";
  const old = row.age === 1 ? "1 day old" : `${row.age} days old`;
  const band = freshnessBand(row);
  const state = band === "ok" ? "fresh" : band;
  return `${row.label} ${value}${unit} · ${when} · ${old} · ${state}`;
}
