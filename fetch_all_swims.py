"""Fetch every eo SwimBETTER session and all detail data via the eolab API."""

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
PAGE_SIZE = 50


def signin(session: requests.Session, email: str, password: str) -> tuple[str, str]:
    r = session.post(f"{API_URL}signin/email", json={"email": email, "password": password})
    r.raise_for_status()
    payload = r.json()
    if not payload.get("data"):
        raise RuntimeError(f"Login failed: {payload}")
    return payload["data"]["accessToken"], payload["data"]["id"]


def _extract_items(payload):
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


def _extract_total_pages(payload) -> int | None:
    if isinstance(payload, dict):
        for key in ("totalPages", "pageCount", "totalPage"):
            if isinstance(payload.get(key), int):
                return payload[key]
        for v in payload.values():
            found = _extract_total_pages(v)
            if found is not None:
                return found
    return None


def search_page(session: requests.Session, user_id: str, timezone: str, page: int) -> tuple[list, int | None]:
    body = {
        "dateTimeFilter": {
            "time": 5,
            "customStartDate": "",
            "customEndDate": "",
            "customString": "all",
            "timezone": timezone,
        },
        "userId": user_id,
    }
    r = session.post(
        f"{API_URL}swim/data/search?pageSize={PAGE_SIZE}&pageNo={page}&locale=en_US",
        json=body,
    )
    r.raise_for_status()
    payload = r.json()
    items = _extract_items(payload) or []
    total_pages = _extract_total_pages(payload)
    return items, total_pages


def get_json(session: requests.Session, path: str) -> dict:
    r = session.get(f"{API_URL}{path}")
    r.raise_for_status()
    return r.json()["data"]


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


def save(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        path.write_text(str(payload))


def fetch_swim_detail(session: requests.Session, swim_id: str, swim_date: str, out_root: Path) -> Path:
    date_part = swim_date[:10] if swim_date else "unknown"
    out_dir = out_root / f"{date_part}_{swim_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    swim_data = get_json(session, f"swim/data?locale=en_us&Id={swim_id}")
    save(out_dir / "swim.json", swim_data)

    try:
        lap_force = get_json(session, f"swim/chart/lapforcetime-swim?locale=en_US&swimId={swim_id}")
        save(out_dir / "lapforcetime.json", lap_force)
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

    return out_dir


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

    all_items: list[dict] = []
    page = 1
    while True:
        items, total_pages = search_page(session, user_id, timezone, page)
        all_items.extend(items)
        print(f"page {page}: {len(items)} swims (total so far: {len(all_items)})")
        if not items or (total_pages and page >= total_pages):
            break
        page += 1

    if not all_items:
        print("No swims found.")
        return 0

    DATA_DIR.mkdir(exist_ok=True)
    index = []
    for i, item in enumerate(all_items, 1):
        swim_id = item.get("swimId")
        swim_date = item.get("swimDate") or item.get("date") or ""
        if not swim_id:
            continue
        print(f"[{i}/{len(all_items)}] {swim_id} ({swim_date[:10]})")
        out_dir = fetch_swim_detail(session, swim_id, swim_date, DATA_DIR)
        index.append({
            "swimId": swim_id,
            "swimDate": swim_date,
            "dir": str(out_dir.relative_to(DATA_DIR.parent)),
            "comments": [c.get("content") for c in (item.get("comments") or [])],
        })

    save(DATA_DIR / "_index.json", {
        "fetchedAt": datetime.utcnow().isoformat() + "Z",
        "count": len(index),
        "swims": index,
    })
    print(f"Done. {len(index)} swims saved to {DATA_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
