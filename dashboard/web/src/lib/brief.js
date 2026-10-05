// Desk labels for the series a regime check points at. The page humanizes
// keys here so the brief table matches the grid, including CPI names.
export const SERIES_LABELS = {
  payems: "Payrolls",
  unrate: "Unemployment",
  icsa: "Initial Claims",
  cfnai: "CFNAI",
  real_pce: "Real PCE",
  hy_spread: "HY Spread",
  move: "MOVE",
  vix: "VIX",
  nfci: "NFCI",
  stlfsi4: "STL FSI",
  fed_net_liquidity: "Net Liq",
  ahe: "Wage Growth",
  core_pce: "Core PCE",
  core_cpi: "Core CPI",
  cpi: "CPI",
};

export function checkLabel(check) {
  if (check.id === "spec") return "Speculation gate";
  return SERIES_LABELS[check.series] || check.series;
}

// Color follows the meaning, not the words PASS and FAIL.
export function checkMeaning(check) {
  const result = check.result;
  if (!result) return { word: "—", tone: "muted" };
  if (check.group === "growth") {
    if (result === "PASS") return { word: "supports", tone: "ok" };
    if (result === "FAIL") return { word: "misses", tone: "muted" };
  }
  if (check.group === "inflation") {
    if (result === "DOWN") return { word: "cooling", tone: "ok" };
    if (result === "UP") return { word: "heating", tone: "bad" };
    if (result === "FLAT") return { word: "flat", tone: "muted" };
  }
  if (check.group === "stress") {
    if (result === "PASS") return { word: "firing", tone: "bad" };
    if (result === "FAIL") return { word: "quiet", tone: "ok" };
  }
  if (check.group === "trend" || check.group === "gate") {
    return { word: String(result).toLowerCase(), tone: "neutral" };
  }
  return { word: "—", tone: "muted" };
}

export function collapsedLine(brief) {
  const economy = brief?.economy;
  const liquidity = brief?.liquidity;
  if (!economy || !liquidity) return null;
  const econName = [economy.name, economy.qualifier].filter(Boolean).join(" ");
  const econ = `Economy ${econName || "—"} · ${economy.status || "—"}`;
  let liqName = liquidity.name || "—";
  if (liquidity.toward) liqName += ` tipping → ${liquidity.toward}`;
  const liq = `Liquidity ${liqName} · ${liquidity.status || "—"}`;
  return `${econ} | ${liq} | v${brief.version} · as of ${brief.as_of || "—"}`;
}

export function signedInt(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  if (number < 0) return `−${Math.abs(number)}`;
  if (number > 0) return `+${number}`;
  return "0";
}
