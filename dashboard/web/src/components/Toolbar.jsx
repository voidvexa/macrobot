export const RULE_LABEL = { cadence: "cadence", strict: ">30d" };
export const RULE_TEXT = { cadence: "past cadence + lag", strict: "older than 30d" };

export function Toolbar({ inputRef, query, onQuery, tabs, total, cat, onCat, rule, onRule, sort, onSort }) {
  return (
    <div className="toolbar">
      <label className="filter">
        <span className="prompt" aria-hidden="true">
          &gt;
        </span>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="filter label / key …   ( / )"
          aria-label="Filter series"
          aria-keyshortcuts="/"
          autoComplete="off"
          spellCheck={false}
        />
      </label>
      <div className="tabs" role="toolbar" aria-label="Categories">
        <Tab digit={0} name="All" count={total} pressed={cat === "all"} onClick={() => onCat("all")} />
        {tabs.map((tab) => (
          <Tab
            key={tab.cat.id}
            id={tab.cat.id}
            digit={tab.digit}
            name={tab.cat.short}
            count={tab.count}
            pressed={cat === tab.cat.id}
            onClick={() => onCat(tab.cat.id)}
          />
        ))}
      </div>
      <div className="opts">
        <button
          type="button"
          className="opt"
          onClick={onRule}
          aria-label={`Stale rule: ${RULE_LABEL[rule]} (${RULE_TEXT[rule]})`}
          aria-keyshortcuts="s"
        >
          STALE: <b>{RULE_LABEL[rule]}</b> <kbd>s</kbd>
        </button>
        <button type="button" className="opt" onClick={onSort} aria-label={`Sort: ${sort}`} aria-keyshortcuts="o">
          SORT: <b>{sort}</b> <kbd>o</kbd>
        </button>
      </div>
    </div>
  );
}

function Tab({ id, digit, name, count, pressed, onClick }) {
  const digits = digit <= 9 ? String(digit) : undefined;
  return (
    <button
      type="button"
      className={id ? "tab" : "tab tab-all"}
      style={id ? { "--c": `var(--c-${id})` } : undefined}
      aria-pressed={pressed}
      aria-keyshortcuts={digits}
      onClick={onClick}
    >
      {digits ? <kbd aria-hidden="true">{digits}</kbd> : null}
      <span className="tab-name">{name}</span>
      <span className="n">{count}</span>
    </button>
  );
}
