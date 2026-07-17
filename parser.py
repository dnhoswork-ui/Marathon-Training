"""Screenshot → run data via the Claude API (vision + structured output).

Enabled when ANTHROPIC_API_KEY is present in Streamlit secrets. The app
degrades gracefully without it — manual entry always works.
"""

import base64
from typing import Optional

import streamlit as st
from pydantic import BaseModel, Field

MODEL = "claude-opus-4-8"

MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


class RunData(BaseModel):
    date: Optional[str] = Field(None, description="Run date as YYYY-MM-DD, or null if not visible")
    distance_km: Optional[float] = Field(None, description="Distance in kilometers (convert from miles if needed)")
    duration: Optional[str] = Field(None, description="Moving/elapsed time as H:MM:SS or MM:SS")
    avg_pace: Optional[str] = Field(None, description="Average pace as M:SS per km")
    avg_hr: Optional[int] = Field(None, description="Average heart rate in bpm, or null")
    cadence: Optional[int] = Field(None, description="Average cadence in steps per minute, or null")
    run_title: Optional[str] = Field(None, description="Activity title or short description shown in the app")


def api_key() -> str:
    try:
        return str(st.secrets.get("ANTHROPIC_API_KEY", ""))
    except Exception:
        return ""


def available() -> bool:
    return bool(api_key())


def parse_screenshot(data: bytes, filename: str) -> RunData:
    """Extract run fields from a Garmin/Strava/Coros screenshot."""
    import anthropic  # imported lazily so the app runs without the package configured

    ext = filename.rsplit(".", 1)[-1].lower()
    media_type = MEDIA_TYPES.get(ext, "image/png")

    client = anthropic.Anthropic(api_key=api_key())
    response = client.messages.parse(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(data).decode(),
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "This is a screenshot of a run from a fitness app (Garmin, Strava, Coros, "
                        "Apple Fitness, etc.). Extract the run's data. Use null for anything not "
                        "visible. Distances shown in miles must be converted to kilometers. If the "
                        "screenshot shows a relative date like 'Today' or 'Yesterday', return null "
                        "for the date rather than guessing."
                    ),
                },
            ],
        }],
        output_format=RunData,
    )
    if response.stop_reason == "refusal":
        raise ValueError("The model declined to process this image.")
    parsed = response.parsed_output
    if parsed is None:
        raise ValueError("Could not extract structured run data from the screenshot.")
    return parsed
