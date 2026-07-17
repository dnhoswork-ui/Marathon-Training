"""Road to Sub-3:50 — marathon training dashboard for training plan v2."""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import parser as run_parser
import plan
import storage

st.set_page_config(page_title="Road to Sub-3:50", page_icon="🏃", layout="wide")

# validated palette (dataviz skill): series-1 blue, series-2 green, muted grays
C_PLAN = "#2a78d6"
C_ACTUAL = "#008300"
C_MUTED = "#898781"
C_GRID = "#e1e0d9"
C_WARN = "#d03b3b"


# ---------------------------------------------------------------- helpers
def pace_to_s(p: str) -> int:
    m, s = p.split(":")
    return int(m) * 60 + int(s)


def s_to_pace(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


def duration_to_min(d) -> float | None:
    if not isinstance(d, str) or ":" not in d:
        return None
    parts = [int(p) for p in d.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 60 + parts[1] + parts[2] / 60
    if len(parts) == 2:
        return parts[0] + parts[1] / 60
    return None


def pace_of(row) -> str | None:
    mins = duration_to_min(row.get("duration"))
    km = row.get("distance_km")
    if mins and km and km > 0:
        sec = int(mins * 60 / km)
        return s_to_pace(sec)
    return None


def runs_df() -> pd.DataFrame:
    return st.session_state["runs"]


def set_runs(df: pd.DataFrame):
    st.session_state["runs"] = df


def with_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Adds plan week/month and computed pace columns (running runs only)."""
    df = df.copy()
    if df.empty:
        for c in ("week", "month", "pace_s"):
            df[c] = pd.Series(dtype="float")
        return df
    df["week"] = df["date"].map(lambda d: plan.week_index(d) + 1)  # 1-based for display
    df["month"] = df["date"].map(lambda d: plan.month_of_week(plan.week_index(d)))
    mins = df["duration"].map(duration_to_min)
    df["pace_s"] = (mins * 60 / df["distance_km"]).where(df["distance_km"] > 0)
    return df


def running_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["type"].isin(["Strength", "Other"])]


if "runs" not in st.session_state:
    df, source = storage.load_runs()
    st.session_state["runs"] = df
    st.session_state["runs_source"] = source

TODAY = date.today()
WI = plan.week_index(TODAY)                      # 0-based
CUR_WEEK = WI + 1
CUR_MONTH = plan.month_of_week(WI)
CUR_PHASE = plan.phase_of_month(CUR_MONTH)
DAYS_TO_RACE = (plan.RACE["date"] - TODAY).days


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🏃 Road to Sub-3:50")
    st.caption(f"9-month plan v2 · HM PR {plan.ATHLETE['hm_pr']}")

    st.metric("Days to race", DAYS_TO_RACE if DAYS_TO_RACE >= 0 else "🏅 done",
              help=plan.RACE["date"].strftime("%A, %d %B %Y"))
    if 0 <= WI < plan.TOTAL_WEEKS:
        st.metric("Plan position", f"M{CUR_MONTH} · Wk {CUR_WEEK}/36",
                  delta=f"Phase {CUR_PHASE['num']}: {CUR_PHASE['name']}", delta_color="off")
    st.divider()

    goal = st.radio(
        "Race goal",
        [f"{plan.RACE['goal']} ({plan.RACE['goal_pace']})",
         f"{plan.RACE['stretch']} ({plan.RACE['stretch_pace']}) — stretch"],
        help=plan.RACE["decision"],
    )
    STRETCH = goal.startswith(plan.RACE["stretch"])

    st.divider()
    st.caption(f"Run log: {st.session_state['runs_source']}")
    st.caption("Screenshot parsing: " + ("✅ enabled" if run_parser.available() else "❌ add ANTHROPIC_API_KEY secret"))
    if st.button("↻ Reload data"):
        df, source = storage.load_runs()
        set_runs(df)
        st.session_state["runs_source"] = source
        st.rerun()


tab_overview, tab_log, tab_progress, tab_plan, tab_race = st.tabs(
    ["📍 Overview", "➕ Log runs", "📈 Progress", "🗓 Training plan", "🏁 Race strategy"]
)

runs = with_derived(runs_df())
running = running_only(runs)

# ---------------------------------------------------------------- overview
with tab_overview:
    in_plan = 0 <= WI < plan.TOTAL_WEEKS
    target = plan.weekly_target_km(WI) if in_plan else 0.0
    this_week = running[running["week"] == CUR_WEEK] if in_plan else running.iloc[0:0]
    week_km = float(this_week["distance_km"].sum())
    long_this_week = float(this_week["distance_km"].max()) if len(this_week) else 0.0
    total_km = float(running["distance_km"].sum())

    c = st.columns(5)
    c[0].metric("This week", f"{week_km:.1f} km", delta=f"target {target:.0f} km", delta_color="off")
    c[1].metric("Longest run this week", f"{long_this_week:.1f} km" if long_this_week else "—")
    c[2].metric("Total logged", f"{total_km:.0f} km", delta=f"{len(running)} runs", delta_color="off")
    last4 = running[running["week"].between(CUR_WEEK - 4, CUR_WEEK - 1)]["distance_km"].sum() if in_plan else 0
    c[3].metric("Last 4 weeks", f"{last4:.0f} km")
    zone_mix = "/".join(part.split("%")[0].strip() for part in CUR_PHASE["distribution"].split("·"))
    c[4].metric("Zone mix (Z2/Z3/Z4)", zone_mix,
                delta=CUR_PHASE["long_run_peak"] + " LR peak", delta_color="off")

    st.subheader(f"This week's sessions — Phase {CUR_PHASE['num']}: {CUR_PHASE['name']}")
    ws = plan.week_start(WI) if in_plan else plan.PLAN_START
    st.caption(f"Week of {ws:%d %b} – {ws + timedelta(days=6):%d %b} · weekly target ≈ {target:.0f} km")
    sess = pd.DataFrame([
        {"Day": s["day"], "Session": s["type"], "Details": s[CUR_PHASE["num"]], "HR target": s["hr"]}
        for s in plan.WEEKLY_SESSIONS
    ])
    st.dataframe(sess, hide_index=True, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"Month {CUR_MONTH} milestone")
        st.info(plan.MILESTONES.get(CUR_MONTH, "—"))
        if CUR_MONTH == 6:
            st.warning("🔀 " + plan.RACE["decision"])
    with col2:
        st.subheader("Golden rules")
        for icon, rule, sub in plan.GOLDEN_RULES[:3]:
            st.markdown(f"{icon} **{rule}** — {sub}")
        with st.expander("All six rules"):
            for icon, rule, sub in plan.GOLDEN_RULES[3:]:
                st.markdown(f"{icon} **{rule}** — {sub}")

# ---------------------------------------------------------------- log runs
with tab_log:
    left, right = st.columns([1, 1])

    with left:
        st.subheader("📷 From a screenshot")
        if run_parser.available():
            shot = st.file_uploader("Upload a Garmin/Strava/Coros screenshot",
                                    type=["png", "jpg", "jpeg", "webp"])
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
            st.info(
                "Screenshot parsing needs an **ANTHROPIC_API_KEY** in the app's secrets "
                "(Streamlit Cloud → app → Settings → Secrets). Until then, log runs manually — "
                "or paste the screenshot into a Claude chat and ask for a CSV row."
            )

    with right:
        st.subheader("✍️ Add a run")
        pre = st.session_state.get("prefill") or {}
        pre_date = None
        if pre.get("date"):
            try:
                pre_date = date.fromisoformat(pre["date"])
            except ValueError:
                pre_date = None
        with st.form("add_run", clear_on_submit=True):
            f_date = st.date_input("Date", value=pre_date or TODAY)
            f_type = st.selectbox("Type", plan.RUN_TYPES)
            f_dist = st.number_input("Distance (km)", 0.0, 60.0,
                                     float(pre.get("distance_km") or 0.0), 0.1)
            f_dur = st.text_input("Duration (H:MM:SS or MM:SS)", value=pre.get("duration") or "")
            f_hr = st.number_input("Avg HR (bpm, 0 = n/a)", 0, 220, int(pre.get("avg_hr") or 0))
            f_cad = st.number_input("Cadence (spm, 0 = n/a)", 0, 250, int(pre.get("cadence") or 0))
            f_notes = st.text_input("Notes", value=pre.get("run_title") or "")
            if st.form_submit_button("Save run", type="primary"):
                row = {
                    "date": f_date, "type": f_type, "distance_km": round(f_dist, 2),
                    "duration": f_dur.strip() or None,
                    "avg_pace": pace_of({"duration": f_dur, "distance_km": f_dist}),
                    "avg_hr": f_hr or None, "cadence": f_cad or None,
                    "notes": f_notes.strip() or None,
                    "source": "screenshot" if pre else "manual",
                }
                new = pd.concat([runs_df(), pd.DataFrame([row])], ignore_index=True)
                ok, msg = storage.save_runs(new)
                set_runs(storage.load_runs()[0] if ok else new)
                st.session_state.pop("prefill", None)
                (st.success if ok else st.error)(msg)
                st.rerun()

    st.divider()
    st.subheader("Run log")
    st.caption("Edit cells or delete rows below, then press **Save changes**. Every save is a commit to the repo when GitHub sync is on.")
    edited = st.data_editor(
        runs_df(), num_rows="dynamic", hide_index=True, use_container_width=True,
        column_config={
            "date": st.column_config.DateColumn("date", required=True),
            "type": st.column_config.SelectboxColumn("type", options=plan.RUN_TYPES),
            "distance_km": st.column_config.NumberColumn("distance_km", format="%.2f"),
        },
        key="log_editor",
    )
    c1, c2 = st.columns([1, 3])
    if c1.button("💾 Save changes"):
        ok, msg = storage.save_runs(edited)
        set_runs(edited if not ok else storage.load_runs()[0])
        (st.success if ok else st.error)(msg)
        st.rerun()
    c2.download_button("⬇ Download runs.csv", runs_df().to_csv(index=False),
                       "runs.csv", "text/csv")

# ---------------------------------------------------------------- progress
with tab_progress:
    if running.empty:
        st.info("No runs logged yet — add your first run in the **Log runs** tab and the charts fill in.")
    else:
        base_axis = alt.Axis(gridColor=C_GRID, domainColor=C_GRID, labelColor=C_MUTED, titleColor=C_MUTED)
        weeks = pd.DataFrame({"week": range(1, plan.TOTAL_WEEKS + 1)})
        weeks["Planned"] = [plan.weekly_target_km(i) for i in range(plan.TOTAL_WEEKS)]
        actual_w = running.groupby("week", as_index=False)["distance_km"].sum().rename(
            columns={"distance_km": "Actual"})
        weekly = weeks.merge(actual_w, on="week", how="left")

        st.subheader("Weekly volume — actual vs plan")
        bars = alt.Chart(weekly).mark_bar(color=C_ACTUAL, width={"band": 0.55}, cornerRadiusTopLeft=3,
                                          cornerRadiusTopRight=3).encode(
            x=alt.X("week:O", title="plan week", axis=base_axis),
            y=alt.Y("Actual:Q", title="km", axis=base_axis),
            tooltip=[alt.Tooltip("week:O", title="Week"),
                     alt.Tooltip("Actual:Q", title="Actual km", format=".1f"),
                     alt.Tooltip("Planned:Q", title="Target km", format=".0f")],
        )
        target_line = alt.Chart(weekly).mark_line(color=C_PLAN, strokeWidth=2, interpolate="step-after").encode(
            x="week:O", y="Planned:Q")
        st.altair_chart(
            (bars + target_line).properties(height=260).configure_view(strokeWidth=0),
            use_container_width=True)
        st.caption("🟩 actual logged km · 🟦 line = the plan's weekly target (25 → 60 km, taper in Month 9)")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Long run progression")
            lr = running.groupby("week", as_index=False)["distance_km"].max().rename(
                columns={"distance_km": "Longest"})
            peaks = pd.DataFrame({
                "week": [m * 4 for m in plan.MONTHLY_LONG_PEAK],
                "Peak target": list(plan.MONTHLY_LONG_PEAK.values()),
            })
            lr_line = alt.Chart(lr).mark_line(color=C_PLAN, strokeWidth=2, point=alt.OverlayMarkDef(
                color=C_PLAN, size=60, stroke="#ffffff", strokeWidth=2)).encode(
                x=alt.X("week:Q", title="plan week", scale=alt.Scale(domain=[1, 36]), axis=base_axis),
                y=alt.Y("Longest:Q", title="km", axis=base_axis),
                tooltip=[alt.Tooltip("week:Q", title="Week"),
                         alt.Tooltip("Longest:Q", title="Longest run km", format=".1f")],
            )
            peak_line = alt.Chart(peaks).mark_line(color=C_MUTED, strokeWidth=1.5,
                                                   interpolate="step-after").encode(
                x="week:Q", y="Peak target:Q",
                tooltip=[alt.Tooltip("Peak target:Q", title="Month-end LR target")])
            st.altair_chart((peak_line + lr_line).properties(height=240).configure_view(strokeWidth=0),
                            use_container_width=True)
            st.caption("🟦 your longest run each week · ⬜ gray steps = month-end long-run targets (peak 32 km in M8)")

        with col2:
            st.subheader("Z2 efficiency — avg HR on easy & long runs")
            z2 = running[running["type"].isin(["Easy Z2", "Long Run", "Med Long"])].dropna(subset=["avg_hr"])
            if z2.empty:
                st.info("Log avg HR on easy/long runs to track aerobic efficiency here.")
            else:
                band = alt.Chart(pd.DataFrame({"lo": [plan.Z2_RANGE[0]], "hi": [plan.Z2_RANGE[1]]})).mark_rect(
                    color=C_PLAN, opacity=0.1).encode(
                    y=alt.Y("lo:Q", scale=alt.Scale(domain=[110, 180])), y2="hi:Q")
                hr_line = alt.Chart(z2).mark_line(color=C_PLAN, strokeWidth=2, point=alt.OverlayMarkDef(
                    color=C_PLAN, size=60, stroke="#ffffff", strokeWidth=2)).encode(
                    x=alt.X("date:T", title=None, axis=base_axis),
                    y=alt.Y("avg_hr:Q", title="avg HR (bpm)",
                            scale=alt.Scale(domain=[110, 180]), axis=base_axis),
                    tooltip=[alt.Tooltip("date:T", title="Date"),
                             alt.Tooltip("type:N", title="Type"),
                             alt.Tooltip("avg_hr:Q", title="Avg HR"),
                             alt.Tooltip("avg_pace:N", title="Pace")],
                )
                st.altair_chart((band + hr_line).properties(height=240).configure_view(strokeWidth=0),
                                use_container_width=True)
                st.caption("Shaded band = Zone 2 (128–141 bpm). The line should stay in the band while pace slowly improves.")

        st.subheader("Monthly summary")
        msum = running.groupby("month").agg(
            runs=("distance_km", "count"), km=("distance_km", "sum"),
            longest=("distance_km", "max"), avg_hr=("avg_hr", "mean")).reset_index()
        msum["weekly target"] = msum["month"].map(plan.MONTHLY_KM)
        msum["km"] = msum["km"].round(1)
        msum["avg_hr"] = msum["avg_hr"].round(0)
        st.dataframe(msum, hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- training plan
with tab_plan:
    st.subheader("Training phases — 9 months")
    cols = st.columns(3)
    for col, p in zip(cols, plan.PHASES):
        active = p["num"] == CUR_PHASE["num"] and 0 <= WI < plan.TOTAL_WEEKS
        with col:
            box = st.container(border=True)
            box.markdown(f"**{'▶ ' if active else ''}Phase {p['num']}: {p['name']}**")
            box.caption(p["period"])
            box.markdown(
                f"- Weekly mileage: **{p['mileage']}**\n"
                f"- Long run peak: **{p['long_run_peak']}**\n"
                f"- Tempo: {p['tempo']}\n"
                f"- {p['extra']}\n"
                f"- {p['distribution']}"
            )

    st.subheader("Weekly mileage progression")
    mkm = pd.DataFrame({"month": list(plan.MONTHLY_KM), "km/week": list(plan.MONTHLY_KM.values())})
    mkm["state"] = ["current" if m == CUR_MONTH else "other" for m in mkm["month"]]
    mile = alt.Chart(mkm).mark_bar(width={"band": 0.5}, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("month:O", title="plan month"),
        y=alt.Y("km/week:Q", title="km per week"),
        color=alt.Color("state:N", legend=None,
                        scale=alt.Scale(domain=["current", "other"], range=[C_PLAN, "#9ec5f4"])),
        tooltip=[alt.Tooltip("month:O", title="Month"), alt.Tooltip("km/week:Q", title="Weekly km")],
    ).properties(height=200).configure_view(strokeWidth=0)
    st.altair_chart(mile, use_container_width=True)
    st.caption("Dark bar = current month. Month 9 drops to 32 km/week — that's the taper, not a slump.")

    st.subheader("Weekly session structure")
    st.dataframe(pd.DataFrame([
        {"Day": s["day"], "Type": s["type"],
         "Phase 1 (M1–3)": s[1], "Phase 2 (M4–6)": s[2], "Phase 3 (M7–9)": s[3],
         "HR target": s["hr"]}
        for s in plan.WEEKLY_SESSIONS
    ]), hide_index=True, use_container_width=True)

    st.subheader(f"Heart-rate zones (Karvonen · max {plan.ATHLETE['max_hr']} · rest {plan.ATHLETE['resting_hr']})")
    zcols = st.columns(5)
    for zc, z in zip(zcols, plan.HR_ZONES):
        with zc:
            b = st.container(border=True)
            b.markdown(f"**{z['zone']}**")
            b.markdown(f"### {z['bpm']}")
            b.caption(f"{z['pct']} · {z['desc']}")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Phase milestones")
        for m, text in plan.MILESTONES.items():
            done = m < CUR_MONTH
            here = m == CUR_MONTH
            icon = "✅" if done else ("👉" if here else "⬜")
            st.markdown(f"{icon} **Month {m}:** {text}")
    with col2:
        st.subheader("Running-economy targets")
        for t in plan.ECONOMY_TARGETS:
            st.markdown(f"- {t}")
        st.subheader("Key numbers")
        kn = st.columns(2)
        for i, (label, val, sub) in enumerate(plan.KEY_NUMBERS):
            kn[i % 2].markdown(f"**{val}** — {label} ({sub})")

# ---------------------------------------------------------------- race strategy
with tab_race:
    offset = plan.STRETCH_OFFSET_S if STRETCH else 0
    tgt = plan.RACE["stretch"] if STRETCH else plan.RACE["goal"]
    st.subheader(f"Race-day strategy — {tgt} target")
    if STRETCH:
        st.caption("Stretch-goal paces: each segment ~10 s/km faster per plan v2. "
                   "Only race this if the Month 6 tune-up HM went sub-1:44.")
    st.markdown(f"**The rule:** " + " → ".join(
        s_to_pace(pace_to_s(seg["pace"]) - offset) for seg in plan.RACE_STRATEGY) + " /km")

    scols = st.columns(4)
    for sc, seg in zip(scols, plan.RACE_STRATEGY):
        with sc:
            b = st.container(border=True)
            b.markdown(f"**{seg['km']} · {seg['phase']}**")
            b.markdown(f"### {s_to_pace(pace_to_s(seg['pace']) - offset)}/km")
            b.caption(f"{seg['zone']}" + ("" if STRETCH else f" · {seg['split']}"))
            b.caption(seg["note"])

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Gut-check splits (Sub-3:50 pacing)")
        st.dataframe(pd.DataFrame(plan.GUT_CHECKS).rename(
            columns={"km": "At", "time": "Clock", "note": "Check"}),
            hide_index=True, use_container_width=True)
    with col2:
        st.subheader("Gel plan — 6 gels")
        st.dataframe(pd.DataFrame(plan.GEL_PLAN).rename(
            columns={"at": "At", "gel": "Gel", "note": "Note"}),
            hide_index=True, use_container_width=True)
        st.error(plan.WALL_WARNING)

    st.subheader("Performance projections")
    pcols = st.columns(4)
    for pc, proj in zip(pcols, plan.PROJECTIONS):
        with pc:
            b = st.container(border=True)
            b.caption(proj["when"])
            b.markdown(f"HM **{proj['hm']}**")
            b.markdown(f"FM **{proj['fm']}**")
            b.caption(proj["note"])
    st.info("🔀 " + plan.RACE["decision"])
