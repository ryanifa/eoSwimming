"""List eo SwimBETTER swims for a given date as a GitHub Actions job summary."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

API_URL = "https://api.app.eolab.com/"
PAGE_SIZE = 50


def signin(session: requests.Session, email: str, password: str) -> tuple[str, str]:
    r = session.post(f"{API_URL}signin/email", json={"email": email, "password": password})
    r.raise_for_status()
    payload = r.json()
    if not payload.get("data"):
        raise RuntimeError(f"Login failed: {payload}")
    return payload["data"]["accessToken"], payload["data"]["id"]


def _find_items(payload):
    if isinstance(payload, dict):
        if "items" in payload and isinstance(payload["items"], list):
            return payload["items"]
        for v in payload.values():
            f = _find_items(v)
            if f is not None:
                return f
    elif isinstance(payload, list):
        for v in payload:
            f = _find_items(v)
            if f is not None:
                return f
    return None


def _find_total_pages(payload):
    if isinstance(payload, dict):
        for k in ("totalPages", "pageCount", "totalPage"):
            if isinstance(payload.get(k), int):
                return payload[k]
        for v in payload.values():
            f = _find_total_pages(v)
            if f is not None:
                return f
    return None


def search_swims(session: requests.Session, user_id: str, timezone: str, target_date: date) -> list[dict]:
    """Fetch swims on `target_date` by asking the API for that exact day."""
    if (date.today() - target_date).days < 0:
        return []

    target_iso = target_date.isoformat()
    start_iso = target_iso
    end_iso = (target_date + timedelta(days=1)).isoformat()

    body = {
        "dateTimeFilter": {
            "time": 5,
            "customStartDate": start_iso,
            "customEndDate": end_iso,
            "customString": "custom",
            "timezone": timezone,
        },
        "userId": user_id,
    }

    matched: list[dict] = []
    page = 1
    while True:
        r = session.post(
            f"{API_URL}swim/data/search?pageSize={PAGE_SIZE}&pageNo={page}&locale=en_US",
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        items = _find_items(payload) or []
        if not items:
            break
        passed_target = False
        for it in items:
            swim_date_str = (it.get("swimDate") or it.get("date") or "")[:10]
            if swim_date_str == target_iso:
                matched.append(it)
            elif swim_date_str and swim_date_str < target_iso:
                passed_target = True
        if passed_target:
            break
        total_pages = _find_total_pages(payload)
        if total_pages and page >= total_pages:
            break
        if len(items) < PAGE_SIZE:
            break
        page += 1
    return matched


def _comments_text(item: dict) -> str:
    comments = item.get("comments") or []
    parts = []
    for c in comments:
        if isinstance(c, dict):
            content = c.get("content") or c.get("text") or ""
            if content:
                parts.append(content)
        elif isinstance(c, str):
            parts.append(c)
    return " · ".join(parts) if parts else ""


def _candidate_filename(item: dict) -> str:
    for key in ("originalFileName", "fileName", "filename", "deviceFileName",
                "recordingName", "recordingId", "swimIDString", "deviceId"):
        v = item.get(key)
        if v:
            return f"{key}={v}"
    return ""


def render_summary(target_date: date, items: list[dict]) -> str:
    out: list[str] = []
    out.append(f"# Swims on {target_date.isoformat()}")
    out.append("")
    if not items:
        out.append(f"_No swims found for {target_date.isoformat()}._")
        out.append("")
        out.append("Re-run this workflow with a different `date` input.")
        return "\n".join(out)

    out.append(f"Found **{len(items)}** swim(s). Re-run this workflow with `swim_id` set to the row you want analysed.")
    out.append("")
    out.append("| # | Time | Distance | Stroke | Duration | Laps | Notes (swimmer) | Device / file hint | Favorite | swim_id |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, it in enumerate(items, 1):
        swim_date = it.get("swimDate") or it.get("date") or ""
        time_str = swim_date[11:16] if len(swim_date) >= 16 else ""
        distance = it.get("distance") or ""
        unit = it.get("unitDistance") or "m"
        stroke = it.get("stroke") or ""
        dur_ms = it.get("duration") or 0
        dur_str = f"{dur_ms / 1000:.2f}s" if dur_ms else ""
        laps = it.get("laps") or ""
        notes = _comments_text(it)
        fname = _candidate_filename(it)
        fav = "⭐" if it.get("isFavorite") else ""
        swim_id = it.get("swimId") or ""
        out.append(
            f"| {i} | {time_str} | {distance} {unit} | {stroke} | {dur_str} | {laps} | "
            f"{notes or '_(empty)_'} | {fname or '_(none)_'} | {fav} | `{swim_id}` |"
        )
    out.append("")
    out.append("## How to analyse one")
    out.append("")
    out.append("1. Copy a `swim_id` from the table above.")
    out.append(f"2. Re-run this workflow with `date = {target_date.isoformat()}` and `swim_id = <pasted value>`.")
    out.append("3. After the run completes, download the artifact (contains `lapforcetime.json` for the sync tool, plots, analysis.md).")
    out.append("")
    out.append("## Raw fields per swim")
    out.append("")
    out.append("If you want a column added (e.g. for the handheld device's original filename), expand a row below and tell which key holds it.")
    out.append("")
    for i, it in enumerate(items, 1):
        out.append(f"<details><summary>Swim {i}: <code>{it.get('swimId', '')}</code></summary>")
        out.append("")
        out.append("```json")
        out.append(json.dumps(it, indent=2, ensure_ascii=False))
        out.append("```")
        out.append("</details>")
        out.append("")
    return "\n".join(out)


def main() -> int:
    load_dotenv()
    email = os.environ.get("EO_EMAIL")
    password = os.environ.get("EO_PASSWORD")
    timezone = os.environ.get("EO_TIMEZONE", "Europe/Amsterdam")
    date_str = os.environ.get("SWIM_DATE") or os.environ.get("DATE") or ""

    if not email or not password:
        print("Set EO_EMAIL and EO_PASSWORD.", file=sys.stderr)
        return 1

    if not date_str:
        target_date = date.today()
    else:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            print(f"Bad date: {date_str!r}. Use YYYY-MM-DD.", file=sys.stderr)
            return 1

    session = requests.Session()
    access_token, user_id = signin(session, email, password)
    session.headers.update({"Authorization": f"Bearer {access_token}"})

    items = search_swims(session, user_id, timezone, target_date)
    summary = render_summary(target_date, items)
    print(summary)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
