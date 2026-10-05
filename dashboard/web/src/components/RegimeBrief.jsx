import { useState } from "react";
import { DASH } from "../lib/format.js";
import { checkLabel, checkMeaning, collapsedLine, signedInt } from "../lib/brief.js";

export function RegimeBrief({ brief, open, onToggle, onMark }) {
  const line = collapsedLine(brief);
  const ready = Boolean(brief?.economy && brief?.liquidity);
  return (
    <section className={open ? "panel brief" : "panel brief is-closed"} aria-labelledby="brief-head">
      <h2>
        <button
          type="button"
          className="panel-head"
          id="brief-head"
          aria-expanded={open}
          aria-controls="brief-body"
          onClick={onToggle}
        >
          <span className="glyph" aria-hidden="true">
            {open ? "−" : "+"}
          </span>{" "}
          {open ? (
            <>
              <span className="panel-name">macro regime brief</span>
              <span className="rule" aria-hidden="true" />{" "}
              <span className="meta">
                v{brief?.version || "1.0.0"}
                {brief?.as_of ? ` · as of ${brief.as_of}` : ""} <kbd>b</kbd>
              </span>
            </>
          ) : (
            <span className="brief-line">{line || "macro regime brief"}</span>
          )}
        </button>
      </h2>
      {open ? (
        <div id="brief-body">
          {!brief ? (
            <p className="brief-wait">waiting for /api/regime-brief</p>
          ) : brief.error ? (
            <p className="brief-wait">{brief.error}</p>
          ) : !ready ? (
            <p className="brief-wait">{brief.note || "no observations to score yet"}</p>
          ) : (
            <>
              <div className="brief-cards">
                <EconomyCard card={brief.economy} onMark={onMark} />
                <LiquidityCard card={brief.liquidity} onMark={onMark} />
              </div>
              <Context brief={brief} />
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}

function EconomyCard({ card, onMark }) {
  return (
    <article className="brief-card">
      <div className="brief-top">
        <div className="brief-id">
          <p className="brief-kicker">economy map</p>
          <p className="brief-name">
            {card.name || DASH} {card.qualifier ? <small>{card.qualifier}</small> : null}{" "}
            <StatusChip status={card.status} label={card.status_label} />
          </p>
        </div>
        <Quadrant name={card.name} raw={card.raw} />
      </div>
      <p className="brief-why">{card.why}</p>
      <div className="meters">
        <Meter
          label="Growth"
          dir={card.growth.direction}
          score={`${card.growth.score}/${card.growth.of}`}
          note={`threshold ${card.growth.threshold}`}
        >
          <Pips count={card.growth.of} filled={card.growth.score} tone="ok" ticks={[card.growth.threshold]} />
        </Meter>
        <Meter label="Inflation" dir={card.inflation.direction} score={`net ${signedInt(card.inflation.net)}`} note="net">
          <InflationPips checks={card.checks.filter((check) => check.group === "inflation")} />
        </Meter>
      </div>
      <Phases raw={card.raw} confirmed={card.name} />
      <Chain
        weeks={card.weeks}
        columns={[
          ["week", "week"],
          ["raw", "raw"],
          ["confirmed", "confirmed"],
          ["growth", "growth"],
          ["inflation", "inflation"],
        ]}
      />
      <Checks checks={card.checks} onMark={onMark} />
    </article>
  );
}

function LiquidityCard({ card, onMark }) {
  const tip = card.toward ? (
    <>
      {card.arrow === "down" ? "▼" : "▲"} tipping toward {card.toward}
    </>
  ) : null;
  return (
    <article className="brief-card">
      <div className="brief-top">
        <div className="brief-id">
          <p className="brief-kicker">liquidity cycle</p>
          <p className="brief-name">
            {card.name || DASH} {tip ? <small>{tip}</small> : null}{" "}
            <StatusChip status={card.status} label={card.status_label} />
          </p>
        </div>
      </div>
      <p className="brief-why">{card.why}</p>
      <div className="meters">
        <Meter
          label="Stress"
          dir={null}
          score={`${card.stress.score}/${card.stress.of}`}
          note={`tipping tick ${card.stress.tipping}, turbulence at ${card.stress.turbulence}`}
        >
          <Pips
            count={card.stress.of}
            filled={card.stress.score}
            tone="bad"
            ticks={[card.stress.tipping, card.stress.turbulence]}
          />
        </Meter>
        <Meter label="Trend" dir={card.trend.direction} score={card.trend.text || DASH} note="net liq 28d">
          <span className="trend-pip" aria-hidden="true" />
        </Meter>
      </div>
      <Phases raw={card.raw} confirmed={card.name} />
      <Chain
        weeks={card.weeks}
        columns={[
          ["week", "week"],
          ["raw", "raw"],
          ["confirmed", "confirmed"],
          ["stress", "stress"],
          ["trend", "trend"],
        ]}
      />
      <Checks checks={card.checks} onMark={onMark} />
    </article>
  );
}

function StatusChip({ status, label }) {
  const tone = status === "unchanged" ? "ok" : status === "pending" ? "warn" : status === "changed" ? "ai" : "muted";
  if (!label) return null;
  return <span className={`chip chip-${tone}`}>{label}</span>;
}

function Quadrant({ name, raw }) {
  return (
    <div className="quad" role="group" aria-label={`Growth and inflation quadrant, ${name || "unplaced"}`}>
      <span />
      <span className="quad-axis">infl ↓</span>
      <span className="quad-axis">infl ↑</span>
      <span className="quad-axis">g ↑</span>
      <Cell label="Goldilocks" name={name} raw={raw} />
      <Cell label="Reflation" name={name} raw={raw} />
      <span className="quad-axis">g ↓</span>
      <Cell label="Deflation" name={name} raw={raw} />
      <Cell label="Stagflation" name={name} raw={raw} />
    </div>
  );
}

function Cell({ label, name, raw }) {
  const current = label === name;
  const pending = label === raw && raw !== name;
  const className = ["quad-cell", current && "is-now", pending && "is-raw"].filter(Boolean).join(" ");
  return (
    <span className={className} aria-current={current ? "true" : undefined}>
      {label}
    </span>
  );
}

function Meter({ label, dir, score, note, children }) {
  return (
    <div className="meter" aria-label={`${label} ${dir || ""} ${score}. ${note}.`}>
      <span className="meter-k">{label}</span>
      {dir ? <span className="meter-dir">{dir}</span> : null}
      {children}
      <span className="meter-score">{score}</span>
    </div>
  );
}

function Pips({ count, filled, tone, ticks }) {
  return (
    <span className="pips" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <span key={index} className={index < filled ? `pip is-on tone-${tone}` : "pip"}>
          {ticks.includes(index + 1) ? <i className="pip-tick" /> : null}
        </span>
      ))}
    </span>
  );
}

function InflationPips({ checks }) {
  return (
    <span className="pips" aria-hidden="true">
      {checks.map((check) => {
        const tone = checkMeaning(check).tone;
        const on = check.result != null;
        return <span key={check.id} className={on ? `pip is-on tone-${tone}` : "pip"} />;
      })}
    </span>
  );
}

function Phases({ raw, confirmed }) {
  const split = raw && confirmed && raw !== confirmed;
  return (
    <p className="phases">
      <span className={split ? "phase is-raw" : "phase"}>raw {raw || DASH}</span>
      <span className="phase">confirmed {confirmed || DASH}</span>
    </p>
  );
}

function Chain({ weeks, columns }) {
  return (
    <div className="chain-wrap">
      <table className="chain">
        <thead>
          <tr>
            {columns.map(([key, label]) => (
              <th key={key} scope="col">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(weeks || []).map((week) => (
            <tr key={week.date} className={week.diverged ? "is-split" : undefined}>
              {columns.map(([key]) => (
                <td key={key}>{week[key] || DASH}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Checks({ checks, onMark }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="checks-block">
      <button
        type="button"
        className="checks-toggle"
        aria-expanded={open}
        onClick={() => {
          setOpen((current) => !current);
          onMark(null);
        }}
      >
        checks {open ? "▾" : "▸"}
      </button>
      {open ? (
        <div className="chain-wrap">
          <table
            className="checks"
            onMouseLeave={() => onMark(null)}
          >
            <thead>
              <tr>
                <th scope="col">id</th>
                <th scope="col">label</th>
                <th scope="col">result</th>
                <th scope="col">value</th>
                <th scope="col">detail</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((check) => {
                const meaning = checkMeaning(check);
                return (
                  <tr
                    key={check.id}
                    className="chk"
                    tabIndex={0}
                    data-series={check.series}
                    onMouseEnter={() => onMark(check.series)}
                    onFocus={() => onMark(check.series)}
                    onBlur={() => onMark(null)}
                  >
                    <td className="chk-id">{check.id}</td>
                    <td>{checkLabel(check)}</td>
                    <td className={`tone-${meaning.tone}`}>{meaning.word}</td>
                    <td className="chk-value">{check.value || DASH}</td>
                    <td className="detail">{check.detail}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function Context({ brief }) {
  const { rrp, tga, flags, speculation_gate: gate } = brief.context;
  const gateWord = gate.state === "on" ? "ON" : gate.state === "off" ? "OFF" : DASH;
  return (
    <div className="brief-context">
      <span>
        RRP {rrp.level_text || DASH} <span className="dim">Δ28d {rrp.change_text || DASH}</span>
      </span>
      <span>
        TGA {tga.level_text || DASH} <span className="dim">Δ28d {tga.change_text || DASH}</span>
      </span>
      {flags.map((flag) => (
        <span key={flag.id} className={`brief-flag is-${flag.id}`} title={flag.series.join(", ")}>
          {flag.id}
        </span>
      ))}
      <span>
        speculation gate {gateWord} · {gate.rule}
      </span>
      <span>
        v{brief.version} · as of {brief.as_of}
      </span>
      <span className="dim">{brief.release_rule}</span>
    </div>
  );
}
