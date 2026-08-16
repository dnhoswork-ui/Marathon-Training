"""Plan layer for training plan v3 — everything loads from the JSON files.

Source of truth:
- data/training_plan_v3.json  (phases, ladders, bands, tune-up decision gate)
- data/athlete_profile.json   (HR zones, PRs, shoes, fueling, conventions)

Never hardcode phase dates here — read them from the JSON.
"""

import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_BASE = os.path.dirname(os.path.abspath(__file__))


def _load(name: str) -> dict:
    with open(os.path.join(_BASE, "data", name)) as f:
        return json.load(f)


PLAN = _load("training_plan_v3.json")
PROFILE = _load("athlete_profile.json")

RACE_DATE = date.fromisoformat(PLAN["race_date"])
ATHLETE = PROFILE.get("athlete", {})
DEVICE = ATHLETE.get("device", "")

# Streamlit Cloud runs on UTC; the athlete trains in Singapore (UTC+8), so a
# morning run there is "tomorrow" to a UTC server. Anchor the app to local time.
TZ = ZoneInfo({"Singapore": "Asia/Singapore"}.get(ATHLETE.get("location", ""), "UTC"))


def today() -> date:
    return datetime.now(TZ).date()


PHASES = PLAN["phases"]
GOLDEN_RULES = PLAN["golden_rules"]
PACE_REFERENCE = PLAN["pace_reference"]

# ---------------------------------------------------------------- HR: versioned LTHR
# LTHR is date-versioned. A run must always be graded against the zones that were
# in effect the day it was run, or the whole March–July history gets retro-classified
# against bands that did not exist yet.
HR = PROFILE["heart_rate"]
MAX_HR = HR["max_hr"]
RESTING_HR = HR.get("resting_hr_baseline")


