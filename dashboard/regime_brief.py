"""Read-only macro regime brief, computed from stored observations.

`GET /api/regime-brief` scores the rows already in `observations`. It does
not fetch, and it does not invent a print that is not in the file.

As-of is the latest observation date that is already released: `date` on or
before the read's UTC day, and `recorded_at` on or before the read. Every
week in the chain uses the same rule with that week's Friday (or the as-of
day for the current week) as its cutoff. The line the page prints is
"only data dated ≤ as-of and released by as-of".

Two facts the file cannot supply are listed on `unmapped`:

- Inflation's 3-month annualized rate. `cpi`, `core_cpi`, `core_pce`, and
  `ahe` are stored as FRED year-over-year percent (`units=pc1`), not the
  index. A check uses the change in that year-over-year rate over three
  calendar months. Down at least 0.1pp is cooling, up at least 0.1pp is
  heating, and anything in between is flat.
- Superseded vintages. One row per series and date is overwritten on
  revision, and `recorded_at` is the latest write. The cutoff can drop a
  row written after the as-of instant. It cannot restore the print that
  was current before that revision.

History is whatever the cron has already stored. The updater asks FRED for
the latest print, so a new database has no 3-month change, no z-score, and
no 5-week chain until older dates have been collected.

Map, from the growth and inflation directions:

- Goldilocks: growth up, inflation down or flat
- Reflation: growth up, inflation up
- Stagflation: growth down, inflation up
- Deflation: growth down, inflation down or flat

Growth is up at 5 checks when at least 3 pass, and down when at least 3
fail. The qualifier is firm only when all 5 pass and the inflation net is
at least 3 in absolute value. Otherwise it is soft.

Liquidity raw phase is Turbulence at a stress score of 3 or more, and Calm
below that. Score 2 is the tipping line: the raw phase is still Calm, and
the headline points toward Turbulence. A new raw phase confirms after it
holds for 3 consecutive scored weeks. Until then the confirmed phase stays
put and the status is pending.
"""

from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from dashboard.read import connect, parse_run_timestamp

VERSION = "1.0.0"
RELEASE_RULE = "only data dated ≤ as-of and released by as-of"

UNMAPPED = (
    "Inflation 3-month annualized rate. cpi, core_cpi, core_pce, and ahe are stored as FRED year-over-year percent, not the price index. The check uses the 3-month change in that year-over-year rate.",
    "Superseded vintages. observations keeps one value per series and date, and recorded_at is the latest write, so a revision replaces the print that was current on an earlier as-of.",
)

# The updater writes one latest print per run. Older rows exist only after
# the cron has been collecting them.
HISTORY_NOTE = (
    "Change, z-score, and week-chain fields need older observations. "
    "A database that has only the latest print for each series cannot score them yet."
)

GROWTH_UP_AT = 3
STRESS_TIP = 2
STRESS_TURBULENCE = 3
CONFIRM_WEEKS = 3
CHAIN_WEEKS = 5
LOOKBACK_WEEKS = 16
Z_FIRE = 1.0
GATE_Z = -1.5
INFLATION_STEP = 0.1
LIQ_BAND = 50.0  # billions, used when a 28-day z-score is not available
TENTATIVE_DAYS = 7
Z_SAMPLES = 8

QUADRANTS = {
    ("UP", "DOWN"): "Goldilocks",
    ("UP", "FLAT"): "Goldilocks",
    ("UP", "UP"): "Reflation",
    ("DOWN", "UP"): "Stagflation",
    ("DOWN", "DOWN"): "Deflation",
    ("DOWN", "FLAT"): "Deflation",
}

# Same cadence limits as dashboard/web/src/lib/series.js (STALE_DAYS).
STALE_DAYS = {
    "payems": 95,
    "unrate": 95,
    "icsa": 21,
    "cfnai": 95,
    "real_pce": 95,
    "core_pce": 95,
    "core_cpi": 95,
    "cpi": 95,
    "ahe": 95,
    "hy_spread": 6,
    "move": 6,
    "vix": 6,
    "nfci": 21,
    "stlfsi4": 21,
    "fed_net_liquidity": 6,
    "rrp": 6,
    "tga": 6,
}

REVISABLE = {"payems", "unrate", "cpi", "core_cpi", "core_pce", "ahe", "real_pce", "cfnai"}

