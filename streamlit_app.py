"""Road to Sub-3:50 — marathon dashboard, training plan v3 (JSON-driven)."""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import importlib

import parser as run_parser
import plan
import storage

# Streamlit hot-reloads this script but keeps imported modules cached, which
# strands the app on stale code after a git push — reload them every run
# (cheap: two small JSON reads).
for _m in (plan, storage, run_parser):
    importlib.reload(_m)

st.set_page_config(page_title="Road to Sub-3:50", page_icon="🏃", layout="wide")

# validated palette (dataviz): outdoor=blue, treadmill=green, mixed=mauve,
# plan/targets=muted. All-pairs CVD-checked against both surfaces.
C_OUT = "#2a78d6"
C_TM = "#008300"
C_MIX = "#a8577a"
C_MUTED = "#898781"
C_GRID = "#e1e0d9"
C_BAND = "#9ec5f4"
C_CRIT = "#d03b3b"
SURF_COLORS = {"outdoor": C_OUT, "mixed": C_MIX, "treadmill": C_TM}
SURF_SCALE = alt.Scale(domain=list(SURF_COLORS), range=list(SURF_COLORS.values()))


def surf_scale(d: pd.DataFrame) -> alt.Scale:
    """Colour scale limited to the surfaces actually plotted, so a filtered-out
    series never lingers in the legend as an entry with no marks."""
    present = [s for s in SURF_COLORS if s in set(d["surface"])]
    return alt.Scale(domain=present, range=[SURF_COLORS[s] for s in present])
AXIS = alt.Axis(gridColor=C_GRID, domainColor=C_GRID, labelColor=C_MUTED, titleColor=C_MUTED)
PACE_LABEL = "floor(datum.value/60) + ':' + (datum.value%60 < 10 ? '0' : '') + toString(round(datum.value%60))"


