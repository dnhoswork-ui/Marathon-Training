"""Marathon Training Plan v2 ("Road to Sub-3:50").

All plan data lives here so the dashboard has a single source of truth.
Dates: plan started the Monday after the April 2026 HM PR; the 9 months are
modeled as 4-week blocks (36 weeks), putting race day in Month 9.
"""

from datetime import date, timedelta

# ---------------------------------------------------------------- athlete
ATHLETE = {
    "hm_pr": "1:56:05",
    "max_hr": 179,
    "resting_hr": 52,
    "hrr": 127,
    "race_cadence": 174,
    "vo2max": "48–50",
}

RACE = {
    "name": "Full Marathon",
    "date": date(2026, 12, 6),          # early-Dec target; edit if the exact race differs
    "goal": "Sub 3:50",
    "goal_pace": "5:27/km",
    "stretch": "Sub 3:35",
    "stretch_pace": "5:07/km",
    "decision": "Month 6 tune-up HM: sub-1:44 → chase Sub-3:35 · 1:44–1:48 → stay Sub-3:50",
}

PLAN_START = date(2026, 4, 6)           # Monday after the April HM PR
WEEKS_PER_MONTH = 4
TOTAL_MONTHS = 9
TOTAL_WEEKS = TOTAL_MONTHS * WEEKS_PER_MONTH  # 36


# ---------------------------------------------------------------- date helpers
def week_index(d: date) -> int:
    """0-based plan week for a date (can be <0 before the plan or >35 after)."""
    return (d - PLAN_START).days // 7


def week_start(i: int) -> date:
    return PLAN_START + timedelta(weeks=i)


