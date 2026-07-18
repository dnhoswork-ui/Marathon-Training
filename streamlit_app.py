"""Road to Sub-3:50 — marathon dashboard, training plan v3 (JSON-driven)."""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import parser as run_parser
import plan
import storage

st.set_page_config(page_title="Road to Sub-3:50", page_icon="🏃", layout="wide")

# validated palette (dataviz): outdoor=blue, treadmill=green, plan/targets=muted
C_OUT = "#2a78d6"
C_TM = "#008300"
C_MUTED = "#898781"
C_GRID = "#e1e0d9"
C_BAND = "#9ec5f4"
C_CRIT = "#d03b3b"
SURF_SCALE = alt.Scale(domain=["outdoor", "treadmill"], range=[C_OUT, C_TM])
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
    return df


def heat_adjusted(df: pd.DataFrame, on: bool) -> pd.DataFrame:
    """Adds pace_adj (heat-adjusted pace where feels-like was logged)."""
    df = df.copy()
    adj = (df["feels_like_c"] - plan.HEAT_THRESHOLD_C).clip(lower=0) * plan.HEAT_S_PER_KM_PER_C
    df["pace_adj"] = df["pace_sec_per_km"] - adj.fillna(0) if on else df["pace_sec_per_km"]
    return df


def trend_pool(df: pd.DataFrame) -> pd.DataFrame:
    """Rows usable for fitness trends: exact dates, no races/shakeouts."""
    return df[df["is_run"] & (df["date_precision"] != "approx")
              & df["run_type"].isin(["easy", "long", "tempo"])]


if "runs" not in st.session_state:
    _df, _src = storage.load_runs()
    st.session_state["runs"] = _df
    st.session_state["runs_source"] = _src

