"""Probe the eo API for a dedicated 'Distribution of Power' / force-field endpoint.

The app's Force Field percentages don't fall out of lapforcetime.json with any
simple formula, so they're almost certainly served by their own chart endpoint
(same shape as pathsweep/strokephase: swim/chart/<name>?swimId=..&lap=N).

This tries a list of likely names and reports which return data, saving any hits
to data/_probe/. Run it with your credentials:

    EO_EMAIL=... EO_PASSWORD=... SWIM_ID=<id> python probe_forcefield.py

Then tell me which endpoint returned the distribution and I'll wire it into the
fetchers and the Force Field page.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

API_URL = "https://api.app.eolab.com/"
OUT_DIR = Path("data") / "_probe"

CANDIDATES = [
    "forcefield", "force-field", "force_field",
    "powerdistribution", "power-distribution", "power_distribution",
    "distributionofpower", "distribution-of-power",
    "forcedistribution", "force-distribution",
    "distribution", "power", "forcevector", "force-vector",
    "lapforce", "lapforcefield", "powerfield",
]


def signin(session: requests.Session, email: str, password: str) -> str:
    r = session.post(f"{API_URL}signin/email", json={"email": email, "password": password})
    r.raise_for_status()
    payload = r.json()
    if not payload.get("data"):
        raise RuntimeError(f"Login failed: {payload}")
    return payload["data"]["accessToken"]


def try_endpoint(session: requests.Session, name: str, swim_id: str, lap: int | None) -> str:
    lap_q = f"&lap={lap}" if lap is not None else ""
    path = f"swim/chart/{name}?locale=en_US&swimId={swim_id}{lap_q}"
    try:
        r = session.get(f"{API_URL}{path}", timeout=20)
    except Exception as exc:
        return f"  [err] {name:24s} {exc}"
    if r.status_code != 200:
        return f"  [{r.status_code}] {name:24s}{lap_q}"
    try:
        data = r.json().get("data")
    except Exception:
        return f"  [200?] {name:24s} non-JSON body"
    if data in (None, [], {}):
        return f"  [empty] {name:24s}{lap_q}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fn = OUT_DIR / f"{name}{('-lap%d' % lap) if lap is not None else ''}.json"
    fn.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    keys = list(data.keys()) if isinstance(data, dict) else f"list[{len(data)}]"
    return f"  [HIT] {name:24s}{lap_q} -> {fn}  keys={keys}"


def main() -> int:
    load_dotenv()
    email = os.environ.get("EO_EMAIL")
    password = os.environ.get("EO_PASSWORD")
    swim_id = os.environ.get("SWIM_ID", "").strip()
    if not email or not password or not swim_id:
        print("Set EO_EMAIL, EO_PASSWORD and SWIM_ID.", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {signin(session, email, password)}"})

    print(f"Probing {len(CANDIDATES)} endpoint names for swim {swim_id}\n")
    for name in CANDIDATES:
        for lap in (1, None):
            line = try_endpoint(session, name, swim_id, lap)
            print(line)
            if "[HIT]" in line:
                break  # got it with lap=1, no need to retry without lap
    print(f"\nAny hits saved under {OUT_DIR}/. Send me one and I'll wire it in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