BRIEF_SQL = """
SELECT series_key, date, value, recorded_at
FROM observations
WHERE series_key IN (
    'payems', 'unrate', 'icsa', 'cfnai', 'real_pce',
    'core_pce', 'core_cpi', 'cpi', 'ahe',
    'hy_spread', 'move', 'vix', 'nfci', 'stlfsi4',
    'fed_net_liquidity', 'rrp', 'tga'
)
ORDER BY series_key, date, recorded_at
"""


@dataclass(frozen=True)
class Point:
    day: date
    value: float
    released: datetime


@dataclass(frozen=True)
class RegimeBrief:
    db_path: str
    db_exists: bool
    error: str | None
    version: str | None
    as_of: str | None
    release_rule: str | None
    unmapped: tuple[str, ...]
    note: str | None
    economy: dict | None
    liquidity: dict | None
    context: dict | None


def brief_payload(brief: RegimeBrief) -> dict:
    return {
        "db_path": brief.db_path,
        "db_exists": brief.db_exists,
        "error": brief.error,
        "version": brief.version,
        "as_of": brief.as_of,
        "release_rule": brief.release_rule,
        "unmapped": list(brief.unmapped),
        "note": brief.note,
        "economy": brief.economy,
        "liquidity": brief.liquidity,
        "context": brief.context,
    }


def load_regime_brief(db_path: Path, now: datetime | None = None) -> RegimeBrief:
    """Score one as-of. `now` is the read instant, UTC."""
    moment = _utc(now or datetime.now(timezone.utc))
    path_text = str(db_path)
    rows, exists, error = _read(db_path)
    if rows is None:
        return _blank(path_text, exists, error)
    return _compose(path_text, _group(rows), moment)


def _blank(path_text: str, exists: bool, error: str | None) -> RegimeBrief:
    return RegimeBrief(
        db_path=path_text,
        db_exists=exists,
        error=error,
        version=None,
        as_of=None,
        release_rule=None,
        unmapped=(),
        note=None,
        economy=None,
        liquidity=None,
        context=None,
    )


def _compose(path_text: str, grouped: dict[str, list[Point]], moment: datetime) -> RegimeBrief:
    today = moment.date()
    released = [
        point
        for points in grouped.values()
        for point in points
        if point.day <= today and point.released <= moment
    ]
    if not released:
        return RegimeBrief(
            db_path=path_text,
            db_exists=True,
            error=None,
            version=VERSION,
            as_of=None,
            release_rule=RELEASE_RULE,
            unmapped=UNMAPPED,
            note=HISTORY_NOTE,
            economy=None,
            liquidity=None,
            context=None,
        )
    as_of = max(point.day for point in released)
    weeks = _week_ends(as_of, LOOKBACK_WEEKS)
    economy_weeks = [_economy_at(grouped, day, _cutoff(day, moment)) for day in weeks]
    liquidity_weeks = [_liquidity_at(grouped, day, _cutoff(day, moment)) for day in weeks]
    _apply_hysteresis(economy_weeks)
    _apply_hysteresis(liquidity_weeks)
    current_e = economy_weeks[-1]
    current_l = liquidity_weeks[-1]
    context = _context(grouped, as_of, _cutoff(as_of, moment), moment)
    return RegimeBrief(
        db_path=path_text,
        db_exists=True,
        error=None,
        version=VERSION,
        as_of=as_of.isoformat(),
        release_rule=RELEASE_RULE,
        unmapped=UNMAPPED,
        note=HISTORY_NOTE,
        economy=_economy_payload(current_e, economy_weeks[-CHAIN_WEEKS:]),
        liquidity=_liquidity_payload(current_l, liquidity_weeks[-CHAIN_WEEKS:]),
        context=context,
    )