TODAY = date.today()
CUR = plan.display_phase(TODAY)
DAYS_TO_RACE = (plan.RACE_DATE - TODAY).days
runs = enrich(st.session_state["runs"])
running = runs[runs["is_run"]] if not runs.empty else runs

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🏃 Road to Sub-3:50")
    st.caption(f"Plan v3 · {plan.PROFILE['device']} · HM PR {plan.PROFILE['prs']['half_marathon']['time']}")
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
    st.divider()
    st.caption(f"Run log: {st.session_state['runs_source']}")
    st.caption("Screenshot parsing: " + ("✅ enabled" if run_parser.available() else "❌ add ANTHROPIC_API_KEY"))
    if st.button("↻ Reload data"):
        _df, _src = storage.load_runs()
        st.session_state["runs"] = _df
        st.session_state["runs_source"] = _src
        st.rerun()

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
        if CUR.get("week_1_special") and wk <= 1 and CUR["id"] == "phase2":
            st.error("🧪 **Week 1:** " + CUR["week_1_special"])
        tmpl = CUR.get("weekly_template")
        if tmpl:
            days = pd.DataFrame({"Day": list(tmpl), "Session": list(tmpl.values())})
            days["Today"] = ["👉" if TODAY.strftime("%a") == d else "" for d in days["Day"]]
            st.dataframe(days[["Today", "Day", "Session"]], hide_index=True, use_container_width=True)
        for name, detail in CUR.get("key_sessions", {}).items():
            st.markdown(f"- **{name.replace('_', ' ').title()}**: {detail}")
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
            f_date = st.date_input("Date", value=pre_date)
            r1 = st.columns(2)
            f_type = r1[0].selectbox("Type", plan.RUN_TYPES)
            f_surface = r1[1].selectbox("Surface", plan.SURFACES)
            r2 = st.columns(2)
            f_dist = r2[0].number_input("Distance (km)", 0.0, 60.0, float(pre.get("distance_km") or 0.0), 0.01)
            f_dur = r2[1].text_input("Duration (H:MM:SS)", value=pre.get("duration") or "")
            r3 = st.columns(3)
            f_hr = r3[0].number_input("Avg HR", 0, 220, int(pre.get("avg_hr") or 0))
            f_cad = r3[1].number_input("Cadence (spm)", 0, 250, int(pre.get("cadence_spm") or 0))
            f_feels = r3[2].number_input("Feels-like °C", 0.0, 50.0, float(pre.get("feels_like_c") or 0.0), 0.5)
            r4 = st.columns(3)
            f_vo = r4[0].number_input("Vert. osc (cm)", 0.0, 15.0, float(pre.get("vertical_osc_cm") or 0.0), 0.1)
            f_gct = r4[1].number_input("GCT (ms)", 0, 400, int(pre.get("gct_ms") or 0))
            f_grade = r4[2].selectbox("Grade", plan.GRADES)
            r5 = st.columns(3)
            f_shoe = r5[0].selectbox("Shoe", [""] + plan.SHOE_NAMES + ["Other"])
            f_hr1 = r5[1].number_input("HR 1st half", 0, 220, 0, help="For cardiac-drift tracking on long runs")
            f_hr2 = r5[2].number_input("HR 2nd half", 0, 220, 0)
            f_notes = st.text_input("Notes", value=pre.get("run_title") or "")
            if st.form_submit_button("Save run", type="primary"):
                mins = duration_to_min(f_dur)
                pace_s = int(mins * 60 / f_dist) if (mins and f_dist > 0) else None
                p = plan.phase_of(f_date)
                row = {
                    "date": f_date, "date_precision": "exact",
                    "phase": p["id"] if p else "", "run_type": f_type, "surface": f_surface,
                    "distance_km": round(f_dist, 2) or None, "duration": f_dur.strip() or None,
                    "avg_pace": fmt_pace(pace_s) if pace_s else None, "pace_sec_per_km": pace_s,
                    "avg_hr": f_hr or None, "cadence_spm": f_cad or None,
                    "vertical_osc_cm": f_vo or None, "gct_ms": f_gct or None,
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
                st.rerun()

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
    c2.download_button("⬇ Download runs.csv", st.session_state["runs"].to_csv(index=False), "runs.csv", "text/csv")

# ---------------------------------------------------------------- progress
with tab_prog:
    if running.empty:
        st.info("No runs logged yet.")
        st.stop()

    heat_on = st.toggle(
        "🌡 Heat-adjusted paces",
        help=f"Subtracts ~{plan.HEAT_S_PER_KM_PER_C:g} s/km per °C of feels-like above "
             f"{plan.HEAT_THRESHOLD_C:g} °C, where logged. {plan.ENVIRONMENT['heat_effect']}")
    R = heat_adjusted(running, heat_on)
    pool = trend_pool(R)

    # ---- weekly volume vs band + 10% flags (feature 4)
    st.subheader("Weekly volume vs plan band")
    wsum = R.groupby("week", as_index=False)["distance_km"].sum().rename(columns={"distance_km": "km"})
    all_weeks = pd.date_range(wsum["week"].min(), plan.RACE_DATE, freq="W-MON").date
    vol = pd.DataFrame({"week": all_weeks}).merge(wsum, on="week", how="left").fillna({"km": 0})
    bands = [plan.weekly_band(w) for w in vol["week"]]
    vol["lo"] = [b[0] if b else None for b in bands]
    vol["hi"] = [b[1] if b else None for b in bands]
    prev = vol["km"].shift(1)
    vol["breach"] = (prev > 10) & (vol["km"] > prev * 1.10)
    vol["week_str"] = vol["week"].astype(str)

    band_area = alt.Chart(vol.dropna(subset=["lo"])).mark_area(color=C_BAND, opacity=0.25).encode(
        x=alt.X("week:T", title=None, axis=AXIS), y=alt.Y("lo:Q", title="km/week", axis=AXIS), y2="hi:Q")
    gap_df = pd.DataFrame([{"s": str(s), "e": str(e), "label": lab} for s, e, lab in plan.GAPS])
    gap_rects = alt.Chart(gap_df).mark_rect(color=C_MUTED, opacity=0.12).encode(
        x="s:T", x2="e:T", tooltip=["label:N"])
    gap_text = alt.Chart(gap_df).mark_text(dy=-80, angle=270, color=C_MUTED, fontSize=10).encode(
        x="s:T", text="label:N")
    vbars = alt.Chart(vol[vol["km"] > 0]).mark_bar(width=8, cornerRadiusTopLeft=3, cornerRadiusTopRight=3,
                                                   color=C_OUT).encode(
        x="week:T", y="km:Q",
        tooltip=[alt.Tooltip("week:T", title="Week of"), alt.Tooltip("km:Q", format=".1f"),
                 alt.Tooltip("lo:Q", title="Band lo", format=".0f"),
                 alt.Tooltip("hi:Q", title="Band hi", format=".0f")])
    flags = alt.Chart(vol[vol["breach"]]).mark_text(text="⚠", dy=-10, fontSize=14, color=C_CRIT).encode(
        x="week:T", y="km:Q", tooltip=alt.value("More than +10% vs previous week"))
    st.altair_chart((band_area + gap_rects + gap_text + vbars + flags + alt.Chart(
        pd.DataFrame({"d": [str(TODAY)]})).mark_rule(color=C_CRIT, strokeWidth=1.5).encode(x="d:T"))
        .properties(height=240).configure_view(strokeWidth=0), use_container_width=True)
    st.caption("🟦 bars = logged km · shaded band = phase target · ⚠ = 10%-rule breach · gray blocks = illness/holiday (real gaps, not missing data)")

    # ---- long-run ladder (feature 5)
    st.subheader("Long-run ladder — planned vs actual")
    ladder = pd.DataFrame(plan.full_ladder())
    ladder["date"] = pd.to_datetime(ladder["date"])
    ladder["kind"] = ladder["type"].fillna("build") if "type" in ladder else "build"
    actual_lr = R[R["run_type"].isin(["long", "race_hm"])].copy()
    plan_line = alt.Chart(ladder).mark_line(color=C_MUTED, strokeWidth=1.5, point=alt.OverlayMarkDef(
        color=C_MUTED, size=45)).encode(
        x=alt.X("date:T", title=None, axis=AXIS),
        y=alt.Y("km:Q", title="km", axis=AXIS),
        tooltip=[alt.Tooltip("date:T"), alt.Tooltip("km:Q"), alt.Tooltip("kind:N", title="type")])
    act_pts = alt.Chart(actual_lr).mark_point(filled=True, size=90, color=C_OUT, stroke="#ffffff",
                                              strokeWidth=2).encode(
        x="date:T", y="distance_km:Q",
        tooltip=[alt.Tooltip("date:T"), alt.Tooltip("distance_km:Q", title="km", format=".1f"),
                 alt.Tooltip("grade:N"), alt.Tooltip("avg_hr:Q", title="avg HR"),
                 alt.Tooltip("notes:N")])
    act_line = alt.Chart(actual_lr).mark_line(color=C_OUT, strokeWidth=2).encode(x="date:T", y="distance_km:Q")
    chips = alt.Chart(actual_lr.dropna(subset=["grade"])).mark_text(dy=-14, fontSize=10, fontWeight=600,
                                                                    color="#52514e").encode(
        x="date:T", y="distance_km:Q", text="grade:N")
    lr_today = alt.Chart(pd.DataFrame({"d": [str(TODAY)]})).mark_rule(color=C_CRIT, strokeWidth=1.5).encode(x="d:T")
    st.altair_chart((plan_line + act_line + act_pts + chips + lr_today).properties(height=260)
                    .configure_view(strokeWidth=0), use_container_width=True)
    st.caption("⬜ gray = planned ladder (down weeks included, 32 km peak on 14 Nov) · 🟦 blue = actual long runs with grade chips")

    col1, col2 = st.columns(2)
    with col1:
        # ---- EF trend (feature 2)
        st.subheader("Efficiency Factor (3-run MA)")
        ef = pool.dropna(subset=["pace_adj", "avg_hr"]).copy()
        ef = ef[ef["run_type"].isin(["easy", "long"])].sort_values("date")
        ef["EF"] = (1000 / ef["pace_adj"] * 60) / ef["avg_hr"]
        ef["EF_ma"] = ef.groupby("surface")["EF"].transform(lambda s: s.rolling(3, min_periods=1).mean())
        ef_chart = alt.Chart(ef).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(
            size=55, filled=True, stroke="#ffffff", strokeWidth=2)).encode(
            x=alt.X("date:T", title=None, axis=AXIS),
            y=alt.Y("EF_ma:Q", title="m/min per bpm", scale=alt.Scale(zero=False), axis=AXIS),
            color=alt.Color("surface:N", scale=SURF_SCALE,
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip("date:T"), alt.Tooltip("surface:N"),
                     alt.Tooltip("EF:Q", format=".3f"), alt.Tooltip("EF_ma:Q", title="3-run MA", format=".3f"),
                     alt.Tooltip("avg_pace:N", title="pace"), alt.Tooltip("avg_hr:Q")])
        st.altair_chart(ef_chart.properties(height=230).configure_view(strokeWidth=0), use_container_width=True)
        st.caption("Higher = more speed per heartbeat — the honest fitness signal when pace and HR move together. Compare within a surface only.")

    with col2:
        # ---- pace vs HR scatter (feature 3)
        st.subheader("Pace vs HR — the aerobic curve")
        sc = pool.dropna(subset=["pace_adj", "avg_hr"])
        z2band = alt.Chart(pd.DataFrame({"lo": [plan.Z2[0]], "hi": [plan.Z2[1]]})).mark_rect(
            color=C_OUT, opacity=0.08).encode(
            y=alt.Y("lo:Q", scale=alt.Scale(domain=[125, 175])), y2="hi:Q")
        train_rule = alt.Chart(pd.DataFrame({"y": [plan.Z2_TRAIN[1]]})).mark_rule(
            color=C_MUTED, strokeDash=[1, 0], strokeWidth=1).encode(y="y:Q")
        pts = alt.Chart(sc).mark_point(filled=True, opacity=0.85, stroke="#ffffff", strokeWidth=1.5).encode(
            x=alt.X("pace_adj:Q", title="pace (min/km)" + (" · heat-adjusted" if heat_on else ""),
                    scale=alt.Scale(domain=[330, 530]),
                    axis=alt.Axis(gridColor=C_GRID, labelColor=C_MUTED, titleColor=C_MUTED,
                                  labelExpr=PACE_LABEL, tickCount=6)),
            y=alt.Y("avg_hr:Q", title="avg HR", scale=alt.Scale(domain=[125, 175]), axis=AXIS),
            color=alt.Color("surface:N", scale=SURF_SCALE, legend=alt.Legend(orient="top", title=None)),
            size=alt.Size("distance_km:Q", legend=None, scale=alt.Scale(range=[40, 350])),
            tooltip=[alt.Tooltip("date:T"), alt.Tooltip("run_type:N"), alt.Tooltip("surface:N"),
                     alt.Tooltip("avg_pace:N", title="pace"), alt.Tooltip("avg_hr:Q"),
                     alt.Tooltip("distance_km:Q", format=".1f"), alt.Tooltip("grade:N")])
        st.altair_chart((z2band + train_rule + pts).properties(height=230).configure_view(strokeWidth=0),
                        use_container_width=True)
        st.caption(f"Shaded = Z2 ({plan.Z2[0]}–{plan.Z2[1]}), line = train-to ceiling {plan.Z2_TRAIN[1]}. "
                   "Progress = the cloud shifting left (faster) inside the band. Dot size = distance.")

    col3, col4 = st.columns(2)
    with col3:
        # ---- grade GPA trend (feature 7)
        st.subheader("Run quality — grade GPA (3-run MA)")
        gp = R.dropna(subset=["grade_points"]).sort_values("date").copy()
        gp["GPA_ma"] = gp["grade_points"].rolling(3, min_periods=1).mean()
        gpa_chart = alt.Chart(gp).mark_line(color=C_OUT, strokeWidth=2, point=alt.OverlayMarkDef(
            color=C_OUT, size=50, stroke="#ffffff", strokeWidth=2)).encode(
            x=alt.X("date:T", title=None, axis=AXIS),
            y=alt.Y("GPA_ma:Q", title="GPA", scale=alt.Scale(domain=[2.0, 4.4]), axis=AXIS),
            tooltip=[alt.Tooltip("date:T"), alt.Tooltip("grade:N"),
                     alt.Tooltip("GPA_ma:Q", title="3-run MA", format=".2f"), alt.Tooltip("notes:N")])
        st.altair_chart(gpa_chart.properties(height=210).configure_view(strokeWidth=0), use_container_width=True)
        st.caption("A+ = 4.3 … C = 2.0, per your grading convention.")

    with col4:
        # ---- cardiac drift (feature 9)
        st.subheader("Cardiac drift — long runs")
        drift = R[(R["run_type"] == "long")].dropna(subset=["hr_first_half", "hr_second_half"]).copy()
        if drift.empty:
            st.info("Log **HR 1st half / 2nd half** on long runs (form fields exist) — target drift "
                    "< 15 bpm. The HM race showed ~22 bpm.")
        else:
            drift["drift"] = drift["hr_second_half"] - drift["hr_first_half"]
            drift["status"] = drift["drift"].map(lambda d: "✅ good" if d < 15 else "🔴 high")
            st.dataframe(drift[["date", "distance_km", "hr_first_half", "hr_second_half", "drift", "status"]],
                         hide_index=True, use_container_width=True)
            st.caption("Target < 15 bpm between halves at steady effort.")

    # ---- form panel (feature 6)
    st.subheader("Running form vs targets")
    f1, f2, f3 = st.columns(3)
    def _spark(col, field, title, lo=None, hi=None, target_text=""):
        d = R.dropna(subset=[field]).sort_values("date")
        with col:
            if d.empty:
                st.info(f"No {title} data yet.")
                return
            layers = []
            if lo is not None:
                layers.append(alt.Chart(pd.DataFrame({"lo": [lo], "hi": [hi]})).mark_rect(
                    color=C_TM, opacity=0.10).encode(y=alt.Y("lo:Q", scale=alt.Scale(zero=False)), y2="hi:Q"))
            layers.append(alt.Chart(d).mark_line(color=C_OUT, strokeWidth=2, point=alt.OverlayMarkDef(
                color=C_OUT, size=40, stroke="#ffffff", strokeWidth=2)).encode(
                x=alt.X("date:T", title=None, axis=AXIS),
                y=alt.Y(f"{field}:Q", title=title, scale=alt.Scale(zero=False), axis=AXIS),
                tooltip=[alt.Tooltip("date:T"), alt.Tooltip(f"{field}:Q"), alt.Tooltip("avg_pace:N", title="pace")]))
            st.altair_chart(alt.layer(*layers).properties(height=160).configure_view(strokeWidth=0),
                            use_container_width=True)
            st.caption(target_text)
    _spark(f1, "cadence_spm", "cadence (spm)", 178, 180, "Target 178–180 spm (best: 183)")
    _spark(f2, "vertical_osc_cm", "vert. osc (cm)", 7.0, 8.5, "Target < 8.5 cm (best: 7.5)")
    _spark(f3, "gct_ms", "GCT (ms)", None, None, "Compare only at similar paces — GCT rises naturally when running slower")

    # ---- shoes (feature 11)
    st.subheader("Shoe mileage")
    shoe_km = R.dropna(subset=["shoe"]).groupby("shoe")["distance_km"].sum()
    scols = st.columns(len(plan.SHOES))
    for scol, s in zip(scols, plan.SHOES):
        km = shoe_km.get(s["model"], 0.0)
        scol.metric(s["model"], f"{km:.0f} km", delta=s["role"], delta_color="off")
    st.caption("Mileage counts from logged `shoe` values — historical rows mostly predate shoe logging; totals build going forward.")

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
    lad = lad.rename(columns={"date": "Date", "km": "Km", "type": "Type", "phase": "Phase"})
    st.dataframe(lad[["Date", "Km", "Type", "Phase"]], hide_index=True, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"HR zones — {plan.PROFILE['device']}")
        if plan.ZONES_PROVISIONAL:
            st.warning("Provisional until the 30-min LTHR field test. " + plan.HR["note"])
        z = plan.HR["zones"]
        st.dataframe(pd.DataFrame({"Zone": list(z), "Range (bpm)": list(z.values())}),
                     hide_index=True, use_container_width=True)
        st.caption(f"LTHR {plan.HR['lthr']} · Max {plan.HR['max_hr']} · RHR {plan.HR['rhr_current']} "
                   f"(rest-day rule triggers at {plan.HR['rhr_current'] + 5}+)")
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
    g1, g2, g3 = st.columns(3)
    for gcol, (k, g) in zip((g1, g2, g3), plan.GOALS.items()):
        sel = "👉 " if k == goal_key else ""
        gcol.metric(f"{sel}{g['label']}", g["pace"], delta=g["kind"], delta_color="off")
    tune = next(p for p in plan.PHASES if p["id"] == "phase3")["tune_up"]
    st.info(f"🔀 **Tune-up HM ({tune['window']})**, full race effort. Decision rule: {tune['decision_rule']}")

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
        st.markdown(f"- **Marathon target**: {plan.FUELING['marathon_target']}")
        st.markdown(f"- **Proven HM protocol**: {plan.FUELING['proven_hm_protocol']}")
        st.markdown(f"- **Training rule**: {plan.FUELING['training_rule']}")
        st.markdown(f"- **Pre-run**: {plan.FUELING['pre_run']}")
        st.markdown(f"- **Race shoe**: {next(s['model'] for s in plan.SHOES if 'race' in s['role'])} (foam reserved)")
