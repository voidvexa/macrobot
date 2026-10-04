import { ageDays, trimUnit } from "./format.js";
import { CADENCE_ORDER, CATEGORIES, OTHER, cadenceOf, limitDays } from "./series.js";

const PLACES = new Map();
CATEGORIES.forEach((cat, catIndex) => {
  cat.keys.forEach((key, keyIndex) => PLACES.set(key, { cat, catIndex, keyIndex }));
});

export function buildRows(snapshotRows, now, rule) {
  return snapshotRows.map((row) => {
    const key = String(row.key);
    const place = PLACES.get(key) ?? { cat: OTHER, catIndex: CATEGORIES.length, keyIndex: 0 };
    const cadence = cadenceOf(key);
    const age = ageDays(row.date, now);
    const limit = limitDays(cadence, rule);
    const noData = row.value == null || row.date == null;
    return {
      key,
      label: String(row.label ?? key),
      value: row.value,
      unit: trimUnit(row.unit),
      date: row.date,
      ...place,
      cadence,
      age: noData ? null : age,
      limit,
      noData,
      stale: noData || age == null || age > limit,
    };
  });
}

const byLabel = (a, b) => a.label.localeCompare(b.label) || a.key.localeCompare(b.key);
const byGroup = (a, b) => a.catIndex - b.catIndex || a.keyIndex - b.keyIndex || byLabel(a, b);
const byAge = (direction) => (a, b) => {
  if (a.age == null || b.age == null) {
    return (a.age == null) - (b.age == null) || byLabel(a, b);
  }
  return direction * (a.age - b.age) || byLabel(a, b);
};
const SORTERS = { group: byGroup, freshest: byAge(1), oldest: byAge(-1), "a-z": byLabel };

export function sortRows(rows, sort) {
  return [...rows].sort(SORTERS[sort] ?? byGroup);
}

export function toNeedle(query) {
  return query.trim().toLowerCase();
}

export function matches(row, needle) {
  if (!needle) return true;
  return (
    row.label.toLowerCase().includes(needle) ||
    row.key.toLowerCase().includes(needle) ||
    (needle === "stale" && row.stale)
  );
}

// Plain string pieces, so the caller can wrap hits in <mark> as React text.
export function splitMatch(text, needle) {
  const lower = text.toLowerCase();
  if (!needle || lower.length !== text.length) return [{ text, hit: false }];
  const parts = [];
  let from = 0;
  for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, from)) {
    if (at > from) parts.push({ text: text.slice(from, at), hit: false });
    parts.push({ text: text.slice(at, at + needle.length), hit: true });
    from = at + needle.length;
  }
  if (from < text.length) parts.push({ text: text.slice(from), hit: false });
  return parts;
}

export function cadenceLetters(rows) {
  const letters = [];
  for (const row of sortRows(rows, "group")) {
    const letter = row.cadence[0].toUpperCase();
    if (!letters.includes(letter)) letters.push(letter);
  }
  return letters.join("/");
}

export function countStale(rows) {
  return rows.reduce((total, row) => total + (row.stale ? 1 : 0), 0);
}

export function cadenceSummary(rows, rule) {
  return CADENCE_ORDER.map((cadence) => {
    const members = rows.filter((row) => row.cadence === cadence);
    const ages = members.map((row) => row.age).filter((age) => age != null);
    return {
      cadence,
      count: members.length,
      oldest: ages.length ? Math.max(...ages) : null,
      limit: limitDays(cadence, rule),
      stale: countStale(members),
    };
  }).filter((group) => group.count > 0);
}

export function groupsOf(rows) {
  return [...CATEGORIES, OTHER]
    .map((cat) => ({ cat, rows: rows.filter((row) => row.cat === cat) }))
    .filter((group) => group.rows.length > 0);
}