def _economy_at(grouped: dict[str, list[Point]], day: date, cutoff: datetime) -> dict:
    visible = {key: _visible(points, cutoff) for key, points in grouped.items()}
    checks = [
        _payrolls(visible, day),
        _unemployment(visible, day),
        _claims(visible, day),
        _cfnai(visible, day),
        _real_pce(visible, day),
        _inflation(visible, day, "i1", "core_pce", "Core PCE"),
        _inflation(visible, day, "i2", "core_cpi", "Core CPI"),
        _inflation(visible, day, "i3", "cpi", "CPI"),
        _inflation(visible, day, "i4", "ahe", "wage growth"),
    ]
    growth = [check for check in checks if check["group"] == "growth"]
    inflation = [check for check in checks if check["group"] == "inflation"]
    passes = sum(check["result"] == "PASS" for check in growth)
    fails = sum(check["result"] == "FAIL" for check in growth)
    if passes >= GROWTH_UP_AT:
        growth_dir = "UP"
    elif fails >= GROWTH_UP_AT:
        growth_dir = "DOWN"
    else:
        growth_dir = None
    scored_i = [check for check in inflation if check["result"] in {"UP", "DOWN", "FLAT"}]
    if not scored_i:
        net = None
        infl_dir = None
    else:
        net = sum(_infl_sign(check["result"]) for check in scored_i)
        infl_dir = "DOWN" if net < 0 else "UP" if net > 0 else "FLAT"
    name = QUADRANTS.get((growth_dir, infl_dir))
    firm = passes == 5 and net is not None and abs(net) >= 3
    return {
        "date": day,
        "raw_name": name,
        "qualifier": None if name is None else "firm" if firm else "soft",
        "growth_dir": growth_dir,
        "growth_score": passes,
        "inflation_dir": infl_dir,
        "inflation_net": net,
        "checks": checks,
        "confirmed": None,
        "status": None,
        "pending_week": 0,
    }


def _liquidity_at(grouped: dict[str, list[Point]], day: date, cutoff: datetime) -> dict:
    visible = {key: _visible(points, cutoff) for key, points in grouped.items()}
    stress = [
        _z_check(visible, day, "s1", "hy_spread", "stress", 28, "4w z", "Fires when the 4-week HY change has a z-score of 1 or more."),
        _z_check(visible, day, "s2", "move", "stress", 28, "4w z", "Fires when the 4-week MOVE change has a z-score of 1 or more."),
        _z_check(visible, day, "s3", "vix", "stress", 20, "20d z", "Fires when the 20-day VIX change has a z-score of 1 or more."),
        _level_check(
            visible,
            day,
            "s4",
            "nfci",
            "Fires when NFCI is above zero, tighter than average.",
            fire_above=0.0,
        ),
        _level_check(
            visible,
            day,
            "s5",
            "stlfsi4",
            "Fires when the St. Louis stress index is above zero.",
            fire_above=0.0,
        ),
    ]
    trend = _trend(visible, day)
    gate = _gate(visible, day)
    fires = sum(check["result"] == "PASS" for check in stress)
    scored = sum(check["result"] in {"PASS", "FAIL"} for check in stress)
    missing = len(stress) - scored
    if scored == 0:
        raw = None
    elif fires >= STRESS_TURBULENCE:
        raw = "Turbulence"
    elif fires + missing < STRESS_TURBULENCE:
        raw = "Calm"
    else:
        raw = None
    return {
        "date": day,
        "raw_name": raw,
        "stress_score": fires,
        "stress_of": len(stress),
        "trend": trend["result"],
        "trend_change": trend["number"],
        "checks": stress + [trend, gate],
        "confirmed": None,
        "status": None,
        "pending_week": 0,
    }


def _apply_hysteresis(weeks: list[dict]) -> None:
    confirmed = None
    previous = None
    streak_name = None
    streak = 0
    for week in weeks:
        raw = week["raw_name"]
        if raw is None:
            week["confirmed"] = confirmed
            week["status"] = "unchanged" if confirmed else None
            week["pending_week"] = 0
            continue
        if raw == streak_name:
            streak += 1
        else:
            streak_name = raw
            streak = 1
        if confirmed is None or streak >= CONFIRM_WEEKS:
            confirmed = raw
        week["confirmed"] = confirmed
        if raw != confirmed:
            week["status"] = "pending"
            week["pending_week"] = streak
        elif previous is not None and confirmed != previous:
            week["status"] = "changed"
            week["pending_week"] = 0
        else:
            week["status"] = "unchanged"
            week["pending_week"] = 0
        previous = confirmed


def _economy_payload(current: dict, chain: list[dict]) -> dict:
    name = current["confirmed"]
    status = current["status"]
    return {
        "name": name,
        "qualifier": current["qualifier"] if name else None,
        "status": status,
        "status_label": _status_label(status, current["pending_week"]),
        "pending_week": current["pending_week"],
        "raw": current["raw_name"],
        "why": _economy_why(current),
        "growth": {
            "direction": current["growth_dir"],
            "score": current["growth_score"],
            "of": 5,
            "threshold": GROWTH_UP_AT,
        },
        "inflation": {
            "direction": current["inflation_dir"],
            "net": current["inflation_net"],
            "of": 4,
        },
        "weeks": [_economy_week(week) for week in chain],
        "checks": current["checks"],
    }


