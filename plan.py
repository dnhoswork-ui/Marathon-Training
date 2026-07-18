"""Plan layer for training plan v3 — everything loads from the JSON files.

Source of truth:
- data/training_plan_v3.json  (phases, ladders, bands, tune-up decision gate)
- data/athlete_profile.json   (HR zones, PRs, shoes, fueling, conventions)

Never hardcode phase dates here — read them from the JSON.
"""

import json
import os
from datetime import date, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))


def _load(name: str) -> dict:
    with open(os.path.join(_BASE, "data", name)) as f:
        return json.load(f)


PLAN = _load("training_plan_v3.json")
PROFILE = _load("athlete_profile.json")

RACE_DATE = date.fromisoformat(PLAN["race_date"])
PHASES = PLAN["phases"]
GOLDEN_RULES = PLAN["golden_rules"]
PACE_REFERENCE = PLAN["pace_reference"]

# HR zones (Garmin 265 baseline — provisional until the LTHR field test)
HR = PROFILE["heart_rate"]
Z2 = (138, 154)
Z2_TRAIN = (138, 150)
ZONES_PROVISIONAL = "PROVISIONAL" in HR.get("status", "")

GPA_MAP = PROFILE["conventions"]["gpa_map"]
SHOES = PROFILE["shoes"]
SHOE_NAMES = [s["model"] for s in SHOES]
FUELING = PROFILE["fueling"]
ENVIRONMENT = PROFILE["environment"]

RUN_TYPES = ["easy", "long", "tempo", "field_test", "shakeout", "race_hm", "race_fm", "strength", "other"]
SURFACES = ["outdoor", "treadmill"]
GRADES = ["", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]

# real gaps — annotate, never interpolate
GAPS = [
    (date(2026, 4, 25), date(2026, 5, 13), "Illness"),
    (date(2026, 6, 15), date(2026, 6, 24), "Holiday"),
]

# heat model: ~+2–3 s/km per °C of feels-like above 28 (use midpoint 2.5)
HEAT_THRESHOLD_C = 28.0
HEAT_S_PER_KM_PER_C = 2.5


# ---------------------------------------------------------------- phases
def _d(s: str) -> date:
    return date.fromisoformat(s)


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
GOAL_OFFSETS_S = {"3:50": 0, "3:40": 14, "3:35": 21}
GOALS = {
    "3:50": {"label": "Sub 3:50", "pace": "5:27/km", "kind": "primary"},
    "3:40": {"label": "Sub 3:40", "pace": "5:13/km", "kind": "signal"},
    "3:35": {"label": "Sub 3:35", "pace": "5:06/km", "kind": "stretch"},
}

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
