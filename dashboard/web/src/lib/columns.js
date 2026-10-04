// Open category panels measured at the desktop row size (12.5px / 1.5, 2px padding):
// 4 rows 127px, 5 rows 150px, 6 rows 173px, 7 rows 195px. A closed panel is the header.
const GAP = 12;
const OPEN_CHROME = 37.5;
const ROW = 22.5;
const CLOSED = 32;

export function estimatePanelHeight(rowCount, open) {
  if (!open) return CLOSED;
  return OPEN_CHROME + rowCount * ROW;
}

function stackHeight(heights) {
  if (heights.length === 0) return 0;
  return heights.reduce((sum, height) => sum + height, 0) + GAP * (heights.length - 1);
}

// Whole panels only. Brute force is fine: there are at most eight categories.
function assignColumns(heights, columns) {
  const count = heights.length;
  if (count === 0) return [];
  if (count > 9) return greedy(heights, columns);

  let best = null;
  const assign = new Array(count);
  const walk = (index) => {
    if (index === count) {
      const buckets = Array.from({ length: columns }, () => []);
      for (let i = 0; i < count; i += 1) buckets[assign[i]].push(heights[i]);
      if (count >= columns && buckets.some((bucket) => bucket.length === 0)) return;
      const totals = buckets.map(stackHeight);
      const range = Math.max(...totals) - Math.min(...totals);
      // Prefer earlier categories in the left columns when two packs tie.
      const leftBias = assign.reduce((sum, column, i) => sum + column * (count - i), 0);
      if (best == null || range < best.range || (range === best.range && leftBias < best.leftBias)) {
        best = { range, leftBias, assign: assign.slice() };
      }
      return;
    }
    for (let column = 0; column < columns; column += 1) {
      assign[index] = column;
      walk(index + 1);
    }
  };
  walk(0);
  return best.assign;
}

function greedy(heights, columns) {
  const totals = Array(columns).fill(0);
  const counts = Array(columns).fill(0);
  return heights.map((height) => {
    let column = 0;
    for (let i = 1; i < columns; i += 1) {
      if (totals[i] < totals[column]) column = i;
    }
    totals[column] += height + (counts[column] > 0 ? GAP : 0);
    counts[column] += 1;
    return column;
  });
}

// Place panels so the three wide columns end as close as whole panels allow.
// Slots keep source order; the grid positions them.
export function arrangeColumns(panels, measured, columns = 3) {
  const heights = panels.map(
    (panel) => measured?.[panel.cat.id] ?? estimatePanelHeight(panel.rows.length, panel.open),
  );
  const assigned = assignColumns(heights, columns);
  const cursor = Array(columns).fill(0);
  const place = new Map();
  panels.forEach((panel, index) => {
    const column = assigned[index] ?? 0;
    place.set(panel.cat.id, { column, top: cursor[column] });
    cursor[column] += heights[index] + GAP;
  });
  return { place, pad: cursor.length ? Math.max(...cursor) : 0 };
}