def _liquidity_payload(current: dict, chain: list[dict]) -> dict:
    name = current["confirmed"]
    status = current["status"]
    tip = _tip(current)
    return {
        "name": name,
        "status": status,
        "status_label": _status_label(status, current["pending_week"]),
        "pending_week": current["pending_week"],
        "raw": current["raw_name"],
        "toward": tip["toward"] if tip else None,
        "arrow": tip["arrow"] if tip else None,
        "why": _liquidity_why(current),
        "stress": {
            "score": current["stress_score"],
            "of": current["stress_of"],
            "tipping": STRESS_TIP,
            "turbulence": STRESS_TURBULENCE,
        },
        "trend": {
            "direction": current["trend"],
            "change_28d": current["trend_change"],
            "text": _money(current["trend_change"], signed=True) if current["trend_change"] is not None else None,
        },
        "weeks": [_liquidity_week(week) for week in chain],
        "checks": current["checks"],
    }


def _tip(current: dict) -> dict | None:
    raw = current["raw_name"]
    confirmed = current["confirmed"]
    if current["status"] == "pending" and raw and confirmed and raw != confirmed:
        return {"toward": raw, "arrow": "up" if raw == "Turbulence" else "down"}
    score = current["stress_score"]
    if score == STRESS_TIP and confirmed == "Calm":
        return {"toward": "Turbulence", "arrow": "up"}
    if score == STRESS_TIP and confirmed == "Turbulence":
        return {"toward": "Calm", "arrow": "down"}
    return None


def _economy_why(current: dict) -> str:
    if current["status"] == "pending" and current["raw_name"]:
        return _pending_why(current["raw_name"], current["pending_week"])
    name = current["confirmed"]
    if current["status"] == "changed" and name:
        return f"The map confirmed {name} this week."
    growth = {"UP": "up", "DOWN": "down"}.get(current["growth_dir"])
    infl = {"DOWN": "cooling", "UP": "heating", "FLAT": "flat"}.get(current["inflation_dir"])
    if name and growth and infl and current["status"] == "unchanged":
        return f"Growth is {growth} and inflation is {infl}, so the map stays in {name}."
    return "Not enough history to place the economy map."


def _liquidity_why(current: dict) -> str:
    if current["status"] == "pending" and current["raw_name"]:
        return _pending_why(current["raw_name"], current["pending_week"])
    name = current["confirmed"]
    if current["status"] == "changed" and name:
        return f"The cycle confirmed {name} this week."
    if name and current["status"] == "unchanged":
        score = current["stress_score"]
        of = current["stress_of"]
        if score == STRESS_TIP:
            return f"Stress is {score}/{of}, on the tipping line. The phase stays {name}."
        return f"Stress is {score}/{of} and the phase stays {name}."
    return "Not enough history to place the liquidity cycle."


def _pending_why(raw: str, n: int) -> str:
    unit = "week" if n == 1 else "weeks"
    return f"Raw {raw} for {n} {unit}. Confirms on the 3rd."


def _status_label(status: str | None, pending_week: int) -> str | None:
    if status == "pending" and pending_week:
        return f"pending · {_ordinal(pending_week)} week"
    return status


def _economy_week(week: dict) -> dict:
    return {
        "week": week["date"].strftime("%m-%d"),
        "date": week["date"].isoformat(),
        "raw": week["raw_name"],
        "confirmed": week["confirmed"],
        "growth": week["growth_dir"],
        "inflation": week["inflation_dir"],
        "diverged": bool(week["raw_name"] and week["confirmed"] and week["raw_name"] != week["confirmed"]),
    }


def _liquidity_week(week: dict) -> dict:
    score = week["stress_score"]
    return {
        "week": week["date"].strftime("%m-%d"),
        "date": week["date"].isoformat(),
        "raw": week["raw_name"],
        "confirmed": week["confirmed"],
        "stress": f"{score}/{week['stress_of']}" if week["raw_name"] else None,
        "trend": week["trend"],
        "diverged": bool(week["raw_name"] and week["confirmed"] and week["raw_name"] != week["confirmed"]),
    }


