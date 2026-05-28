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

# --- calibration knobs (tune against a real swim) ---------------------------
PROJ_Y = "forward"   # component drawn along the fan's vertical (up) axis
PROJ_X = "lateral"   # component drawn along the fan's horizontal axis
FLIP_Y = False       # set True if propulsive should point down
FLIP_X = False       # set True to mirror left/right
# ----------------------------------------------------------------------------

LEFT_COLOR = "#f5a04b"
RIGHT_COLOR = "#3aa0f5"

# (key in JSON, positive-direction label, negative-direction label)
AXES = [
    ("forward", "propulsive", "hand_drag"),
    ("vertical", "upward", "downward"),
    ("lateral", "left", "right"),
]


def comp(side: dict, key: str) -> np.ndarray:
    return np.asarray(side.get(key) or [], dtype=float)


def load_sides(swim_dir: Path) -> tuple[dict, dict]:
    d = json.loads((swim_dir / "lapforcetime.json").read_text())
    if isinstance(d, list) and d:
        d = d[0]
    left = d.get("left") if isinstance(d.get("left"), dict) else {}
    right = d.get("right") if isinstance(d.get("right"), dict) else {}
    return left, right


def distribution(*sides: dict) -> dict:
    """Six-direction power split, summed over the given hands, normalised to 100%."""
    b = {}
    for side in sides:
        for key, pos, neg in AXES:
            c = comp(side, key)
            b[pos] = b.get(pos, 0.0) + float(np.clip(c, 0, None).sum())
            b[neg] = b.get(neg, 0.0) + float(np.clip(-c, 0, None).sum())
    total = sum(b.values()) or 1.0
    return {k: 100.0 * v / total for k, v in b.items()}


def mean_power(swim_dir: Path, side: str) -> float | None:
    """Average power per stroke for a side, from strokephase files if present."""
    vals: list[float] = []
    key = "PPSLeft" if side == "left" else "PPSRight"
    for f in sorted(swim_dir.glob("lap-*-strokephase.json")):
        try:
            ind = (json.loads(f.read_text()) or {}).get("indicator", {})
        except Exception:
            continue
        vals.extend(v for v in (ind.get(key) or []) if v is not None)
    return sum(vals) / len(vals) if vals else None


def draw_fan(ax, side: dict, color: str) -> None:
    x = comp(side, PROJ_X)
    y = comp(side, PROJ_Y)
    n = min(len(x), len(y))
    if not n:
        return
    x, y = x[:n], y[:n]
    if FLIP_X:
        x = -x
    if FLIP_Y:
        y = -y
    for xi, yi in zip(x, y):
        ax.plot([0, xi], [0, yi], color=color, alpha=0.12, linewidth=0.8,
                solid_capstyle="round")


def build_figure(swim_dir: Path) -> plt.Figure:
    left, right = load_sides(swim_dir)
    dist = distribution(left, right)
    pl, pr = mean_power(swim_dir, "left"), mean_power(swim_dir, "right")

    fig, ax = plt.subplots(figsize=(7, 7))
    fig.patch.set_facecolor("#f4f4f4")
    ax.set_facecolor("#f4f4f4")

    # reference rings
    span = 0.0
    for side in (left, right):
        for k in (PROJ_X, PROJ_Y):
            c = comp(side, k)
            if c.size:
                span = max(span, float(np.abs(c).max()))
    span = span or 1.0
    for r in np.linspace(span / 4, span, 4):
        ax.add_patch(plt.Circle((0, 0), r, fill=False, color="#d8d8d8", lw=1))
    ax.axhline(0, color="#d0d0d0", lw=1)
    ax.axvline(0, color="#d0d0d0", lw=1)

    draw_fan(ax, left, LEFT_COLOR)
    draw_fan(ax, right, RIGHT_COLOR)

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
    txt = "Distribution of Power\n"
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("swim_dir")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    swim_dir = Path(args.swim_dir)
    if not (swim_dir / "lapforcetime.json").exists():
        print(f"No lapforcetime.json in {swim_dir}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else swim_dir / "force_field.png"
    fig = build_figure(swim_dir)
    fig.savefig(out, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)

    left, right = load_sides(swim_dir)
    dist = distribution(left, right)
    print(f"wrote {out}")
    print("  " + "  ".join(f"{k}={v:.2f}%" for k, v in dist.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