# ---------------------------------------------------------------- helpers
def fmt_pace(sec) -> str:
    if pd.isna(sec):
        return "—"
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_hms(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def duration_to_min(d) -> float | None:
    if not isinstance(d, str) or ":" not in d:
        return None
    parts = [int(p) for p in d.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 60 + parts[1] + parts[2] / 60
    if len(parts) == 2:
        return parts[0] + parts[1] / 60
    return None


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        return df
    # fill pace_sec_per_km from duration+distance where missing
    mins = df["duration"].map(duration_to_min)
    computed = (mins * 60 / df["distance_km"]).where(df["distance_km"] > 0)
    df["pace_sec_per_km"] = df["pace_sec_per_km"].fillna(computed)
    df["week"] = df["date"].map(week_monday)
    df["is_run"] = ~df["run_type"].isin(["strength", "other"])
    # HR as % of the LTHR in effect that day — the only HR measure comparable
    # across the 30 Jul rebase (raw bpm is not)
    df["pct_lthr"] = [plan.pct_lthr(hr, d) if pd.notna(hr) else None
                      for hr, d in zip(df["avg_hr"], df["date"])]
    df["zone"] = [plan.zone_of(hr, d) if pd.notna(hr) else None
                  for hr, d in zip(df["avg_hr"], df["date"])]
    df["lthr_then"] = [plan.lthr_entry_for(d)["lthr"] for d in df["date"]]
    df["time_of_day"] = df["start_time"].map(plan.time_of_day)
    # W/bpm: work done per heartbeat. Unlike EF it is indifferent to terrain and
    # heat, which makes it the cleanest fatigue signal available.
    df["watts_per_bpm"] = (df["avg_power_w"] / df["avg_hr"]).round(3)
    df["grey_zone"] = [plan.grey_zone_flag(t, z) if pd.notna(z) else False
                       for t, z in zip(df["run_type"], df["z3_pct"])]
    df["zones_known"] = df["z3_pct"].notna()
    # pace: road only. power: road + mixed — terrain-independent between outdoor
    # surfaces, but not against a treadmill belt with no air resistance.
    df["pace_comparable"] = df["surface"].isin(plan.PACE_COMPARABLE_SURFACES)
    df["power_comparable"] = df["surface"].isin(plan.POWER_COMPARABLE_SURFACES)
    return df


def heat_adjusted(df: pd.DataFrame, on: bool) -> pd.DataFrame:
    """Adds pace_adj (heat-adjusted pace where feels-like was logged)."""
    df = df.copy()
    adj = (df["feels_like_c"] - plan.HEAT_THRESHOLD_C).clip(lower=0) * plan.HEAT_S_PER_KM_PER_C
    df["pace_adj"] = df["pace_sec_per_km"] - adj.fillna(0) if on else df["pace_sec_per_km"]
    return df


def trend_pool(df: pd.DataFrame) -> pd.DataFrame:
    """Rows usable for fitness trends: exact dates, no races/shakeouts/field tests."""
    return df[df["is_run"] & (df["date_precision"] != "approx")
              & df["run_type"].isin(["easy", "long", "tempo"])]


def fatigue_pool(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Same-intensity W/bpm comparison set: Z2 only, outdoor or mixed, recent.

    Treadmill is dropped (no air resistance, so power isn't comparable) and so is
    anything flagged out of the EF trend (the 30 Jul field test — a maximal effort
    inflates W/bpm). Zone is the filter, but a run with no time-in-zone recorded
    still qualifies on run_type: 2 Aug is the reference case for the whole panel
    and has no zone data, so filtering on zone alone would discard the very
    decoupling this chart exists to catch.
    """
    d = df[df["is_run"] & df["power_comparable"]
           & df["include_in_ef_trend"]].dropna(subset=["watts_per_bpm"]).copy()
    inferred = d["dominant_zone"].isna() & d["run_type"].isin(["easy", "long"])
    d = d[(d["dominant_zone"] == "z2") | inferred]
    d["zone_inferred"] = inferred.reindex(d.index, fill_value=False)
    d = d[d["date"] >= plan.today() - timedelta(days=days)].sort_values("date")
    d["wbpm_delta_pct"] = d["watts_per_bpm"].pct_change() * 100
    d["fatigue_flag"] = d["wbpm_delta_pct"] < -plan.FATIGUE_DROP_PCT
    return d


# 30 Jul 2026 LTHR rebase — annotates any HR-over-time chart so the step change
# in zone classification doesn't look like a data bug
LTHR_MARKS = pd.DataFrame([
    {"d": str(e["effective_from"]),
     "label": f"LTHR → {e['lthr']}"}
    for e in plan.LTHR_HISTORY[1:]
])


def lthr_rules(y_field: str | None = None):
    """Vertical rule + label at each LTHR change."""
    if LTHR_MARKS.empty:
        return []
    rule = alt.Chart(LTHR_MARKS).mark_rule(color="#4a3aa7", strokeWidth=1.5,
                                           strokeDash=[4, 3]).encode(
        x="d:T", tooltip=["label:N"])
    text = alt.Chart(LTHR_MARKS).mark_text(align="left", dx=4, dy=-6, fontSize=10,
                                           color="#4a3aa7", fontWeight=600).encode(
        x="d:T", y=alt.value(8), text="label:N")
    return [rule, text]


if "runs" not in st.session_state:
    _df, _src = storage.load_runs()
    st.session_state["runs"] = _df
    st.session_state["runs_source"] = _src

TODAY = plan.today()          # Singapore local date, not the server's UTC date
CUR = plan.display_phase(TODAY)
DAYS_TO_RACE = (plan.RACE_DATE - TODAY).days
runs = enrich(st.session_state["runs"])
running = runs[runs["is_run"]] if not runs.empty else runs

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🏃 Road to Sub-3:50")
    _pr = next((p for p in plan.PROFILE["personal_records"] if p.get("current")), {})
    st.caption(f"Plan v3 · {plan.DEVICE} · HM PR {_pr.get('time', '—')}")
    st.metric("Days to race", DAYS_TO_RACE if DAYS_TO_RACE >= 0 else "🏅 done",
              help=plan.RACE_DATE.strftime("%A, %d %B %Y"))
    wk = plan.phase_week(CUR, TODAY)
    if wk == 0:
        wk_label = f"starts {date.fromisoformat(CUR['start']):%a %d %b}"
    elif CUR.get("weeks"):
        wk_label = f"Week {wk}/{CUR['weeks']}"
    else:
        wk_label = CUR["status"]
    st.metric("Current phase", CUR["name"].split(" - ")[0], delta=wk_label, delta_color="off")
    st.divider()
    goal_key = st.radio("Race goal", list(plan.GOALS),
                        format_func=lambda k: f"{plan.GOALS[k]['label']} ({plan.GOALS[k]['pace']}) · {plan.GOALS[k]['kind']}",
                        help="Decision gate at the tune-up HM (3–4 Oct): " + CUR.get("tune_up", {}).get(
                            "decision_rule", "sub-1:52 hold 3:50 | sub-1:48 open 3:40 | sub-1:46 chase 3:35"))
    if plan.ZONES_PROVISIONAL:
        st.warning("HR zones are PROVISIONAL — confirm via the 30-min LTHR field test (Phase 2, week 1).")
    else:
        st.success(f"**LTHR {plan.LTHR_CURRENT}** · Z2 {plan.Z2[0]}–{plan.Z2[1]} bpm"
                   + (f"\n\nThreshold pace **{plan.THRESHOLD_PACE['pace']}/km**"
                      if plan.THRESHOLD_PACE.get("pace") else ""))
        st.caption(f"Measured {plan.THRESHOLD_PACE.get('measured_on', '—')} by field test")
    st.divider()
    SYNCED = st.session_state["runs_source"].startswith("GitHub")
    if SYNCED:
        st.success(f"Run log: {st.session_state['runs_source']}")
    else:
        st.error("⚠️ Run log NOT saved — new runs are lost on restart")
    st.caption("Screenshot parsing: " + ("✅ enabled" if run_parser.available() else "❌ add ANTHROPIC_API_KEY"))
    if st.button("↻ Reload data"):
        _df, _src = storage.load_runs()
        st.session_state["runs"] = _df
        st.session_state["runs_source"] = _src
        st.rerun()

if not SYNCED:
    st.error(
        "### ⚠️ Runs you log here are **not being saved**\n"
        "This app has no `GITHUB_TOKEN` secret, so the run log lives in temporary storage that is "
        "wiped every time the app restarts or redeploys — anything logged since the last restart is "
        "already gone.\n\n"
        "**Fix it:** *Manage app → Settings → Secrets*, add a fine-grained GitHub token with "
        "**Contents: Read and write** on this repo:\n"
        "```toml\nGITHUB_TOKEN = \"github_pat_...\"\n"
        "GITHUB_REPO = \"dnhoswork-ui/Marathon-Training\"\nGITHUB_BRANCH = \"main\"\n```\n"
        "**Until then:** press **⬇ Download runs.csv** on the Log runs tab after every session, and "
        "use **Restore from backup** on the same tab to load it back.")

tab_over, tab_log, tab_prog, tab_plan, tab_race = st.tabs(
    ["📍 Overview", "➕ Log runs", "📈 Progress", "🗓 Training plan", "🏁 Race day"])

# ---------------------------------------------------------------- overview
with tab_over:
    this_week = running[running["week"] == week_monday(TODAY)] if not running.empty else running
    week_km = float(this_week["distance_km"].sum()) if not this_week.empty else 0.0
    band = plan.weekly_band(week_monday(TODAY))
    nlr = plan.next_long_run(TODAY)

    c = st.columns(5)
    c[0].metric("This week", f"{week_km:.1f} km",
                delta=f"target {band[0]:.0f}–{band[1]:.0f} km" if band else "no target", delta_color="off")
    c[1].metric("Next long run",
                f"{nlr['km']} km" if nlr else "—",
                delta=(f"{date.fromisoformat(nlr['date']):%a %d %b}"
                       + (f" · {nlr['type'].replace('_', ' ')}" if nlr.get("type") else "")) if nlr else "",
                delta_color="off")
    longest = float(running["distance_km"].max()) if not running.empty else 0
    c[2].metric("Longest run", f"{longest:.1f} km")
    total_km = float(running["distance_km"].sum()) if not running.empty else 0
    c[3].metric("Total logged", f"{total_km:.0f} km", delta=f"{len(running)} runs", delta_color="off")
    c[4].metric("Z2 (train to)", f"{plan.Z2_TRAIN[0]}–{plan.Z2_TRAIN[1]}",
                delta=f"full Z2 {plan.Z2[0]}–{plan.Z2[1]} bpm", delta_color="off")

    # ---- phase timeline with today marker (feature 1)
    tl = pd.DataFrame([
        {"phase": p["name"].split(" - ")[0], "start": p["start"], "end": p["end"],
         "status": p["status"], "order": i,
         "detail": f"{p['start']} → {p['end']}" + (f" · {p['weekly_km'][0]}–{p['weekly_km'][1]} km/wk" if p.get("weekly_km") else "")}
        for i, p in enumerate(plan.PHASES)
    ])
    bars = alt.Chart(tl).mark_bar(height=18, cornerRadius=4).encode(
        x=alt.X("start:T", title=None, axis=AXIS),
        x2="end:T",
        y=alt.Y("phase:N", sort=alt.SortField("order"), title=None, axis=AXIS),
        color=alt.Color("status:N", legend=None,
                        scale=alt.Scale(domain=["complete", "current", "upcoming"],
                                        range=[C_BAND, C_OUT, C_GRID])),
        tooltip=["phase:N", "detail:N", "status:N"],
    )
    today_rule = alt.Chart(pd.DataFrame({"d": [str(TODAY)]})).mark_rule(
        color=C_CRIT, strokeWidth=2).encode(x="d:T", tooltip=alt.value("today"))
    race_pt = alt.Chart(pd.DataFrame({"d": [str(plan.RACE_DATE)], "phase": ["Taper"]})).mark_point(
        shape="diamond", size=120, color=C_CRIT, filled=True).encode(
        x="d:T", y="phase:N", tooltip=alt.value("Race day — 8 Dec"))
    st.altair_chart((bars + today_rule + race_pt).properties(height=150).configure_view(strokeWidth=0),
                    use_container_width=True)
    st.caption("🟦 current phase · red line = today · ◆ race day 8 Dec")

    col1, col2 = st.columns([3, 2])
    with col1:
        head = CUR["name"] if CUR["id"] == "taper" else f"Phase {CUR['id'][-1]}: {CUR['name']}"
        st.subheader(head + (f" — starts {date.fromisoformat(CUR['start']):%A %d %b}" if wk == 0
                             else f" — week {wk}"))
        w1 = CUR.get("week_1_special")
        if isinstance(w1, dict) and w1.get("status") == "COMPLETE":
            st.success(f"✅ **Week 1 field test complete** ({w1['completed_on']}) — {w1['result']}. "
                       "Zones below are measured, not estimated.")
        elif w1 and wk <= 1 and CUR["id"] == "phase2":
            st.error("🧪 **Week 1:** " + (w1["description"] if isinstance(w1, dict) else w1))
        tmpl = CUR.get("weekly_template")
        if tmpl:
            days = pd.DataFrame({"Day": list(tmpl), "Session": list(tmpl.values())})
            days["Today"] = ["👉" if TODAY.strftime("%a") == d else "" for d in days["Day"]]
            st.dataframe(days[["Today", "Day", "Session"]], hide_index=True, use_container_width=True)

        for name, detail in CUR.get("key_sessions", {}).items():
            if isinstance(detail, str):
                st.markdown(f"- **{name.replace('_', ' ').title()}**: {detail}")
                continue
            bits = [detail.get("description", "")]
            if detail.get("pace_outdoor"):
                po, pt = detail["pace_outdoor"], detail.get("pace_treadmill", {})
                bits.append(f"Outdoor **{po['start']} → {po['end']}/km**"
                            + (f" (treadmill {pt['start']} → {pt['end']})" if pt else ""))
            if detail.get("target_hr_bpm"):
                lo, hi = detail["target_hr_bpm"]
                bits.append(f"HR **{lo}–{hi} bpm**")
            st.markdown(f"- **{name.replace('_', ' ').title()}**: " + " · ".join(b for b in bits if b))
            if detail.get("note"):
                st.caption("   " + detail["note"])
            if detail.get("supersedes"):
                st.caption(f"   Revised after the field test — was {detail['supersedes']}")
    with col2:
        st.subheader("Exit criteria")
        for cr in CUR.get("exit_criteria", []):
            st.markdown(f"⬜ {cr}")
        st.subheader("Golden rules")
        for r in plan.GOLDEN_RULES:
            st.markdown(f"- {r}")

# ---------------------------------------------------------------- log runs
with tab_log:
    left, right = st.columns(2)
    with left:
        st.subheader("📷 From a screenshot")
        if run_parser.available():
            shot = st.file_uploader("Garmin/Strava screenshot", type=["png", "jpg", "jpeg", "webp"])
            if shot and st.button("Extract run data", type="primary"):
                with st.spinner("Reading the screenshot with Claude…"):
                    try:
                        parsed = run_parser.parse_screenshot(shot.getvalue(), shot.name)
                        st.session_state["prefill"] = parsed.model_dump()
                        st.success("Extracted — review and save in the form →")
                    except Exception as e:
                        st.error(f"Couldn't parse the screenshot: {e}")
            if st.session_state.get("prefill"):
                st.json({k: v for k, v in st.session_state["prefill"].items() if v is not None})
        else:
            st.info("Add an **ANTHROPIC_API_KEY** secret to enable screenshot parsing; manual entry always works.")

    with right:
        st.subheader("✍️ Add a run")
        pre = st.session_state.get("prefill") or {}
        try:
            pre_date = date.fromisoformat(pre["date"]) if pre.get("date") else TODAY
        except ValueError:
            pre_date = TODAY
        with st.form("add_run", clear_on_submit=True):
            r0 = st.columns([2, 1])
            f_date = r0[0].date_input("Date", value=pre_date)
            f_start = r0[1].text_input("Start time", placeholder="06:30",
                                       help="Matters in Singapore — heat arrives ~07:15–07:30")
            r1 = st.columns(2)
            f_type = r1[0].selectbox("Type", plan.RUN_TYPES)
            f_surface = r1[1].selectbox("Surface", plan.SURFACES)
            r2 = st.columns(2)
            f_dist = r2[0].number_input("Distance (km)", 0.0, 60.0, float(pre.get("distance_km") or 0.0), 0.01)
            f_dur = r2[1].text_input("Duration (H:MM:SS)", value=pre.get("duration") or "")
            r3 = st.columns(3)
            f_hr = r3[0].number_input("Avg HR", 0, 220, int(pre.get("avg_hr") or 0))
            f_maxhr = r3[1].number_input("Max HR", 0, 220, int(pre.get("max_hr") or 0))
            f_feels = r3[2].number_input("Feels-like °C", 0.0, 50.0, float(pre.get("feels_like_c") or 0.0), 0.5)
            r4 = st.columns(3)
            f_cad = r4[0].number_input("Cadence (spm)", 0, 250, int(pre.get("cadence_spm") or 0))
            f_vo = r4[1].number_input("Vert. osc (cm)", 0.0, 15.0, float(pre.get("vertical_osc_cm") or 0.0), 0.1)
            f_gct = r4[2].number_input("GCT (ms)", 0, 400, int(pre.get("gct_ms") or 0))
            r5 = st.columns(3)
            f_stride = r5[0].number_input("Stride length (m)", 0.0, 2.0,
                                          float(pre.get("stride_length_m") or 0.0), 0.01)
            f_power = r5[1].number_input("Avg power (W)", 0, 600, int(pre.get("avg_power_w") or 0))
            f_shoe = r5[2].selectbox("Shoe", [""] + plan.SHOE_NAMES + ["Other"])
            r6 = st.columns(4)
            f_feel = r6[0].selectbox("Feel", ["", "Strong", "Normal", "Weak"])
            f_rpe = r6[1].selectbox("Perceived effort", [""] + [f"{n}/10" for n in range(1, 11)])
            f_grade = r6[2].selectbox("Grade", plan.GRADES)
            f_hr1 = r6[3].number_input("HR 1st half", 0, 220, 0,
                                       help="With HR 2nd half below, powers cardiac-drift tracking")
            f_hr2 = st.number_input("HR 2nd half", 0, 220, 0)
            f_notes = st.text_input("Notes", value=pre.get("run_title") or "")
            if st.form_submit_button("Save run", type="primary"):
                mins = duration_to_min(f_dur)
                pace_s = int(mins * 60 / f_dist) if (mins and f_dist > 0) else None
                p = plan.phase_of(f_date)
                row = {
                    "date": f_date, "start_time": f_start.strip() or None, "date_precision": "exact",
                    "phase": p["id"] if p else "", "run_type": f_type, "surface": f_surface,
                    "distance_km": round(f_dist, 2) or None, "duration": f_dur.strip() or None,
                    "avg_pace": fmt_pace(pace_s) if pace_s else None, "pace_sec_per_km": pace_s,
                    "avg_hr": f_hr or None, "max_hr": f_maxhr or None,
                    "cadence_spm": f_cad or None, "stride_length_m": f_stride or None,
                    "vertical_osc_cm": f_vo or None, "gct_ms": f_gct or None,
                    "avg_power_w": f_power or None,
                    "feel": f_feel or None, "perceived_effort": f_rpe or None,
                    "grade": f_grade or None,
                    "grade_points": plan.GPA_MAP.get(f_grade) if f_grade else None,
                    "shoe": f_shoe or None, "feels_like_c": f_feels or None,
                    "hr_first_half": f_hr1 or None, "hr_second_half": f_hr2 or None,
                    "notes": f_notes.strip() or None,
                }
                new = pd.concat([st.session_state["runs"], pd.DataFrame([row])], ignore_index=True)
                ok, msg = storage.save_runs(new)
                st.session_state["runs"] = storage.load_runs()[0] if ok else new
                st.session_state.pop("prefill", None)
                (st.success if ok else st.error)(msg)
                if ok and not SYNCED:
                    st.session_state["nag_backup"] = True
                st.rerun()
    if st.session_state.pop("nag_backup", False):
        st.warning("Run saved — but GitHub sync is off, so **download the CSV below now** or this run "
                   "disappears when the app restarts.")

    st.divider()
    st.subheader("Run log")
    st.caption("Edit cells or delete rows, then **Save changes** — each save is a commit when GitHub sync is on.")
    edited = st.data_editor(
        st.session_state["runs"], num_rows="dynamic", hide_index=True, use_container_width=True,
        column_config={
            "date": st.column_config.DateColumn("date", required=True),
            "run_type": st.column_config.SelectboxColumn("run_type", options=plan.RUN_TYPES),
            "surface": st.column_config.SelectboxColumn("surface", options=plan.SURFACES),
            "grade": st.column_config.SelectboxColumn("grade", options=plan.GRADES[1:]),
            "distance_km": st.column_config.NumberColumn("distance_km", format="%.2f"),
        },
        key="log_editor")
    c1, c2 = st.columns([1, 3])
    if c1.button("💾 Save changes"):
        ok, msg = storage.save_runs(edited)
        st.session_state["runs"] = storage.load_runs()[0] if ok else edited
        (st.success if ok else st.error)(msg)
        st.rerun()
    c2.download_button("⬇ Download runs.csv", st.session_state["runs"].to_csv(index=False),
                       "runs.csv", "text/csv",
                       type="secondary" if SYNCED else "primary",
                       help="Your backup. Essential while GitHub sync is off — the app's own copy is temporary.")

    with st.expander("♻️ Restore from a backup CSV"):
        st.caption("Upload a `runs.csv` you downloaded earlier. Runs are **merged** with what's already "
                   "here — identical rows (same date, type and distance) are not duplicated.")
        up = st.file_uploader("runs.csv backup", type=["csv"], label_visibility="collapsed")
        if up is not None:
            try:
                incoming = pd.read_csv(up)
                incoming["date"] = pd.to_datetime(incoming["date"], errors="coerce").dt.date
                st.write(f"Backup contains **{len(incoming)} rows**, "
                         f"{incoming['date'].min()} → {incoming['date'].max()}.")
                if st.button("Merge into run log", type="primary"):
                    merged = pd.concat([st.session_state["runs"], incoming], ignore_index=True)
                    before = len(merged)
                    merged = merged.drop_duplicates(subset=["date", "run_type", "distance_km"],
                                                    keep="last")
                    ok, msg = storage.save_runs(merged)
                    st.session_state["runs"] = storage.load_runs()[0] if ok else merged
                    st.success(f"Merged — {len(merged)} runs total "
                               f"({before - len(merged)} duplicates skipped). {msg}")
                    st.rerun()
            except Exception as e:
                st.error(f"Couldn't read that CSV: {e}")

# ---------------------------------------------------------------- progress
with tab_prog:
    if running.empty:
        st.info("No runs logged yet — add one in the **Log runs** tab and this fills in.")
    else:
        # ---- data status: did my upload land? ------------------------------
        last_date = running["date"].max()
        days_since = (TODAY - last_date).days
        last7 = running[running["date"] > TODAY - timedelta(days=7)]
        last28 = running[running["date"] > TODAY - timedelta(days=28)]
        src = st.session_state["runs_source"]
        synced = src.startswith("GitHub")

        s = st.columns(5)
        s[0].metric("Runs logged", f"{len(running)}")
        if days_since < 0:
            recency = f"dated {-days_since}d ahead"
        elif days_since == 0:
            recency = "today"
        elif days_since == 1:
            recency = "yesterday"
        else:
            recency = f"{days_since} days ago"
        s[1].metric("Most recent run", f"{last_date:%d %b}", delta=recency, delta_color="off")
        s[2].metric("Last 7 days", f"{last7['distance_km'].sum():.1f} km",
                    delta=f"{len(last7)} runs", delta_color="off")
        s[3].metric("Last 28 days", f"{last28['distance_km'].sum():.0f} km",
                    delta=f"{len(last28)} runs", delta_color="off")
        s[4].metric("Saved to", "GitHub ✅" if synced else "Local ⚠️",
                    delta=src.replace("GitHub · ", ""), delta_color="off")

        if not synced:
            st.warning("**Runs are only in this app's temporary storage** — they'll vanish when the app "
                       "restarts. Add the `GITHUB_TOKEN` secret to commit every run to the repo.")

        # feel far below RPE — may mean the HR reading was fatigue-elevated, not effort-driven
        odd = running[(running["feel"].astype(str).str.lower().isin(["very_weak", "weak"]))
                      & (running["perceived_effort"].astype(str).str.extract(r"(\d+)")[0]
                         .astype(float) <= 5)]
        if not odd.empty:
            latest = odd.sort_values("date").iloc[-1]
            st.warning(f"🩺 **Feel/effort mismatch** on {latest['date']:%d %b} "
                       f"({latest['run_type']}): felt *{latest['feel']}* at only "
                       f"{latest['perceived_effort']}. {len(odd)} such run(s) logged. If this recurs, "
                       "an HR reading may be elevated by fatigue or illness rather than effort — "
                       "worth a retest before trusting zones set from it.")

        # grey-zone leakage: only meaningful on easy-intent runs
        grey = running[running["grey_zone"]]
        if not grey.empty:
            g = grey.sort_values("date").iloc[-1]
            st.warning(f"⚠️ **Grey-zone leakage** on {g['date']:%d %b} ({g['run_type']}): "
                       f"{g['z3_pct']:.0f}% of the run in Z3 on an easy-intent session. "
                       f"{len(grey)} such run(s). Easy runs should sit in Z2 — Z3 costs recovery "
                       "without the adaptation of a real tempo. (Long, tempo and race sessions are "
                       "exempt: there Z3 is marathon specificity, not leakage.)")

        # only meaningful from the point time-in-zone started being captured —
        # earlier runs never had it and flagging them all is noise
        zone_era = running.loc[running["zones_known"], "date"].min() if running["zones_known"].any() else None
        if zone_era is not None:
            no_zones = running[(running["date"] >= zone_era) & ~running["zones_known"]
                               & running["avg_hr"].notna()]
            if not no_zones.empty:
                dates = ", ".join(f"{d:%d %b}" for d in sorted(no_zones["date"]))
                st.info(f"🔍 **{len(no_zones)} run(s) since {zone_era:%d %b} have no time-in-zone "
                        f"data** ({dates}). Their zone classification is inferred from average HR "
                        "alone — low-confidence, not a measured distribution. Backfill from Garmin "
                        "if it matters. (Runs before "
                        f"{zone_era:%d %b} never captured it and aren't counted here.)")

        future = running[running["date"] > TODAY]
        if not future.empty:
            st.info(f"📅 {len(future)} run(s) are dated **after today ({TODAY:%d %b}, Singapore time)** — "
                    f"latest is {future['date'].max():%d %b}. They're included in totals, but check the "
                    "dates are right: a wrong date puts a run in the wrong training week.")

        with st.expander(f"🔍 Check your latest uploads — newest {min(8, len(running))} runs",
                         expanded=days_since <= 2):
            recent = running.sort_values("date", ascending=False).head(8).copy()
            recent["pace"] = recent["pace_sec_per_km"].map(fmt_pace)
            st.dataframe(
                recent[["date", "run_type", "surface", "distance_km", "pace", "avg_hr",
                        "feels_like_c", "grade", "notes"]],
                hide_index=True, use_container_width=True,
                column_config={"distance_km": st.column_config.NumberColumn("km", format="%.2f"),
                               "feels_like_c": st.column_config.NumberColumn("feels °C", format="%.0f")})
            st.caption("If a run you just logged isn't here, it didn't save — check the message on the "
                       "Log runs tab, then press **↻ Reload data** in the sidebar.")

        st.divider()

        # ---- controls -----------------------------------------------------
        ctl = st.columns([2, 2, 3])
        heat_on = ctl[0].toggle(
            "🌡 Heat-adjust paces",
            help=f"Subtracts ~{plan.HEAT_S_PER_KM_PER_C:g} s/km per °C of feels-like above "
                 f"{plan.HEAT_THRESHOLD_C:g}°C, where logged. Profile heat model: "
                 f"+{plan.ENVIRONMENT['pace_penalty_sec_per_km'][0]}–"
                 f"{plan.ENVIRONMENT['pace_penalty_sec_per_km'][1]} s/km and "
                 f"+{plan.HEAT_HR_PENALTY[0]}–{plan.HEAT_HR_PENALTY[1]} bpm above the threshold.")
        ma_n = ctl[1].selectbox("Moving average", [3, 5, 7], index=0,
                                format_func=lambda n: f"{n}-run MA")
        surf_pick = ctl[2].radio("Surface", ["Outdoor + mixed", "All surfaces"],
                                 horizontal=True,
                                 help="Treadmill runs are ~15–20 s/km easier than outdoor Singapore, "
                                      "so they never belong in a pace trend. Mixed/gravel routes cost "
                                      "10–20 s/km at equal effort — they are kept, but as their own "
                                      "series, never averaged into the road line.")
        tod_pick = st.multiselect(
            "Time of day", plan.TIMES_OF_DAY, default=plan.TIMES_OF_DAY,
            help="Singapore mornings and evenings are different thermal environments — comparing a "
                 "17:12 run against an 06:01 run produces a false fitness signal.")

        R = heat_adjusted(running, heat_on)
        pool = trend_pool(R)
        if surf_pick == "Outdoor + mixed":
            pool = pool[pool["surface"].isin(["outdoor", "mixed"])]
        if set(tod_pick) != set(plan.TIMES_OF_DAY):
            pool = pool[pool["time_of_day"].isin(tod_pick)]
            st.caption(f"Filtered to **{', '.join(tod_pick) or 'nothing'}** starts — "
                       f"{len(pool)} of {len(trend_pool(R))} trend-eligible runs.")

        def add_ef(d: pd.DataFrame) -> pd.DataFrame:
            d = d.dropna(subset=["pace_adj", "avg_hr"]).sort_values("date").copy()
            d["EF"] = (1000 / d["pace_adj"] * 60) / d["avg_hr"]
            d["EF_ma"] = d.groupby("surface")["EF"].transform(
                lambda x: x.rolling(ma_n, min_periods=1).mean())
            d["pace_ma"] = d.groupby("surface")["pace_adj"].transform(
                lambda x: x.rolling(ma_n, min_periods=1).mean())
            d["hr_ma"] = d.groupby("surface")["avg_hr"].transform(
                lambda x: x.rolling(ma_n, min_periods=1).mean())
            return d

        # the LTHR test is excluded from EF by flag: it started cold (HR 80 at t=0),
        # so whole-run EF isn't comparable to steady Z2 sessions
        aer = add_ef(pool[pool["run_type"].isin(["easy", "long"]) & pool["include_in_ef_trend"]])
        ef_excluded = int((~running["include_in_ef_trend"]).sum())

        # ---- improvement scorecard ---------------------------------------
        st.subheader("Am I improving?")
        st.caption(f"Comparing your **last {ma_n} outdoor easy/long runs** with the {ma_n} before them. "
                   "Outdoor-only so heat and surface don't fake a trend"
                   + (" · heat-adjusted" if heat_on else "") + ".")
        out = aer[aer["surface"] == "outdoor"]
        if len(out) >= ma_n * 2:
            now, prev = out.tail(ma_n), out.tail(ma_n * 2).head(ma_n)
            m = st.columns(4)
            ef_d = now["EF"].mean() - prev["EF"].mean()
            m[0].metric("Efficiency Factor", f"{now['EF'].mean():.3f}",
                        delta=f"{ef_d:+.3f} m/min per bpm",
                        help="Speed per heartbeat. The cleanest fitness signal — it rises when you get "
                             "faster at the same HR, or hold the same pace at a lower HR.")
            pace_d = now["pace_adj"].mean() - prev["pace_adj"].mean()
            m[1].metric("Z2 pace", f"{fmt_pace(now['pace_adj'].mean())}/km",
                        delta=f"{pace_d:+.0f} s/km", delta_color="inverse")
            hr_d = now["avg_hr"].mean() - prev["avg_hr"].mean()
            m[2].metric("Avg HR on those runs", f"{now['avg_hr'].mean():.0f} bpm",
                        delta=f"{hr_d:+.0f} bpm", delta_color="inverse")
            gap = now["pace_adj"].mean() - 372.5  # 6:12/km midpoint of the 6:10–6:15 goal
            m[3].metric("Gap to 6:10–6:15 goal", f"{gap:+.0f} s/km",
                        delta="on target ✅" if gap <= 3 else "keep building", delta_color="off")
            st.caption("↑ EF is good; ↓ pace and ↓ HR are good (green either way). "
                       "The goal band is the plan's outdoor Z2 target of 6:10–6:15/km.")
        else:
            st.info(f"Need at least {ma_n * 2} outdoor easy/long runs to compare windows — "
                    f"you have {len(out)}. Log a few more and this fills in.")

        st.divider()

        # ---- efficiency factor: raw + MA, newest ringed -------------------
        st.subheader("Efficiency Factor — the real fitness trend")
        if aer.empty:
            st.info("Log pace + avg HR on easy/long runs to build this trend.")
        else:
            newest = aer.sort_values("date").tail(1)
            multi_surf = aer["surface"].nunique() > 1
            ef_legend = alt.Legend(orient="top", title=None) if multi_surf else None
            ef_surf = surf_scale(aer)
            # padded so the ringed newest run and its label aren't clipped at the edge
            ef_x = alt.X("date:T", title=None, axis=AXIS, scale=alt.Scale(padding=34))
            raw = alt.Chart(aer).mark_point(size=45, opacity=0.35, filled=True).encode(
                ef_x,
                y=alt.Y("EF:Q", title="m/min per bpm",
                        scale=alt.Scale(zero=False, padding=16), axis=AXIS),
                color=alt.Color("surface:N", scale=ef_surf, legend=ef_legend),
                tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("run_type:N", title="Type"),
                         alt.Tooltip("surface:N"), alt.Tooltip("EF:Q", title="EF", format=".3f"),
                         alt.Tooltip("avg_pace:N", title="pace"), alt.Tooltip("avg_hr:Q", title="HR"),
                         alt.Tooltip("distance_km:Q", title="km", format=".1f")])
            # straight segments, not a spline: splines undershoot at the series edge,
            # which dragged the endpoint below every point it was averaging
            line = alt.Chart(aer).mark_line(strokeWidth=2.5).encode(
                ef_x, y="EF_ma:Q",
                color=alt.Color("surface:N", scale=ef_surf, legend=None),
                tooltip=[alt.Tooltip("date:T"), alt.Tooltip("EF_ma:Q", title=f"{ma_n}-run MA", format=".3f")])
            ring = alt.Chart(newest).mark_point(size=180, filled=False, strokeWidth=2.5,
                                                color=C_CRIT).encode(ef_x, y="EF:Q")
            tag = alt.Chart(newest).mark_text(dy=-20, dx=-14, align="right", fontSize=11,
                                              fontWeight=600, color=C_CRIT).encode(
                ef_x, y="EF:Q", text=alt.value("latest run"))
            st.altair_chart(alt.layer(raw, line, ring, tag, *lthr_rules()).properties(height=300)
                            .configure_view(strokeWidth=0), use_container_width=True)
            st.caption(f"Faint dots = individual runs · bold line = {ma_n}-run moving average · "
                       "🔴 ring = your most recently logged run. **Up and to the right is fitness.** "
                       "Lines never cross surfaces — each is its own series. **Mixed (≈50% gravel) "
                       "is plotted separately on purpose:** gravel costs 10–20 s/km at equal effort, "
                       "so EF is understated on those runs and averaging them into the road line "
                       "would fake a decline. EF is speed ÷ HR, so the LTHR rebase does not affect it."
                       + (f" {ef_excluded} run(s) excluded by flag (field test)." if ef_excluded else ""))

        # ---- watts per bpm: a fatigue detector, not a fitness trend ----------
        # W/bpm scales with intensity, so a long multi-zone trend line is noise.
        # Its one real strength is short-window, same-intensity comparison.
        st.subheader("Fatigue watch — watts per heartbeat")
        fw_days = st.slider("Window (days)", 7, 42, plan.FATIGUE_WINDOW_DAYS, step=7,
                            help="Short by design. This is a same-intensity comparison, not a "
                                 "fitness trend — widen it only to see whether a flag repeats.")
        wb = fatigue_pool(R, fw_days)
        if len(wb) < 2:
            st.info(f"Need two qualifying Z2 runs in the last {fw_days} days to compare — "
                    f"you have {len(wb)}. Qualifying means outdoor or mixed, Z2, with avg power "
                    "logged.")
        else:
            drop = plan.FATIGUE_DROP_PCT
            # generous padding: the first and last points sit on the window edges,
            # and the flagged points carry a label below the mark
            base = alt.Chart(wb).encode(
                x=alt.X("date:T", title=None, axis=AXIS, scale=alt.Scale(padding=30)),
                y=alt.Y("watts_per_bpm:Q", title="W per bpm", axis=AXIS,
                        scale=alt.Scale(zero=False, nice=False, padding=34)))
            tips = [alt.Tooltip("date:T", title="Date"), alt.Tooltip("run_type:N", title="Type"),
                    alt.Tooltip("surface:N"), alt.Tooltip("avg_power_w:Q", title="power (W)"),
                    alt.Tooltip("avg_hr:Q", title="HR"),
                    alt.Tooltip("watts_per_bpm:Q", title="W/bpm", format=".3f"),
                    alt.Tooltip("wbpm_delta_pct:Q", title="vs previous", format="+.1f"),
                    alt.Tooltip("feel:N")]
            w_line = base.mark_line(color=C_MUTED, strokeWidth=2).encode(order="date:T")
            w_ok = base.transform_filter(alt.datum.fatigue_flag == False).mark_point(
                size=90, filled=True, color=C_OUT, stroke="white", strokeWidth=2).encode(tooltip=tips)
            w_bad = base.transform_filter(alt.datum.fatigue_flag).mark_point(
                size=150, filled=True, color=C_CRIT, stroke="white", strokeWidth=2,
                shape="triangle-down").encode(tooltip=tips)
            w_tag = base.transform_filter(alt.datum.fatigue_flag).mark_text(
                dy=18, fontSize=11, fontWeight=600, color=C_CRIT).encode(
                text=alt.Text("wbpm_delta_pct:Q", format="+.1f"))
            st.altair_chart(alt.layer(w_line, w_ok, w_bad, w_tag).properties(height=250)
                            .configure_view(strokeWidth=0), use_container_width=True)
            st.caption(f"Work done per heartbeat, **Z2 runs only** — mixing a tempo into this makes "
                       "it unreadable. Power is indifferent to terrain and heat, which makes a sudden "
                       "drop the earliest fatigue signal available: it caught the 2 Aug decoupling "
                       f"(−4.5% in 24 h) before pace, HR or feel did. 🔻 = a drop of more than {drop}% "
                       "against the previous qualifying run. **Treadmill is excluded** — no air "
                       "resistance, so the numbers are not comparable; the 30 Jul field test is "
                       "excluded too, since a maximal effort inflates W/bpm.")

            flagged = wb[wb["fatigue_flag"]]
            if not flagged.empty:
                last = flagged.iloc[-1]
                st.warning(f"**{last['date']:%d %b} — W/bpm down {abs(last['wbpm_delta_pct']):.1f}% "
                           f"on the previous Z2 run.** Same intensity, less work per beat. Treat the "
                           "next session as recovery unless the following run recovers the number.")

            # the actionable comparison: the two most recent qualifying runs
            st.markdown("**Last two qualifying Z2 runs**")
            pair = wb.tail(2)
            cmp_tbl = pd.DataFrame({
                "": ["previous", "latest"],
                "Date": [f"{d:%d %b}" for d in pair["date"]],
                "Surface": pair["surface"].values,
                "Power": [f"{p:.0f} W" for p in pair["avg_power_w"]],
                "HR": [f"{h:.0f}" for h in pair["avg_hr"]],
                "W/bpm": [f"{w:.3f}" for w in pair["watts_per_bpm"]],
                "Δ": ["—", f"{pair.iloc[-1]['wbpm_delta_pct']:+.1f}%"],
            })
            st.dataframe(cmp_tbl, hide_index=True, use_container_width=True)
            zi = int(wb["zone_inferred"].sum())
            if zi:
                st.caption(f"{zi} of these {len(wb)} runs had no time-in-zone recorded; "
                           "an easy/long run type was treated as Z2 so the comparison isn't "
                           "silently dropped. Log time-in-zone to remove the assumption.")

        # ---- pace trend vs target band ------------------------------------
        st.subheader("Easy/long pace vs the 6:10–6:15 outdoor target")
        pace_out = aer[aer["surface"] == "outdoor"]
        if pace_out.empty:
            st.info("No outdoor easy/long runs with pace + HR yet.")
        else:
            # descending domain puts faster paces at the top; padded to the data range
            p_lo = min(365, float(pace_out["pace_adj"].min()) - 10)
            p_hi = float(pace_out["pace_adj"].max()) + 10
            PACE_Y = alt.Scale(domain=[p_hi, p_lo])
            target = alt.Chart(pd.DataFrame({"lo": [370], "hi": [375]})).mark_rect(
                color=C_TM, opacity=0.22).encode(y=alt.Y("lo:Q", scale=PACE_Y), y2="hi:Q")
            p_raw = alt.Chart(pace_out).mark_point(size=50, opacity=0.4, filled=True, color=C_OUT).encode(
                x=alt.X("date:T", title=None, axis=AXIS),
                y=alt.Y("pace_adj:Q", title="pace (min/km)", scale=PACE_Y,
                        axis=alt.Axis(gridColor=C_GRID, labelColor=C_MUTED, titleColor=C_MUTED,
                                      labelExpr=PACE_LABEL, tickCount=7)),
                size=alt.Size("distance_km:Q", legend=None, scale=alt.Scale(range=[40, 260])),
                tooltip=[alt.Tooltip("date:T"), alt.Tooltip("avg_pace:N", title="raw pace"),
                         alt.Tooltip("pace_adj:Q", title="adj pace (s/km)", format=".0f"),
                         alt.Tooltip("avg_hr:Q", title="HR"),
                         alt.Tooltip("feels_like_c:Q", title="feels °C"),
                         alt.Tooltip("distance_km:Q", title="km", format=".1f")])
            p_line = alt.Chart(pace_out).mark_line(strokeWidth=2.5, color=C_OUT,
                                                   interpolate="monotone").encode(
                x="date:T", y=alt.Y("pace_ma:Q", scale=PACE_Y))
            p_ring = alt.Chart(pace_out.sort_values("date").tail(1)).mark_point(
                size=180, filled=False, strokeWidth=2.5, color=C_CRIT).encode(
                x="date:T", y=alt.Y("pace_adj:Q", scale=PACE_Y))
            st.altair_chart((target + p_raw + p_line + p_ring).properties(height=280)
                            .configure_view(strokeWidth=0), use_container_width=True)
            st.caption("Green band = the plan's outdoor Z2 goal (6:10–6:15/km). Axis is flipped so "
                       "**faster is higher** — the line should climb toward the band. Dot size = distance"
                       + (" · heat-adjusted paces" if heat_on else
                          " · turn on heat-adjust above to strip out Singapore's temperature penalty") + ".")

        # ---- aerobic curve, small multiples by surface ---------------------
        st.subheader("The aerobic curve — is it shifting left?")
        sc = pool.dropna(subset=["pace_adj", "pct_lthr"])
        if sc.empty:
            st.info("No runs with both pace and HR yet.")
        else:
            lo_pct, hi_pct = plan.Z2_PCT
            surfaces = [s for s in plan.SURFACES if not sc[sc["surface"] == s].empty]
            pcols = st.columns(len(surfaces))
            for pcol, surf in zip(pcols, surfaces):
                d = sc[sc["surface"] == surf]
                y_dom = [min(70, float(d["pct_lthr"].min()) - 2), max(100, float(d["pct_lthr"].max()) + 2)]
                z2band = alt.Chart(pd.DataFrame({"lo": [lo_pct], "hi": [hi_pct]})).mark_rect(
                    color=C_OUT, opacity=0.08).encode(
                    y=alt.Y("lo:Q", scale=alt.Scale(domain=y_dom)), y2="hi:Q")
                pts = alt.Chart(d).mark_point(filled=True, opacity=0.9, stroke="#ffffff",
                                              strokeWidth=1.5).encode(
                    x=alt.X("pace_adj:Q", title="pace (min/km)",
                            scale=alt.Scale(domain=[330, 530]),
                            axis=alt.Axis(gridColor=C_GRID, labelColor=C_MUTED, titleColor=C_MUTED,
                                          labelExpr=PACE_LABEL, tickCount=6)),
                    y=alt.Y("pct_lthr:Q", title="% of LTHR", scale=alt.Scale(domain=y_dom), axis=AXIS),
                    color=alt.Color("date:T", title=None,
                                    scale=alt.Scale(range=["#cde2fb", "#0d366b"]),
                                    legend=alt.Legend(orient="bottom", direction="horizontal",
                                                      gradientLength=140)),
                    size=alt.Size("distance_km:Q", legend=None, scale=alt.Scale(range=[50, 320])),
                    tooltip=[alt.Tooltip("date:T"), alt.Tooltip("run_type:N"),
                             alt.Tooltip("avg_pace:N", title="pace"),
                             alt.Tooltip("avg_hr:Q", title="HR (bpm)"),
                             alt.Tooltip("lthr_then:Q", title="LTHR then"),
                             alt.Tooltip("pct_lthr:Q", title="% LTHR", format=".1f"),
                             alt.Tooltip("zone:N", title="zone that day"),
                             alt.Tooltip("distance_km:Q", title="km", format=".1f"),
                             alt.Tooltip("grade:N")])
                with pcol:
                    st.markdown(f"**{surf.title()}** — {len(d)} runs")
                    st.altair_chart((z2band + pts).properties(height=260)
                                    .configure_view(strokeWidth=0), use_container_width=True)
            st.caption(f"Y axis is **HR as % of the LTHR in force that day**, so the {lo_pct}–{hi_pct}% "
                       "Zone 2 band reads correctly on both sides of the 30 Jul rebase (173 → 176) — a "
                       "fixed bpm band would mis-shade every run before then. Raw bpm is in the tooltip. "
                       "Pale dots are older runs, dark dots recent; improving fitness moves the dark dots "
                       "left at the same height.")

        st.divider()

        # ---- plan adherence: prescribed vs delivered ----------------------
        pres = R[R["prescribed_type"].notna() & (R["prescribed_type"] != "")].sort_values("date")
        if not pres.empty:
            st.subheader("Plan adherence — prescribed vs delivered")
            dev = pres[pres["adherence_flag"]]
            a = st.columns(4)
            a[0].metric("Sessions prescribed", len(pres))
            a[1].metric("Deviations", len(dev),
                        delta=f"{len(dev) / len(pres) * 100:.0f}% of sessions",
                        delta_color="off")
            over = pres[(pres["prescribed_distance_km"].notna())
                        & (pres["distance_km"] > pres["prescribed_distance_km"])]
            a[2].metric("Ran longer than prescribed", len(over))
            unsched = pres[pres["prescribed_type"] == "rest"]
            a[3].metric("Ran on a rest day", len(unsched))

            def _delivered(r):
                bits = [f"{r['distance_km']:.2f} km", r["avg_pace"]]
                if pd.notna(r["avg_hr"]):
                    bits.append(f"HR {r['avg_hr']:.0f}")
                return " · ".join(bits)

            def _prescribed(r):
                if r["prescribed_type"] == "rest":
                    return "REST"
                bits = [str(r["prescribed_type"])]
                if pd.notna(r["prescribed_duration_min"]):
                    bits.append(f"{r['prescribed_duration_min']:.0f} min")
                if pd.notna(r["prescribed_distance_km"]):
                    bits.append(f"{r['prescribed_distance_km']:.0f} km")
                if pd.notna(r["prescribed_pace"]) and str(r["prescribed_pace"]).strip():
                    bits.append(f"@ {r['prescribed_pace']}")
                if pd.notna(r["prescribed_hr_ceiling"]):
                    bits.append(f"HR ≤ {r['prescribed_hr_ceiling']:.0f}")
                return " · ".join(bits)

            tbl = pd.DataFrame({
                "": ["⚠️" if f else "✅" for f in pres["adherence_flag"]],
                "Date": [f"{d:%d %b}" for d in pres["date"]],
                "Prescribed": [_prescribed(r) for _, r in pres.iterrows()],
                "Delivered": [_delivered(r) for _, r in pres.iterrows()],
                "Note": pres["adherence_note"].fillna("").values,
            })
            st.dataframe(tbl, hide_index=True, use_container_width=True)
            if not dev.empty:
                st.warning(f"**{len(dev)} of {len(pres)} prescribed sessions deviated.** Each is minor "
                           "on its own; the aggregate is what matters — consistently exceeding "
                           "prescription raises load above what the plan budgeted for, which is how "
                           "a good block turns into an overreaching one. The plan's progression "
                           "assumes the prescription is the ceiling, not the floor.")

        st.divider()
        st.subheader("Weekly volume vs plan band")
        wsum = R.groupby("week", as_index=False)["distance_km"].sum().rename(columns={"distance_km": "km"})
        all_weeks = pd.date_range(wsum["week"].min(), plan.RACE_DATE, freq="W-MON").date
        vol = pd.DataFrame({"week": all_weeks}).merge(wsum, on="week", how="left").fillna({"km": 0})
        bands = [plan.weekly_band(w) for w in vol["week"]]
        vol["lo"] = [b[0] if b else None for b in bands]
        vol["hi"] = [b[1] if b else None for b in bands]
        prev_km = vol["km"].shift(1)
        vol["breach"] = (prev_km > 10) & (vol["km"] > prev_km * 1.10)
        vol["ma4"] = vol["km"].rolling(4, min_periods=1).mean().where(vol["km"] > 0)

        band_area = alt.Chart(vol.dropna(subset=["lo"])).mark_area(color=C_BAND, opacity=0.25).encode(
            x=alt.X("week:T", title=None, axis=AXIS), y=alt.Y("lo:Q", title="km/week", axis=AXIS), y2="hi:Q")
        gap_df = pd.DataFrame([{"s": str(a), "e": str(b), "label": lab} for a, b, lab in plan.GAPS])
        gap_rects = alt.Chart(gap_df).mark_rect(color=C_MUTED, opacity=0.12).encode(
            x="s:T", x2="e:T", tooltip=["label:N"])
        gap_text = alt.Chart(gap_df).mark_text(dy=-95, angle=270, color=C_MUTED, fontSize=10).encode(
            x="s:T", text="label:N")
        vbars = alt.Chart(vol[vol["km"] > 0]).mark_bar(width=9, cornerRadiusTopLeft=3,
                                                       cornerRadiusTopRight=3, color=C_OUT).encode(
            x="week:T", y="km:Q",
            tooltip=[alt.Tooltip("week:T", title="Week of"), alt.Tooltip("km:Q", format=".1f"),
                     alt.Tooltip("ma4:Q", title="4-week avg", format=".1f"),
                     alt.Tooltip("lo:Q", title="Band lo", format=".0f"),
                     alt.Tooltip("hi:Q", title="Band hi", format=".0f")])
        ma4_line = alt.Chart(vol.dropna(subset=["ma4"])).mark_line(
            color="#0d366b", strokeWidth=2, interpolate="monotone").encode(x="week:T", y="ma4:Q")
        flags = alt.Chart(vol[vol["breach"]]).mark_text(text="⚠", dy=-12, fontSize=15, color=C_CRIT).encode(
            x="week:T", y="km:Q", tooltip=alt.value("More than +10% vs the previous week"))
        now_rule = alt.Chart(pd.DataFrame({"d": [str(TODAY)]})).mark_rule(
            color=C_CRIT, strokeWidth=1.5).encode(x="d:T")
        st.altair_chart((band_area + gap_rects + gap_text + vbars + ma4_line + flags + now_rule)
                        .properties(height=280).configure_view(strokeWidth=0), use_container_width=True)
        st.caption("🟦 bars = km logged that week · dark line = 4-week rolling average (the trend that "
                   "matters for adaptation) · shaded band = the phase's target range · ⚠ = 10%-rule "
                   "breach · gray blocks = illness/holiday, real gaps rather than missing data.")

        # ---- long-run ladder ----------------------------------------------
        st.subheader("Long-run ladder — planned vs actual")
        ladder = pd.DataFrame(plan.full_ladder())
        ladder["date"] = pd.to_datetime(ladder["date"])
        ladder["kind"] = ladder["type"].fillna("build") if "type" in ladder else "build"
        actual_lr = R[R["run_type"].isin(["long", "race_hm"])].copy()
        plan_line = alt.Chart(ladder).mark_line(color=C_MUTED, strokeWidth=1.5, strokeDash=[4, 3],
                                                point=alt.OverlayMarkDef(color=C_MUTED, size=45)).encode(
            x=alt.X("date:T", title=None, axis=AXIS), y=alt.Y("km:Q", title="km", axis=AXIS),
            tooltip=[alt.Tooltip("date:T", title="Planned"), alt.Tooltip("km:Q"),
                     alt.Tooltip("kind:N", title="type")])
        act_line = alt.Chart(actual_lr).mark_line(color=C_OUT, strokeWidth=2.5).encode(
            x="date:T", y="distance_km:Q")
        act_pts = alt.Chart(actual_lr).mark_point(filled=True, size=110, color=C_OUT,
                                                  stroke="#ffffff", strokeWidth=2).encode(
            x="date:T", y="distance_km:Q",
            tooltip=[alt.Tooltip("date:T"), alt.Tooltip("distance_km:Q", title="km", format=".1f"),
                     alt.Tooltip("grade:N"), alt.Tooltip("avg_hr:Q", title="avg HR"),
                     alt.Tooltip("feels_like_c:Q", title="feels °C"), alt.Tooltip("notes:N")])
        chips = alt.Chart(actual_lr.dropna(subset=["grade"])).mark_text(
            dy=-16, fontSize=10, fontWeight=600, color="#52514e").encode(
            x="date:T", y="distance_km:Q", text="grade:N")
        st.altair_chart((plan_line + act_line + act_pts + chips + now_rule).properties(height=290)
                        .configure_view(strokeWidth=0), use_container_width=True)
        st.caption("Dashed gray = the planned ladder including down weeks · 🟦 solid = your actual "
                   "long runs, labelled with the grade you gave each one. The two key runs are now "
                   "**time-capped at 3:15** — aerobic return plateaus past ~3 h while "
                   "musculoskeletal cost keeps climbing.")

        # ---- fuelling: gut training toward the race carb rate
        fuel = R[R["carbs_g_per_hour"].notna()].sort_values("date")
        if not fuel.empty:
            st.subheader("Gut training — carbs per hour on long runs")
            prog = plan.PROFILE.get("fuelling_programme", {})
            if prog:
                st.caption(f"{prog['objective']} · ladder: {prog['ladder']}")
            for _, f in fuel.tail(4).iterrows():
                tgt = f["target_g_per_hour"] or 60
                pct = min(f["carbs_g_per_hour"] / tgt, 1.0)
                cA, cB = st.columns([1, 3])
                cA.markdown(f"**{f['date']:%d %b}** · {f['distance_km']:.1f} km")
                with cB:
                    st.progress(pct, text=f"{f['carbs_g_per_hour']:.0f} of {tgt:.0f} g/h "
                                          f"({pct * 100:.0f}%) · {int(f['gels_count'])} gels"
                                          + (f" at km {f['gel_timing_km']}" if f["gel_timing_km"] else "")
                                          + (f" · caffeine at km {f['caffeine_gel_km']:.0f}"
                                             if pd.notna(f["caffeine_gel_km"]) else "")
                                          + (f" · gut: {f['gut_tolerance']}" if f["gut_tolerance"] else ""))
            st.caption("Race target is 60–90 g/h. Rate has to be trained — the gut adapts slower than "
                       "the legs, so the ladder steps up one gel per long run.")
            latest = fuel.iloc[-1]
            if pd.isna(latest["gut_tolerance"]) or not str(latest["gut_tolerance"]).strip():
                st.warning(f"❓ **Gut tolerance not recorded for {latest['date']:%d %b}** "
                           f"({int(latest['gels_count'])} gels"
                           + (f", {latest['fuel_product']}" if latest["fuel_product"] else "") + "). "
                           "This is the open decision: it determines whether the next long run steps "
                           "up a gel or repeats at the same count. Add it on the Log runs tab.")

        st.divider()

        col3, col4 = st.columns(2)
        with col3:
            st.subheader("Run quality — grade GPA")
            graded = R.dropna(subset=["grade_points"]).sort_values("date").copy()
            graded["GPA_ma"] = graded["grade_points"].rolling(ma_n, min_periods=1).mean()
            # ungraded runs (e.g. the field test) stay in as null rows so the line
            # visibly breaks instead of interpolating straight through them
            blank = R[R["grade_points"].isna() & R["is_run"]].copy()
            blank["GPA_ma"] = None
            gp = pd.concat([graded, blank]).sort_values("date")
            g_raw = alt.Chart(graded).mark_point(size=45, opacity=0.35, filled=True, color=C_OUT).encode(
                x=alt.X("date:T", title=None, axis=AXIS),
                y=alt.Y("grade_points:Q", title="GPA",
                        scale=alt.Scale(domain=list(plan.GPA_RANGE)), axis=AXIS),
                tooltip=[alt.Tooltip("date:T"), alt.Tooltip("grade:N"), alt.Tooltip("notes:N")])
            g_line = alt.Chart(gp).mark_line(color=C_OUT, strokeWidth=2.5).encode(
                x="date:T", y=alt.Y("GPA_ma:Q", scale=alt.Scale(domain=list(plan.GPA_RANGE))),
                tooltip=[alt.Tooltip("GPA_ma:Q", title=f"{ma_n}-run MA", format=".2f")])
            g_gap = alt.Chart(blank).mark_rule(color=C_MUTED, strokeDash=[2, 3], opacity=0.7).encode(
                x="date:T", tooltip=alt.value("Ungraded — field test, deliberately not scored"))
            st.altair_chart(alt.layer(g_gap, g_raw, g_line, *lthr_rules()).properties(height=230)
                            .configure_view(strokeWidth=0), use_container_width=True)
            st.caption(f"A+ = {plan.GPA_MAP['A+']} … C = {plan.GPA_MAP['C']} · faint dots = each graded "
                       f"run, line = {ma_n}-run average. Dashed verticals are deliberately ungraded "
                       "sessions — a field test is a measurement, not a session to score.")

        with col4:
            st.subheader("Cardiac drift — long runs")
            drift = R[R["run_type"] == "long"].dropna(subset=["hr_first_half", "hr_second_half"]).copy()
            if drift.empty:
                st.info("Log **HR 1st half / 2nd half** on long runs (the fields are on the Log runs "
                        "form) and drift tracking appears here. Target is < 15 bpm — your April HM "
                        "showed ~22 bpm, so this is a key readiness metric to move.")
            else:
                drift["drift"] = drift["hr_second_half"] - drift["hr_first_half"]
                drift["status"] = drift["drift"].map(lambda d: "✅ good" if d < 15 else "🔴 high")
                st.dataframe(drift[["date", "distance_km", "hr_first_half", "hr_second_half",
                                    "drift", "status"]], hide_index=True, use_container_width=True)
                st.caption("Target < 15 bpm between halves at steady effort.")

        # ---- form panel ----------------------------------------------------
        st.subheader("Running form vs targets")
        f1, f2, f3 = st.columns(3)

        def _spark(col, field, title, lo=None, hi=None, target_text=""):
            d = R.dropna(subset=[field]).sort_values("date").copy()
            with col:
                if d.empty:
                    st.info(f"No {title} data yet.")
                    return
                d["ma"] = d[field].rolling(ma_n, min_periods=1).mean()
                layers = []
                if lo is not None:
                    layers.append(alt.Chart(pd.DataFrame({"lo": [lo], "hi": [hi]})).mark_rect(
                        color=C_TM, opacity=0.12).encode(
                        y=alt.Y("lo:Q", scale=alt.Scale(zero=False)), y2="hi:Q"))
                layers.append(alt.Chart(d).mark_point(size=40, opacity=0.35, filled=True,
                                                      color=C_OUT).encode(
                    x=alt.X("date:T", title=None, axis=AXIS),
                    y=alt.Y(f"{field}:Q", title=title, scale=alt.Scale(zero=False), axis=AXIS),
                    tooltip=[alt.Tooltip("date:T"), alt.Tooltip(f"{field}:Q"),
                             alt.Tooltip("avg_pace:N", title="pace")]))
                layers.append(alt.Chart(d).mark_line(color=C_OUT, strokeWidth=2.5,
                                                     interpolate="monotone").encode(
                    x="date:T", y=alt.Y("ma:Q", scale=alt.Scale(zero=False))))
                st.altair_chart(alt.layer(*layers).properties(height=180)
                                .configure_view(strokeWidth=0), use_container_width=True)
                st.caption(target_text)

        _spark(f1, "cadence_spm", "cadence (spm)", 178, 180, "Target 178–180 spm (your best: 183)")
        _spark(f2, "vertical_osc_cm", "vert. osc (cm)", 7.0, 8.5, "Target < 8.5 cm (your best: 7.5)")
        _spark(f3, "gct_ms", "GCT (ms)", None, None,
               "Compare only at similar paces — GCT naturally rises when you run slower")

        # ---- shoes ---------------------------------------------------------
        st.subheader("Shoe mileage")
        shoe_km = R.dropna(subset=["shoe"]).groupby("shoe")["distance_km"].sum()
        scols = st.columns(len(plan.SHOES))
        for scol, sh in zip(scols, plan.SHOES):
            scol.metric(sh["model"], f"{shoe_km.get(sh['model'], 0.0):.0f} km",
                        delta=sh["role"], delta_color="off")
        st.caption("Counts only runs where you logged a shoe — most historical rows predate shoe "
                   "logging, so totals build from here.")

# ---------------------------------------------------------------- training plan
with tab_plan:
    st.subheader("Phases")
    pcols = st.columns(len(plan.PHASES))
    icons = {"complete": "✅", "current": "▶", "upcoming": "⬜"}
    for pc, p in zip(pcols, plan.PHASES):
        with pc:
            b = st.container(border=True)
            b.markdown(f"**{icons[p['status']]} {p['name']}**")
            b.caption(f"{p['start']} → {p['end']}")
            lines = []
            if p.get("run_days"):
                lines.append(f"{p['run_days']} run days" + (f" + {p['strength_days']}× strength" if p.get("strength_days") else ""))
            if p.get("weekly_km"):
                lines.append(f"**{p['weekly_km'][0]}–{p['weekly_km'][1]} km/wk**")
            if p.get("long_run_km"):
                lines.append(f"Long runs {p['long_run_km'][0]}→{p['long_run_km'][1]} km")
            if p.get("long_run_peak_km"):
                lines.append(f"LR peak {p['long_run_peak_km']} km")
            b.markdown(" · ".join(lines) if lines else "")
            if p.get("outcome"):
                b.caption("Outcome: " + p["outcome"])

    st.subheader("Long-run ladder")
    lad = pd.DataFrame(plan.full_ladder())
    lad["type"] = lad.get("type", pd.Series()).fillna("build")
    lad["Target"] = [row.get("label") or f"{row['km']:g} km" for _, row in lad.iterrows()]
    lad["Test"] = [row.get("scheduled_test", {}).get("name", "") if isinstance(
        row.get("scheduled_test"), dict) else "" for _, row in lad.iterrows()]
    lad = lad.rename(columns={"date": "Date", "type": "Type", "phase": "Phase"})
    st.dataframe(lad[["Date", "Target", "Type", "Test", "Phase"]],
                 hide_index=True, use_container_width=True)
    st.caption("The two key runs are **time targets, not distance targets** — 30 km *or* 3:15, "
               "whichever comes first. 10 and 17 Oct were also swapped so the block's biggest "
               "session doesn't land at the end of two consecutive build weeks.")
    for step in plan.full_ladder():
        t = step.get("scheduled_test")
        if isinstance(t, dict):
            st.info(f"🎯 **{t['name']}** scheduled into the {step['date']} long run — {t['protocol']}. "
                    + " · ".join(f"{k}: {v}" for k, v in t["thresholds"].items()))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"HR zones — {plan.DEVICE}")
        zt = pd.DataFrame([
            {"Zone": z.upper(), "% LTHR": f"{plan.ZONE_PCT.get(z, ['', ''])[0]}–{plan.ZONE_PCT.get(z, ['', ''])[1]}%",
             **{f"{e['lthr']} (from {e['effective_from']})": f"{e['zones_bpm'][z][0]}–{e['zones_bpm'][z][1]}"
                for e in plan.LTHR_HISTORY}}
            for z in ("z1", "z2", "z3", "z4", "z5")])
        st.dataframe(zt, hide_index=True, use_container_width=True)
        st.caption(f"Both eras shown — runs are always graded against the LTHR in force on the day. "
                   f"Current **LTHR {plan.LTHR_CURRENT}** · Max {plan.MAX_HR} · "
                   f"RHR baseline {plan.RESTING_HR} (rest-day rule at {plan.RESTING_HR + 5}+).")
        if plan.LTHR_EPOCH_IS_PLACEHOLDER:
            st.info(f"⚠️ The **{plan.LTHR_HISTORY[0]['lthr']}** era's start date "
                    f"({plan.LTHR_HISTORY[0]['effective_from']}) is a placeholder, not the real rebase "
                    "date. Runs before it fall back to that entry. Replace it in "
                    "`athlete_profile.json` if the true date can be recovered.")
        if plan.RESTING_HR and any("63" in r for r in plan.GOLDEN_RULES):
            st.warning(f"Golden rule below still cites an RHR baseline of 63; the profile now says "
                       f"**{plan.RESTING_HR}**. Read the rest-day trigger as "
                       f"{plan.RESTING_HR + 5}+ bpm until the plan JSON is updated.")
        st.subheader("Pace reference")
        st.dataframe(pd.DataFrame({"Context": [k.replace('_', ' ') for k in plan.PACE_REFERENCE],
                                   "Pace": list(plan.PACE_REFERENCE.values())}),
                     hide_index=True, use_container_width=True)
    with col2:
        st.subheader("Taper (16 Nov – 8 Dec)")
        taper = next(p for p in plan.PHASES if p["id"] == "taper")
        for wkk in taper["structure"]:
            st.markdown(f"- **{wkk['week']}** — {wkk['volume']}: {wkk.get('long_run', wkk.get('details', ''))}")
        st.subheader("Environment (Singapore)")
        for k, v in plan.ENVIRONMENT.items():
            st.markdown(f"- **{k.replace('_', ' ')}**: {v}")
        st.subheader("Golden rules")
        for r in plan.GOLDEN_RULES:
            st.markdown(f"- {r}")

# ---------------------------------------------------------------- race day
with tab_race:
    goal = plan.GOALS[goal_key]
    offset = plan.GOAL_OFFSETS_S[goal_key]

    st.subheader("Targets & the October decision gate")
    gcols = st.columns(len(plan.GOALS) + 1)
    for gcol, (k, g) in zip(gcols, plan.GOALS.items()):
        sel = "👉 " if k == goal_key else ""
        gcol.metric(f"{sel}{g['label']}", g["pace"], delta=g["kind"], delta_color="off")
    if plan.MARATHON_EQUIV:
        gcols[-1].metric("Current equivalent", plan.MARATHON_EQUIV["range"],
                         delta=f"as of {plan.MARATHON_EQUIV['as_of']}", delta_color="off",
                         help=plan.MARATHON_EQUIV["basis"])
    for rg in plan.RETIRED_GOALS:
        st.warning(f"🚫 **{rg['label']} retired** on {rg['retired_on']} — {rg['reason']}")
    if plan.MARATHON_EQUIV:
        st.caption(f"Current fitness projects to **{plan.MARATHON_EQUIV['range']}** "
                   f"({plan.MARATHON_EQUIV['basis']}). Sub-3:50 stays the target: "
                   + plan.PROFILE["primary_race"]["goal"].get("confidence", ""))
    tune = next(p for p in plan.PHASES if p["id"] == "phase3")["tune_up"]
    st.info(f"🔀 **Tune-up HM ({tune['window']})**, full race effort. Decision rule: {tune['decision_rule']}")

    # ---- checkpoint status cards (e.g. the October marathon-pace HR gate)
    for cp in plan.CHECKPOINTS:
        with st.container(border=True):
            w0, w1 = cp["window"]
            icon = {"pending": "🕒", "passed": "✅", "failed": "🔴"}.get(cp["status"], "🕒")
            st.markdown(f"**{icon} {cp['name']}** — {cp['status'].upper()} · window {w0} → {w1}")
            st.caption(cp["test"])
            tc = st.columns(3)
            for col, (band, txt) in zip(tc, cp["thresholds"].items()):
                col.markdown(f"{'🟢' if band == 'green' else '🟠' if band == 'amber' else '🔴'} {txt}")
            days = (date.fromisoformat(w0) - TODAY).days
            if cp["status"] == "pending":
                st.caption(f"Opens in {days} days — do it inside a Phase 3 long run."
                           if days > 0 else "Window is open — schedule it into a long run now.")

    # ---- Riegel predictor (feature 10)
    st.subheader("Race predictor")
    tune_races = running[(running["run_type"] == "race_hm") & (running["date"] >= date(2026, 9, 1))]
    if tune_races.empty:
        st.info("Activates after the tune-up HM (3–4 Oct). Log it with type `race_hm` and the Riegel "
                "projection + MP-block validation will appear here, mapped to the 3:50 / 3:40 / 3:35 bands.")
    else:
        r = tune_races.sort_values("date").iloc[-1]
        hm_s = duration_to_min(r["duration"]) * 60 if duration_to_min(r["duration"]) else None
        if hm_s:
            proj = hm_s * (42.195 / float(r["distance_km"])) ** 1.06
            st.metric("Riegel projection from tune-up", fmt_hms(proj),
                      delta=f"HM {fmt_hms(hm_s)} on {r['date']}", delta_color="off")
            for label, secs in [("3:50", 13800), ("3:40", 13200), ("3:35", 12900)]:
                verdict = "✅ inside" if proj < secs else "❌ outside"
                st.markdown(f"- **Sub {label}**: {verdict} (needs {fmt_hms(secs)})")
            st.caption("Riegel exponent 1.06. Validate with MP blocks in Phase 3 long runs before committing.")

    st.subheader(f"Pacing plan — {goal['label']}")
    if offset:
        st.caption(f"Segment paces shifted −{offset} s/km from the 3:50 plan. Only race this if the tune-up gate opened it.")
    scols = st.columns(4)
    for sc, seg in zip(scols, plan.RACE_STRATEGY):
        base_s = int(seg["pace"].split(":")[0]) * 60 + int(seg["pace"].split(":")[1])
        with sc:
            b = st.container(border=True)
            b.markdown(f"**{seg['km']} · {seg['phase']}**")
            b.markdown(f"### {fmt_pace(base_s - offset)}/km")
            b.caption(seg["zone"])
            b.caption(seg["note"])

    col1, col2 = st.columns(2)
    with col1:
        if goal_key == "3:50":
            st.subheader("Gut-check splits")
            st.dataframe(pd.DataFrame(plan.GUT_CHECKS).rename(
                columns={"km": "At", "time": "Clock", "note": "Check"}), hide_index=True, use_container_width=True)
        st.error(plan.WALL_WARNING)
    with col2:
        st.subheader("Fueling")
        fm, fh = plan.FUELING["marathon"], plan.FUELING["half_marathon"]
        st.markdown(f"- **Marathon**: {fm['carbs_g_per_hour'][0]}–{fm['carbs_g_per_hour'][1]} g carbs/h "
                    f"= a gel every {fm['gel_interval_min'][0]}–{fm['gel_interval_min'][1]} min")
        st.markdown(f"- **Proven HM protocol**: {fh['strategy']} — {', '.join(fh['timing'])}")
        st.markdown(f"- **Training rule**: {plan.FUELING['training_rule']}")
        st.markdown(f"- **Pre-run**: {plan.FUELING['pre_run']}")
        st.markdown(f"- **Race shoe**: {next(s['model'] for s in plan.SHOES if 'race' in s['role'])} (foam reserved)")