def _context(grouped: dict[str, list[Point]], as_of: date, cutoff: datetime, moment: datetime) -> dict:
    visible = {key: _visible(points, cutoff) for key, points in grouped.items()}
    tentative: list[str] = []
    stale: list[str] = []
    for key, limit in STALE_DAYS.items():
        latest = _at(visible[key], as_of) if key in visible else None
        if latest is None:
            stale.append(key)
            continue
        if (as_of - latest[0]).days > limit:
            stale.append(key)
        if key in REVISABLE:
            released = _latest_release(grouped[key], cutoff, as_of)
            if released is not None and 0 <= (moment.date() - released.date()).days <= TENTATIVE_DAYS:
                tentative.append(key)
    flags = []
    if tentative:
        flags.append({"id": "tentative", "series": tentative})
    if stale:
        flags.append({"id": "stale", "series": stale})
    gate = _gate(visible, as_of)
    return {
        "rrp": _balance(visible, as_of, "rrp"),
        "tga": _balance(visible, as_of, "tga"),
        "flags": flags,
        "speculation_gate": {
            "state": {"ON": "on", "OFF": "off"}.get(gate["result"]),
            "rule": "HY 2w z < −1.5",
            "value": gate["value"],
            "z": gate["number"],
        },
    }


def _payrolls(visible: dict[str, list[tuple[date, float]]], day: date) -> dict:
    latest = _at(visible["payems"], day)
    past3 = _at(visible["payems"], _shift_months(day, 3))
    past12 = _at(visible["payems"], _shift_months(day, 12))
    if latest is None or past3 is None or past12 is None or latest[0] == past3[0] or latest[0] == past12[0]:
        return _missing("g1", "payems", "growth", "Needs a 3-month and a 12-month payrolls print.")
    delta3 = latest[1] - past3[1]
    delta12 = latest[1] - past12[1]
    return _check(
        "g1",
        "payems",
        "growth",
        "PASS" if delta3 > 0 else "FAIL",
        f"3m {_k(delta3)} vs 12m {_k(delta12)}",
        "Supports when the 3-month change in payrolls is positive.",
        delta3,
    )


def _unemployment(visible: dict[str, list[tuple[date, float]]], day: date) -> dict:
    latest = _at(visible["unrate"], day)
    past = _at(visible["unrate"], _shift_months(day, 3))
    if latest is None or past is None or latest[0] == past[0]:
        return _missing("g2", "unrate", "growth", "Needs an unemployment rate from 3 months ago.")
    delta = latest[1] - past[1]
    return _check(
        "g2",
        "unrate",
        "growth",
        "PASS" if delta <= 0 else "FAIL",
        f"3m {_signed(delta, 2)}pp",
        "Supports when unemployment is not higher than 3 months ago.",
        delta,
    )


def _claims(visible: dict[str, list[tuple[date, float]]], day: date) -> dict:
    short = _window(visible["icsa"], day - timedelta(days=28), day)
    long = _window(visible["icsa"], day - timedelta(days=364), day)
    if len(short) < 2 or len(long) < 8:
        return _missing("g3", "icsa", "growth", "Needs a 4-week and a 52-week claims average.")
    avg4 = sum(short) / len(short)
    avg52 = sum(long) / len(long)
    return _check(
        "g3",
        "icsa",
        "growth",
        "PASS" if avg4 <= avg52 else "FAIL",
        f"4w {_count_k(avg4)} vs 52w {_count_k(avg52)}",
        "Supports when the 4-week average is at or below the 52-week average.",
        avg4 - avg52,
    )


def _cfnai(visible: dict[str, list[tuple[date, float]]], day: date) -> dict:
    window = _window(visible["cfnai"], _shift_months(day, 3), day)
    if not window:
        return _missing("g4", "cfnai", "growth", "Needs a CFNAI print in the last 3 months.")
    avg = sum(window) / len(window)
    return _check(
        "g4",
        "cfnai",
        "growth",
        "PASS" if avg >= 0 else "FAIL",
        f"3m avg {_signed(avg, 2)}",
        "Supports when the 3-month average is at or above zero, the trend-growth line.",
        avg,
    )