def month_of_week(i: int) -> int:
    """1-based plan month for a 0-based week index, clamped to 1..9."""
    return max(1, min(TOTAL_MONTHS, i // WEEKS_PER_MONTH + 1))


def phase_of_month(m: int) -> dict:
    for p in PHASES:
        if p["months"][0] <= m <= p["months"][1]:
            return p
    return PHASES[-1]


# ---------------------------------------------------------------- phases
PHASES = [
    {
        "num": 1,
        "name": "Recovery & Base",
        "months": (1, 3),
        "period": "Months 1–3 · 3 days/week",
        "mileage": "25 → 40 km/week",
        "long_run_peak": "20 km",
        "tempo": "None (M1–2) · 5:20/km (M3)",
        "extra": "Strength 2×/week from Month 2",
        "distribution": "90% Z2 · 10% Z3",
    },
    {
        "num": 2,
        "name": "Aerobic Build",
        "months": (4, 6),
        "period": "Months 4–6 · 3 days/week",
        "mileage": "40 → 52 km/week",
        "long_run_peak": "28 km",
        "tempo": "5:10 → 5:00/km",
        "extra": "Tune-up Half Marathon in Month 6",
        "distribution": "80% Z2 · 15% Z3 · 5% Z4",
    },
    {
        "num": 3,
        "name": "Marathon Specific",
        "months": (7, 9),
        "period": "Months 7–9 · 4 days/week",
        "mileage": "52 → 60 → 32 km ↓ taper",
        "long_run_peak": "32 km × 2 runs",
        "tempo": "4:55/km → marathon race pace",
        "extra": "4th day added: med-long 15 km",
        "distribution": "70% Z2 · 20% Z3 · 10% Z4",
    },
]

# weekly-mileage target (km) for each plan month
MONTHLY_KM = {1: 25, 2: 33, 3: 40, 4: 44, 5: 48, 6: 52, 7: 55, 8: 60, 9: 32}

# long-run peak (km) reached by the end of each month — for chart reference lines
MONTHLY_LONG_PEAK = {1: 14, 2: 18, 3: 20, 4: 24, 5: 28, 6: 28, 7: 30, 8: 32, 9: 12}


def weekly_target_km(i: int) -> float:
    """Planned weekly volume for a 0-based week index (race week ≈ taper)."""
    return float(MONTHLY_KM[month_of_week(i)])


# ---------------------------------------------------------------- weekly structure
WEEKLY_SESSIONS = [
    {
        "day": "Monday", "type": "Easy Z2", "hr": "128–141 bpm",
        1: "6–8 km easy Zone 2 + 6×20s strides",
        2: "8–10 km easy Zone 2 + 8×20s strides",
        3: "10–12 km easy Zone 2 — strides mandatory",
    },
    {
        "day": "Tuesday", "type": "Strength", "hr": "—",
        1: "Rest (M1) · 20–30 min strength from M2: squats, hip thrusts, calf raises",
        2: "30 min strength: single-leg squats, deadlifts, hip thrusts, calf raises",
        3: "30 min strength: single-leg focus + plyometrics",
    },
    {
        "day": "Wednesday", "type": "Tempo Z3–4", "hr": "154–166 bpm",
        1: "Rest (M1–2) · 10–12 km tempo @ 5:20/km (M3 only)",
        2: "12–14 km threshold @ 5:10 → 5:00/km",
        3: "14–16 km threshold intervals @ 4:55 → marathon pace",
    },
    {
        "day": "Friday", "type": "Med Long", "hr": "141–154 bpm",
        1: "— Rest —",
        2: "— Rest —",
        3: "15 km with last 5 km at marathon race pace",
    },
    {
        "day": "Sunday", "type": "Long Run", "hr": "128–141 bpm (non-negotiable)",
        1: "12–20 km strictly Zone 2 · gel practice from 16 km+",
        2: "20–28 km strictly Zone 2 · full gel strategy every run",
        3: "28–32 km strictly Zone 2 · two 30 km+ runs in Month 8",
    },
]

RUN_TYPES = ["Easy Z2", "Tempo", "Long Run", "Med Long", "Intervals", "Race", "Strength", "Other"]

# ---------------------------------------------------------------- HR zones (Karvonen)
HR_ZONES = [
    {"zone": "Z1 Recovery", "bpm": "116–128", "pct": "50–60% HRR", "desc": "Walk/jog recovery, active rest days"},
    {"zone": "Z2 Aerobic Base", "bpm": "128–141", "pct": "60–70% HRR", "desc": "Fat burning, mitochondria — ALL long runs here"},
    {"zone": "Z3 Tempo", "bpm": "141–154", "pct": "70–80% HRR", "desc": "Aerobic threshold, comfortably hard"},
    {"zone": "Z4 Threshold", "bpm": "154–166", "pct": "80–90% HRR", "desc": "Lactate threshold, HM race pace zone"},
    {"zone": "Z5 Max", "bpm": "166–179", "pct": "90–100% HRR", "desc": "Anaerobic, race finish — strides & sprints only"},
]
Z2_RANGE = (128, 141)

# ---------------------------------------------------------------- race strategy
# offsets in sec/km applied for the Sub-3:35 stretch goal (plan v2: ~10 s/km faster)
STRETCH_OFFSET_S = 10

RACE_STRATEGY = [
    {"km": "0–5 km", "phase": "Ease In", "pace": "5:40", "zone": "Zone 2", "split": "~28:20",
     "note": "Resist the adrenaline. Trust the watch, not your legs. Let faster runners pass."},
    {"km": "5–21 km", "phase": "Cruise", "pace": "5:30", "zone": "Zone 3", "split": "~1:54–1:55 half",
     "note": "Should feel controlled, almost boring. If it feels hard before 21 km, back off. Gel at 8 km."},
    {"km": "21–32 km", "phase": "Build", "pace": "5:25", "zone": "Zone 3–4", "split": "~2:53 @ 32 km",
     "note": "The real race begins. Gels at 16 & 24 km. The wall lurks between 30–35 km."},
    {"km": "32–42.2 km", "phase": "Finish", "pace": "5:20", "zone": "Zone 4", "split": "~3:47–3:49 finish",
     "note": "Caffeinated gel at 30 km, standard at 36 km. Legs left → push. Hurting → hold pace, don't blow up."},
]

GUT_CHECKS = [
    {"km": "5 km", "time": "~28:20", "note": "Should feel easy. If hard → back off now."},
    {"km": "10 km", "time": "~56:40", "note": "HR settling into Zone 3. Gel taken at 8 km."},
    {"km": "21.1 km", "time": "~1:54–1:55", "note": "Halfway. Still feeling good? Slight negative split ahead."},
    {"km": "30 km", "time": "~2:43", "note": "Wall territory. Caffeinated gel now."},
    {"km": "35 km", "time": "~3:10", "note": "7.2 km to go. Hold form, cadence up."},
    {"km": "40 km", "time": "~3:37", "note": "2.2 km left. Empty the tank."},
]

GEL_PLAN = [
    {"at": "Start", "gel": "Standard", "note": "Before flag-off"},
    {"at": "8 km", "gel": "Standard", "note": "~45 min in"},
    {"at": "16 km", "gel": "Standard", "note": "~88 min in"},
    {"at": "24 km", "gel": "Caffeinated ☕", "note": "~130 min · pre-wall"},
    {"at": "30 km", "gel": "Caffeinated ☕", "note": "~163 min · wall zone"},
    {"at": "36 km", "gel": "Standard", "note": "~196 min · final push"},
]

WALL_WARNING = (
    "**The Wall (km 30–35):** glycogen depletes here regardless of pacing. Your defence: "
    "(1) strict Zone 2 long runs building fat adaptation, (2) gels every 30–35 min practiced in "
    "training, (3) a conservative start so you have reserves. Never skip gels on long runs — "
    "your gut needs training too."
)

# ---------------------------------------------------------------- projections & milestones
PROJECTIONS = [
    {"when": "Month 3", "hm": "1:52–1:54", "fm": "~3:56–4:00", "note": "Base restored, tempo begins"},
    {"when": "Month 5", "hm": "1:48–1:50", "fm": "~3:46–3:52", "note": "Cardiac drift reducing, long runs 24 km+"},
    {"when": "Month 6 — tune-up HM", "hm": "1:44–1:46", "fm": "~3:38–3:44", "note": "Race full effort. Sub-1:44 unlocks Sub-3:35"},
    {"when": "Month 9 — race day", "hm": "1:40–1:42", "fm": "Sub 3:50", "note": "Two 30 km+ runs done, peak fitness"},
]

MILESTONES = {
    1: "DOMS resolved. RHR back to 52 bpm. Easy runs feel genuinely easy.",
    2: "18 km long run in Zone 2 without HR drift above 148. Strength 2×/wk started.",
    3: "Tempo begins at 5:20/km. Gel practice on every run 16 km+.",
    4: "Tempo reaches 5:10/km. Long run hits 24 km. HR at 5:30/km drops below 150.",
    5: "Long run hits 28 km. Cardiac drift under 15 bpm over 21 km.",
    6: "Tune-up HM race — full effort. Decision point on the stretch goal.",
    7: "4th training day added. First 30 km+ long run with full gel plan.",
    8: "Second 30 km+ run done. Tempo at 4:55/km. Peak week 60 km.",
    9: "Wk 1–2 taper: cut volume 40%, keep intensity. Race week: shakeout, carb load, 8–9 h sleep, nothing new.",
}

ECONOMY_TARGETS = [
    "Cadence: 174 → **178–180 spm by Month 6** via strides",
    "Ground contact time: 233 ms → **under 220 ms** via plyometrics",
    "Cardiac drift: 22 bpm → **under 15 bpm** over 21 km by Month 4",
    "Vertical oscillation: keep **below 9.0 cm** (currently 8.7 cm ✅)",
    "Z2 efficiency: run 5:30/km at **135 bpm by Month 6** (race day was 166 bpm)",
    "LT pace: 5:20/km → **5:00/km by Month 7**",
    "VO₂max: 48–50 → **52–54 by race month**",
    "Monthly check: HR at 5:30/km should drop **3–5 bpm each month**",
    "80/20 rule: 80% of all runs in Zone 1–2 — zero grey-zone junk miles",
]

GOLDEN_RULES = [
    ("🐢", "Long runs must feel embarrassingly slow", "Zone 2 is 128–141 bpm. If it feels too easy, you're doing it right."),
    ("🔥", "Easy days easy, hard days hard", "Medium effort is the enemy — too hard to recover, too easy to adapt."),
    ("🧪", "Nothing new on race day", "Shoes, gels, kit, breakfast — all tested in training."),
    ("📊", "Let the data decide your target", "The Month 6 tune-up sets the marathon goal. Evidence over ambition."),
    ("💤", "Sleep is your 4th training day", "Adaptation happens during recovery, not the run."),
    ("🛑", "High RHR = mandatory rest", "5+ bpm above your 52 baseline → skip the session. Always."),
]

KEY_NUMBERS = [
    ("Zone 2 HR", "128–141 bpm", "all long runs"),
    ("Tempo HR", "154–166 bpm", "Wednesday sessions"),
    ("Target cadence", "178–180 spm", "by Month 6"),
    ("GCT target", "<220 ms", "now 233 ms"),
    ("HR drift goal", "<15 bpm", "over 21 km by Month 4"),
    ("Weekly increase", "max 10%", "mileage rule, always"),
    ("Daily protein", "145–158 g", "in training"),
    ("Race carbs", "60–90 g/h", "via gels"),
]
