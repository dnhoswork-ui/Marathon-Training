"""Run-log persistence: data/runs.csv, committed back to GitHub when configured.

Modes
-----
- GITHUB_TOKEN in Streamlit secrets  -> read/write data/runs.csv in the repo
  via the GitHub contents API (each save is a commit).
- No token                            -> read/write the local file only
  (fine for local use; ephemeral on Streamlit Community Cloud — the app
  offers a CSV download as a manual fallback).
"""

import base64
import io
import os
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

RUNS_PATH = "data/runs.csv"
LOCAL_RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), RUNS_PATH)
COLUMNS = [
    "date", "date_precision", "phase", "run_type", "surface", "distance_km", "duration",
    "avg_pace", "pace_sec_per_km", "avg_hr", "cadence_spm", "vertical_osc_cm", "gct_ms",
    "grade", "grade_points", "shoe", "feels_like_c", "hr_first_half", "hr_second_half", "notes",
]
NUMERIC = ["distance_km", "pace_sec_per_km", "avg_hr", "cadence_spm", "vertical_osc_cm",
           "gct_ms", "grade_points", "feels_like_c", "hr_first_half", "hr_second_half"]
API = "https://api.github.com"


def _secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # no secrets.toml at all
        return default


def github_config() -> dict | None:
    token = _secret("GITHUB_TOKEN")
    if not token:
        return None
    return {
        "token": token,
        "repo": _secret("GITHUB_REPO", "dnhoswork-ui/Marathon-Training"),
        "branch": _secret("GITHUB_BRANCH", "main"),
    }


def _headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json"}


def _contents_url(cfg: dict) -> str:
    return f"{API}/repos/{cfg['repo']}/contents/{RUNS_PATH}"


def empty_runs() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


def load_runs() -> tuple[pd.DataFrame, str]:
    """Returns (runs, source_label). Never raises — falls back to empty."""
    cfg = github_config()
    if cfg:
        try:
            r = requests.get(_contents_url(cfg), headers=_headers(cfg),
                             params={"ref": cfg["branch"]}, timeout=15)
            if r.status_code == 404:
                return empty_runs(), f"GitHub · {cfg['repo']}@{cfg['branch']} (new file)"
            r.raise_for_status()
            raw = base64.b64decode(r.json()["content"])
            df = _clean(pd.read_csv(io.BytesIO(raw)))
            return df, f"GitHub · {cfg['repo']}@{cfg['branch']}"
        except Exception as e:
            st.warning(f"Couldn't read runs.csv from GitHub ({e}); using local copy.")
    if os.path.exists(LOCAL_RUNS):
        try:
            return _clean(pd.read_csv(LOCAL_RUNS)), "local file"
        except Exception:
            pass
    return empty_runs(), "local file (empty)"


def save_runs(df: pd.DataFrame) -> tuple[bool, str]:
    """Persist runs. Writes local always; commits to GitHub when configured."""
    df = _clean(df)
    os.makedirs(os.path.dirname(LOCAL_RUNS), exist_ok=True)
    df.to_csv(LOCAL_RUNS, index=False)

    cfg = github_config()
    if not cfg:
        return True, "Saved locally. Add a GITHUB_TOKEN secret to sync to the repo."

    try:
        url = _contents_url(cfg)
        # current sha (required by the contents API for updates)
        sha = None
        r = requests.get(url, headers=_headers(cfg), params={"ref": cfg["branch"]}, timeout=15)
        if r.status_code == 200:
            sha = r.json()["sha"]
        elif r.status_code != 404:
            r.raise_for_status()

        payload = {
            "message": f"Update run log ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)",
            "content": base64.b64encode(df.to_csv(index=False).encode()).decode(),
            "branch": cfg["branch"],
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(url, headers=_headers(cfg), json=payload, timeout=20)
        r.raise_for_status()
        return True, f"Committed to {cfg['repo']}@{cfg['branch']}"
    except Exception as e:
        return False, f"Saved locally, but the GitHub commit failed: {e}"