def _real_pce(visible: dict[str, list[tuple[date, float]]], day: date) -> dict:
    latest = _at(visible["real_pce"], day)
    past = _at(visible["real_pce"], _shift_months(day, 3))
    if latest is None or past is None or latest[0] == past[0] or past[1] <= 0 or latest[1] <= 0:
        return _missing("g5", "real_pce", "growth", "Needs a real PCE level from 3 months ago.")
    ann = ((latest[1] / past[1]) ** 4 - 1.0) * 100.0
    return _check(
        "g5",
        "real_pce",
        "growth",
        "PASS" if ann > 0 else "FAIL",
        f"3m ann. {_signed(ann, 1)}%",
        "Supports when 3-month annualized real PCE growth is positive.",
        ann,
    )


def _inflation(visible, day: date, check_id: str, key: str, name: str) -> dict:
    latest = _at(visible[key], day)
    past = _at(visible[key], _shift_months(day, 3))
    if latest is None or past is None or latest[0] == past[0]:
        return _missing(check_id, key, "inflation", f"Needs a {name} print from 3 months ago.")
    delta = latest[1] - past[1]
    if delta <= -INFLATION_STEP:
        result = "DOWN"
    elif delta >= INFLATION_STEP:
        result = "UP"
    else:
        result = "FLAT"
    return _check(
        check_id,
        key,
        "inflation",
        result,
        f"yoy {_signed(latest[1], 1).lstrip('+')}% · 3m Δ {_signed(delta, 1)}pp",
        "Cooling when the year-over-year rate is down at least 0.1pp over 3 months. The 3-month annualized rate is not stored.",
        delta,
    )


def _z_check(visible, day, check_id, key, group, horizon, label, detail) -> dict:
    zed = _z(visible[key], day, horizon)
    if zed is None:
        return _missing(check_id, key, group, detail)
    fired = zed >= Z_FIRE
    return _check(
        check_id,
        key,
        group,
        "PASS" if fired else "FAIL",
        f"{label} {_signed(zed, 1)}",
        detail,
        zed,
    )


def _level_check(visible, day, check_id, key, detail, fire_above: float) -> dict:
    latest = _at(visible[key], day)
    if latest is None:
        return _missing(check_id, key, "stress", detail)
    return _check(
        check_id,
        key,
        "stress",
        "PASS" if latest[1] > fire_above else "FAIL",
        f"level {_signed(latest[1], 2)}",
        detail,
        latest[1],
    )


def _trend(visible, day: date) -> dict:
    change = _delta(visible["fed_net_liquidity"], day, 28)
    if change is None:
        return _missing("t1", "fed_net_liquidity", "trend", "Needs a net liquidity print from 28 days ago.")
    zed = _z(visible["fed_net_liquidity"], day, 28)
    if zed is not None:
        if zed >= Z_FIRE:
            result = "UP"
        elif zed <= -Z_FIRE:
            result = "DOWN"
        else:
            result = "FLAT"
    elif change >= LIQ_BAND:
        result = "UP"
    elif change <= -LIQ_BAND:
        result = "DOWN"
    else:
        result = "FLAT"
    return _check(
        "t1",
        "fed_net_liquidity",
        "trend",
        result,
        f"28d {_money(change, signed=True)}",
        "Flat when the 28-day z-score is inside ±1, or, without that history, when the 28-day change is inside ±$50B.",
        change,
    )


def _gate(visible, day: date) -> dict:
    zed = _z(visible["hy_spread"], day, 14)
    if zed is None:
        return _missing("spec", "hy_spread", "gate", "On when the 2-week HY z-score is below −1.5.")
    return _check(
        "spec",
        "hy_spread",
        "gate",
        "ON" if zed < GATE_Z else "OFF",
        f"2w z {_signed(zed, 1)}",
        "On when the 2-week HY z-score is below −1.5. Spread tightening is the speculation gate.",
        zed,
    )


def _balance(visible, day: date, key: str) -> dict:
    latest = _at(visible[key], day)
    change = _delta(visible[key], day, 28)
    if latest is None:
        return {"level": None, "change_28d": None, "level_text": None, "change_text": None}
    return {
        "level": latest[1],
        "change_28d": change,
        "level_text": _money(latest[1], signed=False),
        "change_text": _money(change, signed=True) if change is not None else None,
    }


def _check(check_id, series, group, result, value, detail, number) -> dict:
    return {
        "id": check_id,
        "series": series,
        "group": group,
        "result": result,
        "value": value,
        "detail": detail,
        "number": number,
    }