def _d(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(str(s)[:10])


LTHR_HISTORY = sorted(HR["lthr_history"], key=lambda e: _d(e["effective_from"]))
LTHR_CURRENT = HR.get("lthr_current") or LTHR_HISTORY[-1]["lthr"]
# the earliest entry's start is a placeholder — surfaced in the UI, not silently trusted
LTHR_EPOCH_IS_PLACEHOLDER = "placeholder" in (LTHR_HISTORY[0].get("note") or "").lower()
ZONE_PCT = HR.get("zone_model_boundaries_pct", {})


def lthr_entry_for(run_date) -> dict:
    """The LTHR history entry in effect on run_date (earliest entry for older runs)."""
    d = _d(run_date)
    active = LTHR_HISTORY[0]
    for e in LTHR_HISTORY:
        if _d(e["effective_from"]) <= d:
            active = e
        else:
            break
    return active


def zones_for(run_date) -> dict:
    return lthr_entry_for(run_date)["zones_bpm"]


def zone_of(hr, run_date) -> str | None:
    """'z1'..'z5' for an HR reading, using the zones in effect that day."""
    if hr is None:
        return None
    bands = zones_for(run_date)
    for name in ("z1", "z2", "z3", "z4", "z5"):
        lo, hi = bands[name]
        if lo <= hr <= hi:
            return name
    return "z5" if hr > bands["z5"][1] else "z1"


def pct_lthr(hr, run_date) -> float | None:
    """HR as a percentage of the LTHR in effect that day — comparable across the
    whole history, which raw bpm is not once LTHR changes."""
    if hr is None:
        return None
    return round(100.0 * hr / lthr_entry_for(run_date)["lthr"], 1)


# current-day convenience bands (charts that only describe "now")
Z2 = tuple(zones_for(today())["z2"])
_easy = PLAN["phases"][1].get("key_sessions", {}).get("easy", {})
Z2_TRAIN = tuple(_easy["target_hr_bpm"]) if isinstance(_easy, dict) and _easy.get("target_hr_bpm") else Z2
Z2_PCT = tuple(ZONE_PCT.get("z2", (80, 89)))
ZONES_PROVISIONAL = False   # locked in by the 30 Jul field test

THRESHOLD_PACE = PROFILE.get("threshold_pace", {}).get("current", {})
CHECKPOINTS = PROFILE.get("checkpoints", [])
KNOWN_ISSUES = PROFILE.get("known_issues", [])
MARATHON_EQUIV = PROFILE.get("primary_race", {}).get("current_marathon_equivalent", {})

GPA_MAP = PROFILE["grading"]["points"]
GPA_RANGE = (min(GPA_MAP.values()) - 0.5, max(GPA_MAP.values()) + 0.5)
SHOES = [{"model": v, "role": k.replace("_", " ")} for k, v in PROFILE["shoes"].items()]
SHOE_NAMES = [s["model"] for s in SHOES]
FUELING = PROFILE["fueling"]
ENVIRONMENT = PROFILE["heat_model"]
CONVENTIONS = PROFILE.get("conventions", {})

RUN_TYPES = ["easy", "steady", "long", "tempo", "lthr_test", "shakeout",
             "race_hm", "race_fm", "strength", "other"]
SURFACES = ["outdoor", "treadmill", "mixed"]
# only outdoor road is comparable for pace trends: treadmill runs ~15–20 s/km easier,
# and mixed/trail surfaces cost 10–20 s/km at equivalent effort
PACE_COMPARABLE_SURFACES = ["outdoor"]
# Power is terrain-independent between outdoor surfaces — road vs gravel, flat vs
# rolling — which is why mixed routes belong on a W/bpm chart even though they are
# not pace-comparable. It does not extend to treadmill: no air resistance.
POWER_COMPARABLE_SURFACES = ["outdoor", "mixed"]
FATIGUE_WINDOW_DAYS = 10
FATIGUE_DROP_PCT = 3.0

# Z3 above this share is grey-zone leakage on an easy-intent run — but on a long,
# tempo or race session Z3 is marathon specificity (goal MP 5:27/km ≈ 162 bpm,
# inside the 158–166 Z3 band), so those session types are exempt.
GREY_ZONE_Z3_PCT = 50
GREY_ZONE_EXEMPT = ("long", "tempo", "race_hm", "race_fm", "lthr_test")


def grey_zone_flag(run_type, z3_pct) -> bool:
    if run_type in GREY_ZONE_EXEMPT or z3_pct is None:
        return False
    return z3_pct > GREY_ZONE_Z3_PCT


def time_of_day(start: str | None) -> str | None:
    """Singapore mornings and evenings are different thermal environments —
    comparing a 17:12 run with an 06:01 run produces a false fitness signal."""
    if not start or ":" not in str(start):
        return None
    h, m = (int(x) for x in str(start).split(":")[:2])
    mins = h * 60 + m
    return "morning" if mins < 11 * 60 else "midday" if mins < 16 * 60 else "evening"


TIMES_OF_DAY = ["morning", "midday", "evening"]
GRADES = ["", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]

# real gaps — annotate, never interpolate
GAPS = [
    (date(2026, 4, 25), date(2026, 5, 13), "Illness"),
    (date(2026, 6, 15), date(2026, 6, 24), "Holiday"),
]

# heat model, from the profile: +15–30 s/km above the feels-like threshold.
# The per-°C figure is the midpoint of that range spread over a ~10°C excursion.
HEAT_THRESHOLD_C = float(ENVIRONMENT.get("feels_like_threshold_c", 28))
_pen = ENVIRONMENT.get("pace_penalty_sec_per_km", [15, 30])
HEAT_S_PER_KM_PER_C = round(sum(_pen) / 2 / 10, 2)
HEAT_HR_PENALTY = ENVIRONMENT.get("hr_penalty_bpm", [5, 8])


# ---------------------------------------------------------------- phases


def phase_of(d: date) -> dict | None:
    for p in PHASES:
        if _d(p["start"]) <= d <= _d(p["end"]):
            return p
    return None


def current_phase(today: date) -> dict:
    p = phase_of(today)
    if p:
        return p
    if today < _d(PHASES[0]["start"]):
        return PHASES[0]
    return PHASES[-1]


def phase_week(p: dict, today: date) -> int:
    """1-based week within a phase (0 = phase hasn't started yet)."""
    if today < _d(p["start"]):
        return 0
    return (today - _d(p["start"])).days // 7 + 1


def display_phase(today: date) -> dict:
    """The phase the dashboard should focus on: the active one, or — once a
    phase is marked complete — the next one coming up."""
    p = phase_of(today)
    if p and p["status"] != "complete":
        return p
    upcoming = [q for q in PHASES if _d(q["start"]) > today]
    if upcoming:
        return upcoming[0]
    return p or PHASES[-1]


# taper weekly volumes parsed once from its structure strings (approximate)
_TAPER_KMS = [40, 28, 19]


def weekly_band(week_monday: date) -> tuple[float, float] | None:
    """(lo, hi) weekly-km target for the week starting on this Monday, or None pre-plan."""
    p = phase_of(week_monday) or phase_of(week_monday + timedelta(days=6))
    if not p:
        return None
    if p["id"] == "taper":
        idx = min((week_monday - _d(p["start"])).days // 7, len(_TAPER_KMS) - 1)
        km = _TAPER_KMS[max(idx, 0)]
        return (km * 0.85, km * 1.1)
    band = p.get("weekly_km")
    if not band:
        return None
    # linear ramp lo→hi across the phase
    total = (_d(p["end"]) - _d(p["start"])).days or 1
    frac = min(max((week_monday - _d(p["start"])).days / total, 0), 1)
    mid = band[0] + (band[1] - band[0]) * frac
    return (max(band[0] * 0.9, mid - 5), min(band[1] * 1.05, mid + 5))


def full_ladder() -> list[dict]:
    """Planned long runs across phase 2, phase 3, and taper (date, km, type)."""
    ladder = []
    for p in PHASES:
        for step in p.get("long_run_ladder", []):
            ladder.append({**step, "phase": p["id"]})
    taper = next(p for p in PHASES if p["id"] == "taper")
    ladder += [
        {"date": "2026-11-21", "km": 20, "type": "taper", "phase": "taper"},
        {"date": "2026-11-28", "km": 15, "type": "taper", "phase": "taper"},
    ]
    _ = taper
    return sorted(ladder, key=lambda s: s["date"])


def next_long_run(today: date) -> dict | None:
    for step in full_ladder():
        if _d(step["date"]) >= today:
            return step
    return None


# ---------------------------------------------------------------- race strategy
# Segment pacing retained from plan v2 (still keyed to the 3:50 target); the
# goal selector shifts every pace by a fixed offset per target.
GOAL_OFFSETS_S = {"3:50": 0, "3:40": 14}
GOALS = {
    "3:50": {"label": "Sub 3:50", "pace": "5:27/km", "kind": "primary"},
    "3:40": {"label": "Sub 3:40", "pace": "5:13/km", "kind": "signal"},
}
# sub-3:35 was retired on 2026-07-30 after the field test; kept for the record
RETIRED_GOALS = PROFILE.get("primary_race", {}).get("retired_goals", [])

RACE_STRATEGY = [
    {"km": "0–5 km", "phase": "Ease In", "pace": "5:40", "zone": "Zone 2",
     "note": "Resist the adrenaline. Trust the watch, not your legs. Let faster runners pass."},
    {"km": "5–21 km", "phase": "Cruise", "pace": "5:30", "zone": "Zone 3",
     "note": "Controlled, almost boring. If it feels hard before 21 km, back off. Gel at 8 km."},
    {"km": "21–32 km", "phase": "Build", "pace": "5:25", "zone": "Zone 3–4",
     "note": "The real race begins. Gels at 16 & 24 km. The wall lurks between 30–35 km."},
    {"km": "32–42.2 km", "phase": "Finish", "pace": "5:20", "zone": "Zone 4",
     "note": "Caffeinated gel at 30 km, standard at 36 km. Legs left → push. Hurting → hold pace."},
]

GUT_CHECKS = [  # 3:50 pacing
    {"km": "5 km", "time": "~28:20", "note": "Should feel easy. If hard → back off now."},
    {"km": "10 km", "time": "~56:40", "note": "HR settling into Zone 3. Gel taken at 8 km."},
    {"km": "21.1 km", "time": "~1:54–1:55", "note": "Halfway. Slight negative split ahead."},
    {"km": "30 km", "time": "~2:43", "note": "Wall territory. Caffeinated gel now."},
    {"km": "35 km", "time": "~3:10", "note": "7.2 km to go. Hold form, cadence up."},
    {"km": "40 km", "time": "~3:37", "note": "2.2 km left. Empty the tank."},
]

WALL_WARNING = (
    "**The Wall (km 30–35):** glycogen depletes here regardless of pacing. Your defence: "
    "strict Z2 long runs, gels every 30–35 min practiced in training, and a conservative start."
)
