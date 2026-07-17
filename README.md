# Road to Sub-3:50 — Marathon Training Dashboard

A Streamlit dashboard built around a 9-month "Marathon Training Plan v2":
three phases (Recovery & Base → Aerobic Build → Marathon Specific), HR-zone
driven training, a Sub-3:50 primary goal and a Sub-3:35 stretch goal decided at
the Month 6 tune-up half marathon.

## What it does

- **Overview** — days to race, current month/phase/week, this week's sessions
  for the current phase, weekly target vs. logged km, monthly milestone.
- **Log runs** — upload a Garmin/Strava/Coros **screenshot** and Claude extracts
  date, distance, time, HR, and cadence (needs an `ANTHROPIC_API_KEY` secret);
  or type runs in manually. The log is editable in-place and every save is a
  commit of `data/runs.csv` back to this repo.
- **Progress** — weekly volume vs. the plan's 25→60 km build, long-run
  progression toward the 32 km peak, and Z2 efficiency (avg HR on easy/long
  runs against the 128–141 bpm band).
- **Training plan** — the full plan: phase cards, weekly session structure,
  Karvonen HR zones (max 179 / rest 52), monthly milestones, running-economy
  targets, golden rules.
- **Race strategy** — the 5:40 → 5:30 → 5:25 → 5:20 pacing plan, gut-check
  splits, the 6-gel plan, and performance projections. A sidebar toggle switches
  every pace to the Sub-3:35 stretch plan (~10 s/km faster).

## Run it locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Without any secrets the app works fully — runs are saved to the local
`data/runs.csv` (and you can download the CSV from the Log runs tab).

## Deploy on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** → pick
   this repo/branch → main file `streamlit_app.py`.
2. In the app's **Settings → Secrets**, add:

```toml
# enables screenshot parsing (optional)
ANTHROPIC_API_KEY = "sk-ant-..."

# enables saving runs back to this repo (optional but recommended —
# Streamlit Cloud storage is wiped between sessions)
GITHUB_TOKEN = "github_pat_..."   # fine-grained PAT, Contents: Read & write on this repo
GITHUB_REPO = "dnhoswork-ui/Marathon-Training"
GITHUB_BRANCH = "main"
```

With `GITHUB_TOKEN` set, every saved run is committed to `data/runs.csv`, so
your history is versioned and survives app restarts. Without it, use the
**Download runs.csv** button as a manual backup.

## Files

| File | Purpose |
|---|---|
| `streamlit_app.py` | The dashboard (tabs, charts, forms) |
| `plan.py` | The entire training plan as data — edit here to adjust the plan, race date, or targets |
| `storage.py` | `data/runs.csv` load/save, with GitHub-commit sync |
| `parser.py` | Claude vision call that turns run screenshots into structured data |
| `data/runs.csv` | Your run log (committed by the app when GitHub sync is on) |

The plan is anchored on `PLAN_START = 2026-04-06` with months modeled as 4-week
blocks, putting race day (2026-12-06) in Month 9. Edit both dates in `plan.py`
if the actual race differs.
