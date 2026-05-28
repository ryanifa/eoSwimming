"""Prototype: reconstruct eo's "Force Field / Distribution of Power" view.

Reads a swim's lapforcetime.json (time + per-hand force components) and produces:
  - the six-direction power distribution (Propulsive / Hand Drag / Upward /
    Downward / Left / Right) as percentages, and
  - the radial "fan" plot (each time sample is a ray, orange = left hand,
    blue = right hand).

The orientation/axis convention the eo app uses for the 2D fan is not
documented, so the projection is controlled by the knobs below. Once we see a
real swim we tune these so the fan matches the app; the percentages themselves
do not depend on the projection.

Usage:
    python force_field.py <swim_dir> [--out force_field.png]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# --- convention (calibrated against a real swim; see notes below) -----------
# forward > 0  -> Propulsive,  < 0 -> Hand Drag
# vertical > 0 -> Upward,      < 0 -> Downward
# lateral      -> Left / Right, but the right hand's lateral sign is mirrored
#                 (without this the two hands' percentages don't match the app).
# The fan plots forward up and lateral sideways (right hand mirrored), which
# reproduces the app's crossed orange/blue fan.
RIGHT_LATERAL_FLIP = True
PROJ_Y = "forward"   # fan vertical axis
PROJ_X = "lateral"   # fan horizontal axis
PROPULSIVE_DOWN = True  # draw propulsive pointing down (matches the app); left hand stays on the left
# ----------------------------------------------------------------------------

LEFT_COLOR = "#f5a04b"
RIGHT_COLOR = "#3aa0f5"


def comp(side: dict, key: str, mask: np.ndarray | None = None) -> np.ndarray:
    a = np.asarray(side.get(key) or [], dtype=float)
    if mask is not None and len(mask) >= len(a):
        a = a[mask[:len(a)]]
    return a


def lateral(side: dict, name: str, mask: np.ndarray | None = None) -> np.ndarray:
    a = comp(side, "lateral", mask)
    if RIGHT_LATERAL_FLIP and name == "right":
        a = -a
    return a


def load_swim(swim_dir: Path) -> dict:
    d = json.loads((swim_dir / "lapforcetime.json").read_text())
    return d[0] if isinstance(d, list) and d else d


def lap_window(swim_dir: Path, lap: int) -> tuple[float, float] | None:
    """Time window (ms) of a lap, from its strokephase chartScale."""
    f = swim_dir / f"lap-{lap:02d}-strokephase.json"
    if not f.exists():
        return None
    cs = (json.loads(f.read_text()) or {}).get("chartScale") or {}
    lo, hi = cs.get("minTime"), cs.get("maxTime")
    return (float(lo), float(hi)) if lo is not None and hi is not None else None


def make_mask(d: dict, window: tuple[float, float] | None) -> np.ndarray | None:
    if window is None:
        return None
    t = np.asarray(d.get("time") or [], dtype=float)
    lo, hi = window
    return (t >= lo) & (t <= hi)


def distribution(d: dict, mask: np.ndarray | None = None, weight: str = "force") -> dict:
    """Six-direction power split over both hands, normalised to 100%."""
    b = dict.fromkeys(
        ("propulsive", "hand_drag", "upward", "downward", "left", "right"), 0.0)
    for name in ("left", "right"):
        side = d.get(name) or {}
        f = comp(side, "forward", mask)
        v = comp(side, "vertical", mask)
        lat = lateral(side, name, mask)
        w = comp(side, "handVelocity", mask) if weight == "power" else np.ones_like(f)
        b["propulsive"] += float((np.clip(f, 0, None) * w).sum())
        b["hand_drag"] += float((np.clip(-f, 0, None) * w).sum())
        b["upward"] += float((np.clip(v, 0, None) * w).sum())
        b["downward"] += float((np.clip(-v, 0, None) * w).sum())
        b["left"] += float((np.clip(lat, 0, None) * w).sum())
        b["right"] += float((np.clip(-lat, 0, None) * w).sum())
    total = sum(b.values()) or 1.0
    return {k: 100.0 * v / total for k, v in b.items()}


def mean_power(swim_dir: Path, side: str, lap: int | None) -> float | None:
    """Average power per stroke for a side, from strokephase PPS arrays."""
    key = "PPSLeft" if side == "left" else "PPSRight"
    if lap is not None:
        files = [swim_dir / f"lap-{lap:02d}-strokephase.json"]
    else:
        files = sorted(swim_dir.glob("lap-*-strokephase.json"))
    vals: list[float] = []
    for f in files:
        if not f.exists():
            continue
        ind = (json.loads(f.read_text()) or {}).get("indicator", {})
        vals.extend(v for v in (ind.get(key) or []) if v is not None)
    return sum(vals) / len(vals) if vals else None


def draw_fan(ax, side: dict, name: str, color: str, mask) -> None:
    x = lateral(side, name, mask) if PROJ_X == "lateral" else comp(side, PROJ_X, mask)
    y = comp(side, PROJ_Y, mask)
    if PROPULSIVE_DOWN:
        y = -y
    n = min(len(x), len(y))
    for xi, yi in zip(x[:n], y[:n]):
        ax.plot([0, xi], [0, yi], color=color, alpha=0.12, linewidth=0.8,
                solid_capstyle="round")


def build_figure(swim_dir: Path, lap: int | None, weight: str) -> plt.Figure:
    d = load_swim(swim_dir)
    window = lap_window(swim_dir, lap) if lap is not None else None
    mask = make_mask(d, window)
    left, right = d.get("left") or {}, d.get("right") or {}
    dist = distribution(d, mask, weight)
    pl, pr = mean_power(swim_dir, "left", lap), mean_power(swim_dir, "right", lap)

    fig, ax = plt.subplots(figsize=(7, 7))
    fig.patch.set_facecolor("#f4f4f4")
    ax.set_facecolor("#f4f4f4")

    # reference rings
    span = 0.0
    for side in (left, right):
        for k in (PROJ_X, PROJ_Y):
            c = comp(side, k, mask)
            if c.size:
                span = max(span, float(np.abs(c).max()))
    span = span or 1.0
    for r in np.linspace(span / 4, span, 4):
        ax.add_patch(plt.Circle((0, 0), r, fill=False, color="#d8d8d8", lw=1))
    ax.axhline(0, color="#d0d0d0", lw=1)
    ax.axvline(0, color="#d0d0d0", lw=1)

    draw_fan(ax, left, "left", LEFT_COLOR, mask)
    draw_fan(ax, right, "right", RIGHT_COLOR, mask)

    ax.set_aspect("equal")
    ax.set_xlim(-span * 1.15, span * 1.15)
    ax.set_ylim(-span * 1.15, span * 1.15)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    rows = [
        ("Left", dist["left"], "Propulsive", dist["propulsive"], "Right", dist["right"]),
        ("Upward", dist["upward"], "Hand Drag", dist["hand_drag"], "Downward", dist["downward"]),
    ]
    head = "Distribution of Power" + (f" — Lap {lap}" if lap is not None else " — whole swim")
    txt = head + "\n"
    for a, av, b, bv, c, cv in rows:
        txt += f"\n{a} {av:.2f}%    {b} {bv:.2f}%    {c} {cv:.2f}%"
    ax.set_title(txt, fontsize=11, color="#444", loc="center")

    plabel = []
    if pl is not None:
        plabel.append(f"L {pl:.1f} W")
    if pr is not None:
        plabel.append(f"R {pr:.1f} W")
    if plabel:
        ax.text(0.5, -0.06, "   ".join(plabel), transform=ax.transAxes,
                ha="center", color="#666", fontsize=11)

    fig.tight_layout()
    return fig


def write_bundle(swim_dir: Path, out: Path) -> None:
    """Combine swim + lapforcetime + per-lap strokephase into one JSON the
    forcefield.html page can load from a gist via ?data=<raw-url>."""
    bundle: dict = {"lapforcetime": load_swim(swim_dir)}
    swim_file = swim_dir / "swim.json"
    if swim_file.exists():
        s = json.loads(swim_file.read_text())
        bundle["swim"] = s[0] if isinstance(s, list) and s else s
    phases: dict[str, dict] = {}
    for f in sorted(swim_dir.glob("lap-*-strokephase.json")):
        try:
            lap = int(f.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        phases[str(lap)] = json.loads(f.read_text())
    if phases:
        bundle["strokephase"] = phases
    out.write_text(json.dumps(bundle, separators=(",", ":")))
    print(f"wrote {out} ({len(phases)} laps)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("swim_dir")
    ap.add_argument("--lap", type=int, default=None,
                    help="restrict to one lap (uses that lap's strokephase time window)")
    ap.add_argument("--weight", choices=("force", "power"), default="force",
                    help="'force' = sum of force components; 'power' = force x hand speed")
    ap.add_argument("--bundle", action="store_true",
                    help="write a single forcefield-bundle.json (for the HTML page / a gist) instead of a plot")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    swim_dir = Path(args.swim_dir)
    if not (swim_dir / "lapforcetime.json").exists():
        print(f"No lapforcetime.json in {swim_dir}", file=sys.stderr)
        return 1

    if args.bundle:
        out = Path(args.out) if args.out else swim_dir / "forcefield-bundle.json"
        write_bundle(swim_dir, out)
        return 0

    suffix = f"-lap{args.lap:02d}" if args.lap is not None else ""
    out = Path(args.out) if args.out else swim_dir / f"force_field{suffix}.png"
    fig = build_figure(swim_dir, args.lap, args.weight)
    fig.savefig(out, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)

    d = load_swim(swim_dir)
    mask = make_mask(d, lap_window(swim_dir, args.lap) if args.lap is not None else None)
    dist = distribution(d, mask, args.weight)
    print(f"wrote {out}")
    print("  " + "  ".join(f"{k}={v:.2f}%" for k, v in dist.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
