import { cadenceLetters, countStale } from "../lib/rows.js";
import { SeriesRow } from "./SeriesRow.jsx";

export function CategoryPanel({ cat, rows, open, onToggle, needle, sel, onSelect, onHover, marked, slot }) {
  const stale = countStale(rows);
  const listId = `rows-${cat.id}`;
  const nameId = `panel-${cat.id}`;
  const tabStop = rows.some((row) => row.key === sel) ? sel : rows[0]?.key;

  return (
    <section
      className={open ? "panel" : "panel is-closed"}
      data-panel={cat.id}
      style={{
        "--c": `var(--c-${cat.id})`,
        ...(slot ? { "--col": String(slot.column), "--top": `${slot.top}px` } : null),
      }}
      aria-labelledby={nameId}
    >
      <h3>
        <button
          type="button"
          className="panel-head"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => onToggle(cat.id)}
        >
          <span className="glyph" aria-hidden="true">
            {open ? "−" : "+"}
          </span>{" "}
          <span className="panel-name" id={nameId}>
            {cat.name}
          </span>
          <span className="rule" aria-hidden="true" />{" "}
          <span className="meta">
            {stale > 0 ? <span className="flag">{stale}! </span> : null}
            {rows.length} · {cadenceLetters(rows)}
          </span>
        </button>
      </h3>
      <ul className="rows" id={listId} role="listbox" aria-labelledby={nameId} hidden={!open}>
        {rows.map((row) => (
          <SeriesRow
            key={row.key}
            row={row}
            needle={needle}
            selected={row.key === sel}
            marked={row.key === marked}
            tabStop={row.key === tabStop}
            onSelect={onSelect}
            onHover={onHover}
          />
        ))}
      </ul>
    </section>
  );
}
