export const DAY = 86_400_000;
export const DASH = "—";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const COUNT = new Intl.NumberFormat("en-US");
const LOCAL_HM = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const LOCAL_HMS = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
const LOCAL_LONG = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
});
const VALUE_FORMATS = new Map();

export function trimUnit(unit) {
  return unit == null ? "" : String(unit).trim();
}

function fractionDigits(unit, magnitude) {
  if (unit === "%") return { minimumFractionDigits: 1, maximumFractionDigits: 2 };
  if (unit === "bps") return { maximumFractionDigits: 0 };
  if (magnitude >= 1000) return { maximumFractionDigits: 1 };
  if (magnitude >= 1) return { maximumFractionDigits: 2 };
  return { maximumFractionDigits: 3 };
}

export function fmtValue(value, unit) {
  if (value == null) return DASH;
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  const digits = fractionDigits(trimUnit(unit), Math.abs(number));
  const id = `${digits.minimumFractionDigits ?? 0}-${digits.maximumFractionDigits}`;
  if (!VALUE_FORMATS.has(id)) {
    VALUE_FORMATS.set(id, new Intl.NumberFormat("en-US", digits));
  }
  return VALUE_FORMATS.get(id).format(number).replace(/^-/, "\u2212");
}

export function rawText(value) {
  return value == null ? DASH : String(value);
}

export function fmtCount(value) {
  return value == null ? DASH : COUNT.format(value);
}

export function fmtBytes(bytes) {
  if (bytes == null) return DASH;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Number(bytes);
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return unit === 0 ? `${size} B` : `${size.toFixed(1)} ${units[unit]}`;
}

function dateParts(date) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? "");
  if (!match) return null;
  const [, year, month, day] = match.map(Number);
  if (month < 1 || month > 12) return null;
  return { year, month, day };
}

export function utcDay(date) {
  const parts = dateParts(date);
  return parts ? Date.UTC(parts.year, parts.month - 1, parts.day) : null;
}

export function ageDays(date, now) {
  const start = utcDay(date);
  if (start == null) return null;
  return Math.max(0, Math.floor((now - start) / DAY));
}

export function period(date, cadence) {
  const parts = dateParts(date);
  if (!parts) return date ? String(date) : DASH;
  if (cadence === "quarterly") return `Q${Math.floor((parts.month - 1) / 3) + 1} ${parts.year}`;
  if (cadence === "monthly") return `${MONTHS[parts.month - 1]} ${parts.year}`;
  return `${MONTHS[parts.month - 1]} ${parts.day}`;
}

export function parseUtc(value) {
  if (!value) return null;
  const text = String(value).trim();
  if (!text) return null;
  const iso = text.includes("T") ? text : text.replace(" ", "T");
  const zoned = /(?:Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`;
  const parsed = Date.parse(zoned);
  return Number.isNaN(parsed) ? null : parsed;
}

export function utcTime(ms) {
  return ms == null ? DASH : `${new Date(ms).toISOString().slice(11, 19)}Z`;
}

export function utcStamp(ms) {
  if (ms == null) return DASH;
  const iso = new Date(ms).toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
}

export function localTime(ms) {
  return ms == null ? DASH : LOCAL_HM.format(ms);
}

export function localStamp(ms) {
  return ms == null ? DASH : LOCAL_LONG.format(ms);
}

export function clockTime(ms) {
  return LOCAL_HMS.format(ms);
}

export function ago(then, now) {
  if (then == null) return DASH;
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 90) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 90) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

// First matching rule wins (spec 5.1). Rules 1-3 also carry the banner text.
export function jobTone(job, stats, snapshot, error) {
  if (error) {
    return { tone: "bad", label: "API ERROR", banner: `api: ${error}` };
  }
  const parts = [job, stats, snapshot].filter(Boolean);
  const missing = parts.find((part) => part.db_exists === false);
  if (missing) {
    return {
      tone: "bad",
      label: "NO DB",
      banner: `database file is not there yet: ${missing.db_path}. the cron job creates it on the first run.`,
    };
  }
  const failed = parts.find((part) => part.error);
  if (failed) {
    return {
      tone: "bad",
      label: "DB ERROR",
      banner: `could not read the database (${failed.db_path}): ${failed.error}`,
    };
  }
  if (!job) return { tone: "wait", label: "LOADING", banner: null };
  if (job.ingestion_running === true) return { tone: "run", label: "RUNNING", banner: null };
  if (job.last_run_at == null) return { tone: "warn", label: "NO RUN YET", banner: null };
  if (job.last_run_status === "failed") return { tone: "bad", label: "FAILED", banner: null };
  if (job.stale === true) return { tone: "warn", label: "STALE", banner: null };
  if (job.last_run_status === "partial") return { tone: "warn", label: "PARTIAL", banner: null };
  if (job.last_run_status === "ok") return { tone: "ok", label: "OK", banner: null };
  return { tone: "warn", label: String(job.last_run_status ?? "unknown").toUpperCase(), banner: null };
}

export function statusTone(status) {
  if (status === "ok") return "ok";
  if (status === "failed") return "bad";
  return "warn";
}
