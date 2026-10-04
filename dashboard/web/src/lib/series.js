export const CATEGORIES = [
  { id: "rates",     name: "Rates & Curve",        short: "Rates",     keys: ["effr", "sofr", "sofr_effr_spread", "usblr", "us10y", "t10y2y", "t10y3m"] },
  { id: "inflation", name: "Inflation",            short: "Inflation", keys: ["cpi", "core_cpi", "pce", "core_pce", "ppi", "t5yie", "t5yifr"] },
  { id: "labor",     name: "Labor",                short: "Labor",     keys: ["unrate", "payems", "icsa", "ccsa", "ahe"] },
  { id: "growth",    name: "Growth & Activity",    short: "Growth",    keys: ["real_gdp", "real_pce", "rsafs", "indpro", "cfnai", "permit"] },
  { id: "liquidity", name: "Liquidity & Fed",      short: "Liquidity", keys: ["fed_net_liquidity", "walcl", "wresbal", "rrp", "tga", "tga_weekly", "m2sl"] },
  { id: "credit",    name: "Credit & Conditions",  short: "Credit",    keys: ["hy_spread", "ig_spread", "ccc_spread", "drtscilm", "totbkcr", "nfci", "stlfsi4"] },
  { id: "markets",   name: "Markets & Volatility", short: "Markets",   keys: ["vix", "move", "skew", "dtwexbgs"] },
];
export const OTHER = { id: "other", name: "Other", short: "Other", keys: [] }; // color --c-other

export const CADENCE = { // anything not listed is "monthly"
  daily: ["effr", "sofr", "sofr_effr_spread", "usblr", "us10y", "t10y2y", "t10y3m", "t5yie", "t5yifr",
          "hy_spread", "ig_spread", "ccc_spread", "vix", "move", "skew", "fed_net_liquidity", "rrp", "tga"],
  weekly: ["icsa", "ccsa", "nfci", "stlfsi4", "walcl", "wresbal", "tga_weekly", "totbkcr", "dtwexbgs"],
  quarterly: ["real_gdp", "drtscilm"],
};
export const STALE_DAYS = { daily: 6, weekly: 21, monthly: 95, quarterly: 225 }; // includes normal publication lag
export const STRICT_DAYS = 30; // "> 30 days" preview rule

export const CADENCE_ORDER = ["daily", "weekly", "monthly", "quarterly"];
export const RULES = ["cadence", "strict"];
export const SORTS = ["group", "freshest", "oldest", "a-z"];

export function cadenceOf(key) {
  for (const cadence of ["daily", "weekly", "quarterly"]) {
    if (CADENCE[cadence].includes(key)) {
      return cadence;
    }
  }
  return "monthly";
}

export function limitDays(cadence, rule) {
  return rule === "strict" ? STRICT_DAYS : STALE_DAYS[cadence];
}
