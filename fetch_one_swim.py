"""Fetch a single swim by swim_id and write its detail data to data/."""

from __future__ import annotations

import json
import os
import sys
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


def get_json(session: requests.Session, path: str):
    r = session.get(f"{API_URL}{path}")
    r.raise_for_status()
    return r.json()["data"]


def save(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        path.write_text(str(payload))


def detect_lap_count(swim_data) -> int:
    if isinstance(swim_data, list) and swim_data:
        swim_data = swim_data[0]
    if isinstance(swim_data, dict):
        for key in ("laps", "lapCount", "totalLaps", "numLaps"):
            val = swim_data.get(key)
            if isinstance(val, int) and val > 0:
                return val
            if isinstance(val, list) and val:
                return len(val)
    return 0


def main() -> int:
    load_dotenv()
    email = os.environ.get("EO_EMAIL")
    password = os.environ.get("EO_PASSWORD")
    swim_id = os.environ.get("SWIM_ID", "").strip()

    if not email or not password:
        print("Set EO_EMAIL and EO_PASSWORD.", file=sys.stderr)
        return 1
    if not swim_id:
        print("Set SWIM_ID.", file=sys.stderr)
        return 1

    session = requests.Session()
    access_token, _ = signin(session, email, password)
    session.headers.update({"Authorization": f"Bearer {access_token}"})

    swim_data = get_json(session, f"swim/data?locale=en_us&Id={swim_id}")
    swim_obj = swim_data[0] if isinstance(swim_data, list) and swim_data else swim_data
    swim_date = (swim_obj or {}).get("date") or (swim_obj or {}).get("swimDate") or ""
    date_part = swim_date[:10] if swim_date else "unknown"

    out_dir = DATA_DIR / f"{date_part}_{swim_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    save(out_dir / "swim.json", swim_data)
    print(f"swim.json saved to {out_dir}")

    try:
        lf = get_json(session, f"swim/chart/lapforcetime-swim?locale=en_US&swimId={swim_id}")
        save(out_dir / "lapforcetime.json", lf)
    except requests.HTTPError as exc:
        print(f"  lapforcetime failed: {exc}")

    lap_count = detect_lap_count(swim_data) or 50
    for lap in range(1, lap_count + 1):
        try:
            sweep = get_json(session, f"swim/chart/pathsweep?locale=en_US&swimId={swim_id}&lap={lap}")
            depth = get_json(session, f"swim/chart/pathdepth?locale=en_US&swimId={swim_id}&lap={lap}")
            phase = get_json(session, f"swim/chart/strokephase?locale=en_US&swimId={swim_id}&lap={lap}")
        except requests.HTTPError as exc:
            print(f"  stopped at lap {lap}: {exc}")
            break
        if not sweep and not depth and not phase:
            break
        save(out_dir / f"lap-{lap:02d}-pathsweep.json", sweep)
        save(out_dir / f"lap-{lap:02d}-pathdepth.json", depth)
        save(out_dir / f"lap-{lap:02d}-strokephase.json", phase)
        print(f"  lap {lap} saved")

    print(f"Done: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
