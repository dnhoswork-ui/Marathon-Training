# Road to Sub-3:50 — Marathon Training Dashboard

A Streamlit dashboard for a marathon build (race day **8 Dec 2026**), driven by
**training plan v3**: Base/Rebuild (complete) → Build → Peak → Taper, with a
Sub-3:50 primary goal and a 3:40 / 3:35 decision gate at the early-October
tune-up half marathon.

Everything plan-related loads from JSON — no dates or targets are hardcoded:

| File | Purpose |
|---|---|
| `data/training_plan_v3.json` | Phases, weekly-km bands, long-run ladders, tune-up decision rule, taper |
| `data/athlete_profile.json` | HR zones (Garmin 265), PRs, shoes, fueling, grading conventions, heat model |
| `data/runs.csv` | The run log — 28 historical sessions plus everything logged via the app |

## What's on it

- **Overview** — race countdown, phase timeline with a today-marker, current
  phase card (weekly template, key sessions, exit criteria), next long run.
- **Log runs** — Garmin screenshot → Claude extracts distance/time/HR/cadence/
  VO/GCT (needs `ANTHROPIC_API_KEY`); full manual form incl. surface, feels-like
  °C, shoe, grade, and HR-halves for drift tracking. Every save commits
  `data/runs.csv` back to the repo.
- **Progress** — weekly volume vs the phase target band with 10%-rule flags and
  honest gap annotations (illness/holiday); long-run ladder planned-vs-actual
  with grade chips; **Efficiency Factor** trend (3-run MA, split by surface);
  pace-vs-HR scatter with the Z2 band; grade-GPA trend; cadence/VO/GCT form
  panel; cardiac-drift table; shoe mileage. Heat-adjusted pace toggle
  (~2.5 s/km per °C of feels-like above 28).
- **Training plan** — phase cards, the full long-run ladder, Garmin-265 HR
  zones (provisional until the LTHR field test), pace reference, taper
  structure, environment notes, golden rules.
- **Race day** — three goal targets with the October decision gate, a Riegel
  race predictor that activates once the tune-up HM is logged (`race_hm`),
  pacing plan per goal, gut-check splits, fueling protocol.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy on Streamlit Community Cloud

Deploy `streamlit_app.py` from `main`, then add secrets (Settings → Secrets):

```toml
ANTHROPIC_API_KEY = "sk-ant-..."   # screenshot parsing (optional)
GITHUB_TOKEN = "github_pat_..."    # run-log commits to this repo (recommended)
GITHUB_REPO = "dnhoswork-ui/Marathon-Training"
GITHUB_BRANCH = "main"
```

The token is a fine-grained PAT scoped to this repo with **Contents: Read and
write**. Without it the app still works, but runs logged on Streamlit Cloud
don't survive restarts (use the Download button as a manual backup).

## Conventions baked in

- Treadmill and outdoor are never mixed in pace/EF comparisons (treadmill runs
  ~15–20 s/km easier).
- The race row and the one approx-date row are excluded from fitness trends.
- Illness (25 Apr–13 May) and holiday (15–24 Jun) are annotated as real gaps,
  never interpolated.
- Zones change only via a field test — the app flags them as provisional until
  the Phase 2 week-1 LTHR test is done.