def _missing(check_id, series, group, detail) -> dict:
    return _check(check_id, series, group, None, None, detail, None)


def _z(points: list[tuple[date, float]], end: date, horizon: int) -> float | None:
    current = _delta(points, end, horizon)
    if current is None:
        return None
    samples = []
    cursor = end - timedelta(days=7)
    for _ in range(52):
        delta = _delta(points, cursor, horizon)
        if delta is not None:
            samples.append(delta)
        cursor -= timedelta(days=7)
    if len(samples) < Z_SAMPLES:
        return None
    mean = sum(samples) / len(samples)
    var = sum((item - mean) ** 2 for item in samples) / (len(samples) - 1)
    if var <= 1e-9:
        return None
    return (current - mean) / math.sqrt(var)


def _delta(points: list[tuple[date, float]], end: date, horizon: int) -> float | None:
    now = _at(points, end)
    then = _at(points, end - timedelta(days=horizon))
    if now is None or then is None or now[0] == then[0]:
        return None
    return now[1] - then[1]


def _at(points: list[tuple[date, float]], target: date) -> tuple[date, float] | None:
    best = None
    for day, value in points:
        if day <= target:
            best = (day, value)
        else:
            break
    return best


def _window(points: list[tuple[date, float]], start: date, end: date) -> list[float]:
    return [value for day, value in points if start < day <= end]


def _visible(points: list[Point], cutoff: datetime) -> list[tuple[date, float]]:
    latest: dict[date, float] = {}
    for point in points:
        if point.released <= cutoff:
            latest[point.day] = point.value
    return sorted(latest.items())


def _latest_release(points: list[Point], cutoff: datetime, as_of: date) -> datetime | None:
    released = None
    for point in points:
        if point.released <= cutoff and point.day <= as_of:
            if released is None or point.day >= released[0]:
                released = (point.day, point.released)
    return None if released is None else released[1]


def _week_ends(as_of: date, count: int) -> list[date]:
    ends = [as_of]
    prev = as_of - timedelta(days=1)
    while prev.weekday() != 4:
        prev -= timedelta(days=1)
    while len(ends) < count:
        ends.append(prev)
        prev -= timedelta(days=7)
    ends.reverse()
    return ends


def _cutoff(day: date, moment: datetime) -> datetime:
    end = datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)
    return moment if moment < end else end


def _group(rows: tuple) -> dict[str, list[Point]]:
    grouped: dict[str, list[Point]] = {key: [] for key in STALE_DAYS}
    for row in rows:
        key = row["series_key"]
        if key not in grouped:
            continue
        day = _parse_day(row["date"])
        released = parse_run_timestamp(row["recorded_at"])
        if day is None or released is None:
            continue
        grouped[key].append(Point(day, float(row["value"]), released))
    for points in grouped.values():
        points.sort(key=lambda point: (point.day, point.released))
    return grouped


def _read(db_path: Path):
    if not db_path.is_file():
        return None, False, None
    try:
        with closing(connect(db_path)) as conn:
            return tuple(conn.execute(BRIEF_SQL)), True, None
    except sqlite3.Error as exc:
        return None, True, str(exc)


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _shift_months(day: date, months: int) -> date:
    month = day.month - months
    year = day.year
    while month <= 0:
        month += 12
        year -= 1
    last = _month_length(year, month)
    return date(year, month, min(day.day, last))


def _month_length(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - timedelta(days=1)).day


def _infl_sign(result: str) -> int:
    if result == "UP":
        return 1
    if result == "DOWN":
        return -1
    return 0


def _ordinal(n: int) -> str:
    if n % 100 in {11, 12, 13}:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _signed(number: float, digits: int) -> str:
    text = f"{abs(number):.{digits}f}"
    if number < 0:
        return f"\u2212{text}"
    return f"+{text}"


def _k(number: float) -> str:
    rounded = int(round(number))
    sign = "\u2212" if rounded < 0 else "+"
    return f"{sign}{abs(rounded):,}k"


def _count_k(number: float) -> str:
    return f"{int(round(number / 1000.0)):,}k"


def _money(number: float, signed: bool) -> str:
    text = f"{abs(number):.1f}"
    if number < 0:
        return f"\u2212${text}B"
    if signed and number > 0:
        return f"+${text}B"
    return f"${text}B"
