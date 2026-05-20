"""Fetch the most recent eo SwimBETTER session via the eolab API."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

API_URL = "https://api.app.eolab.com/"
DATA_DIR = Path("data")


def signin(session: requests.Session, email: str, password: str) -> tuple[str, str]:
    r = session.post(f"{API_URL}signin/email", json={"email": email, "password": password})
    r.raise_for_status()
    payload = r.json()
    if not payload.get("data"):
        raise RuntimeError(f"Login failed: {payload}")
    return payload["data"]["accessToken"], payload["data"]["id"]


def search_latest_swim(session: requests.Session, user_id: str, timezone: str) -> dict:
    body = {
        "dateTimeFilter": {
            "time": 3,
            "customStartDate": "",
            "customEndDate": "",
            "customString": "ninety-days",
            "timezone": timezone,
        },
        "userId": user_id,
    }
    r = session.post(
        f"{API_URL}swim/data/search?pageSize=1&pageNo=1&locale=en_US",
        json=body,
    )
    r.raise_for_status()
    payload = r.json()
    items = _extract_items(payload)
    if items is None:
        raise RuntimeError(
            f"Could not locate 'items' in search response. Top-level keys: "
            f"{list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}. "
            f"Full payload: {json.dumps(payload)[:1500]}"
        )
    if not items:
        raise RuntimeError("No swim sessions found in the last 90 days.")
    return items[0]


def _extract_items(payload):
    """Recursively find the first list under an 'items' key."""
    if isinstance(payload, dict):
        if "items" in payload and isinstance(payload["items"], list):
            return payload["items"]
        for v in payload.values():
            found = _extract_items(v)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for v in payload:
            found = _extract_items(v)
            if found is not None:
                return found
    return None


def get_json(session: requests.Session, path: str) -> dict:
    r = session.get(f"{API_URL}{path}")
    r.raise_for_status()
    return r.json()["data"]


def detect_lap_count(swim_data) -> int:
    """Find the number of laps from the main swim data payload."""
    if isinstance(swim_data, dict):
        for key in ("laps", "lapList", "lapData", "lapMetrics"):
            val = swim_data.get(key)
            if isinstance(val, list) and val:
                return len(val)
        for key in ("lapCount", "totalLaps", "numLaps"):
            val = swim_data.get(key)
            if isinstance(val, int) and val > 0:
                return val
    return 0


def save(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        path.write_text(str(payload))


def main() -> int:
    load_dotenv()
    email = os.environ.get("EO_EMAIL")
    password = os.environ.get("EO_PASSWORD")
    timezone = os.environ.get("EO_TIMEZONE", "Europe/Amsterdam")

    if not email or not password:
        print("Set EO_EMAIL and EO_PASSWORD in .env (copy from .env.example).", file=sys.stderr)
        return 1

    session = requests.Session()
    access_token, user_id = signin(session, email, password)
    session.headers.update({"Authorization": f"Bearer {access_token}"})
    print(f"Logged in as user {user_id}")

    latest = search_latest_swim(session, user_id, timezone)
    swim_id = latest["swimId"]
    swim_date = latest["swimDate"]
    print(f"Latest swim: {swim_id} on {swim_date}")

    out_dir = DATA_DIR / f"{swim_date[:10]}_{swim_id}"
    print(f"Saving to {out_dir}/")

    swim_data = get_json(session, f"swim/data?locale=en_us&Id={swim_id}")
    save(out_dir / "swim.json", swim_data)

    lap_force = get_json(session, f"swim/chart/lapforcetime-swim?locale=en_US&swimId={swim_id}")
    save(out_dir / "lapforcetime.json", lap_force)

    lap_count = detect_lap_count(swim_data)
    if lap_count == 0:
        print("Could not determine lap count from swim data; probing laps until empty.")
        lap_count = 50  # upper bound, will break on first empty

    for lap in range(1, lap_count + 1):
        try:
            sweep = get_json(session, f"swim/chart/pathsweep?locale=en_US&swimId={swim_id}&lap={lap}")
            depth = get_json(session, f"swim/chart/pathdepth?locale=en_US&swimId={swim_id}&lap={lap}")
            phase = get_json(session, f"swim/chart/strokephase?locale=en_US&swimId={swim_id}&lap={lap}")
        except requests.HTTPError as exc:
            print(f"Stopped at lap {lap}: {exc}")
            break
        if not sweep and not depth and not phase:
            break
        save(out_dir / f"lap-{lap:02d}-pathsweep.json", sweep)
        save(out_dir / f"lap-{lap:02d}-pathdepth.json", depth)
        save(out_dir / f"lap-{lap:02d}-strokephase.json", phase)
        print(f"  lap {lap} saved")

    summary = {
        "swimId": swim_id,
        "swimDate": swim_date,
        "fetchedAt": datetime.utcnow().isoformat() + "Z",
        "comments": [c.get("content") for c in latest.get("comments", [])],
    }
    save(out_dir / "_meta.json", summary)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
