"""Render a transparent video overlay (ProRes 4444 .mov) from eo SwimBETTER data.

This mirrors the live canvas preview in docs/index.html as closely as possible:
a scrolling force/velocity chart (force on the left axis, hand speed on the
right), a metrics panel, and the Head On / Overhead / Side On hand-path panels
with phase colours, the moving marker and the swimmer figures.

Which series and panels are drawn is controlled by environment variables that
the workflow fills from its checkbox inputs (propulsion is on by default).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

FRAME_RATE = 60
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
REF_W = 1280            # logical width the canvas math is written against
REF_H = 720
SC = FRAME_WIDTH / REF_W
WINDOW_MS = 4000

_FONTDIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
FONT_SANS = str(_FONTDIR / "DejaVuSans.ttf")
FONT_SANS_BOLD = str(_FONTDIR / "DejaVuSans-Bold.ttf")
FONT_MONO = str(_FONTDIR / "DejaVuSansMono.ttf")

FRIENDLY = {
    "forward": "Propulsive", "propulsive": "Propulsive", "propulsion": "Propulsive",
    "total": "Total force", "totalforce": "Total force",
    "vertical": "Vertical", "lateral": "Lateral",
    "handvelocity": "Hand velocity", "velocity": "Hand velocity",
    "speed": "Hand speed", "handspeed": "Hand speed",
}
PALETTE = ["#ff8a3d", "#4ea1ff", "#b07cff", "#ffd24a", "#37d39b", "#ff5d8f", "#62d0ff", "#c0e35a"]
PHASE_COLOR = {"catch": "#ff4040", "pull": "#4ea1ff", "recovery": "#9aa7a3", "none": "#9aa7a3"}

# swimmer figures (same PNGs the preview embeds)
GLYPH_FILES = {"headon": "head on.png", "overhead": "overhead.png", "side": "side on.png"}


def hexrgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgba(h: str, a: float = 1.0) -> tuple[int, int, int, int]:
    r, g, b = hexrgb(h)
    return (r, g, b, int(round(a * 255)))


_font_cache: dict = {}


def font(path: str, px: float) -> ImageFont.FreeTypeFont:
    key = (path, int(round(px * SC)))
    f = _font_cache.get(key)
    if f is None:
        f = ImageFont.truetype(path, max(1, key[1]))
        _font_cache[key] = f
    return f


class Canvas:
    """Minimal canvas-like surface with source-over compositing, in logical px."""

    def __init__(self, w: int, h: int):
        self.img = Image.new("RGBA", (int(w * SC), int(h * SC)), (0, 0, 0, 0))

    def _composite(self, bbox, fn) -> None:
        x0, y0, x1, y1 = bbox
        ix0 = int(math.floor(min(x0, x1) * SC)) - 3
        iy0 = int(math.floor(min(y0, y1) * SC)) - 3
        ix1 = int(math.ceil(max(x0, x1) * SC)) + 3
        iy1 = int(math.ceil(max(y0, y1) * SC)) + 3
        ix0 = max(0, ix0); iy0 = max(0, iy0)
        ix1 = min(self.img.width, ix1); iy1 = min(self.img.height, iy1)
        if ix1 <= ix0 or iy1 <= iy0:
            return
        layer = Image.new("RGBA", (ix1 - ix0, iy1 - iy0), (0, 0, 0, 0))
        fn(ImageDraw.Draw(layer), ix0, iy0)
        self.img.alpha_composite(layer, dest=(ix0, iy0))

    def line(self, p0, p1, color, width=1.0):
        w = max(1, int(round(width * SC)))
        self._composite((p0[0], p0[1], p1[0], p1[1]),
                        lambda d, ox, oy: d.line(
                            [(p0[0] * SC - ox, p0[1] * SC - oy), (p1[0] * SC - ox, p1[1] * SC - oy)],
                            fill=color, width=w))

    def polyline(self, pts, color, width=1.0, dash=None):
        if len(pts) < 2:
            return
        if dash:
            for seg in _dash(pts, dash[0], dash[1]):
                self.polyline(seg, color, width)
            return
        w = max(1, int(round(width * SC)))
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        self._composite((min(xs), min(ys), max(xs), max(ys)),
                        lambda d, ox, oy: d.line([(p[0] * SC - ox, p[1] * SC - oy) for p in pts],
                                                 fill=color, width=w, joint="curve"))

    def rrect(self, x, y, w, h, r, fill=None, stroke=None, stroke_w=1.0):
        def fn(d, ox, oy):
            box = [x * SC - ox, y * SC - oy, (x + w) * SC - ox, (y + h) * SC - oy]
            d.rounded_rectangle(box, radius=r * SC, fill=fill,
                                outline=stroke, width=max(1, int(round(stroke_w * SC))) if stroke else 1)
        self._composite((x, y, x + w, y + h), fn)

    def disc(self, cx, cy, r, fill, stroke=None, stroke_w=1.5):
        def fn(d, ox, oy):
            box = [cx * SC - ox - r * SC, cy * SC - oy - r * SC, cx * SC - ox + r * SC, cy * SC - oy + r * SC]
            d.ellipse(box, fill=fill, outline=stroke, width=max(1, int(round(stroke_w * SC))) if stroke else 1)
        self._composite((cx - r, cy - r, cx + r, cy + r), fn)

    def text(self, x, y, s, fnt, color, anchor="ls"):
        if not s:
            return
        xpx, ypx = x * SC, y * SC
        w = fnt.getlength(s)
        asc, desc = fnt.getmetrics()
        ha = anchor[0]
        x0 = xpx if ha == "l" else (xpx - w if ha == "r" else xpx - w / 2)
        ix0 = int(math.floor(x0)) - 2
        iy0 = int(math.floor(ypx - asc)) - 2
        iw = int(math.ceil(w)) + 4
        ih = asc + desc + 4
        layer = Image.new("RGBA", (max(1, iw), max(1, ih)), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((xpx - ix0, ypx - iy0), s, font=fnt, fill=color, anchor=anchor)
        if ix0 < 0:
            layer = layer.crop((-ix0, 0, layer.width, layer.height)); ix0 = 0
        if iy0 < 0:
            layer = layer.crop((0, -iy0, layer.width, layer.height)); iy0 = 0
        self.img.alpha_composite(layer, dest=(ix0, iy0))

    def text_vertical(self, cx, cy, s, fnt, color):
        """Text rotated 90deg CCW, centred at (cx, cy)."""
        if not s:
            return
        bbox = fnt.getbbox(s)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tmp = Image.new("RGBA", (tw + 4, th + 4), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((2 - bbox[0], 2 - bbox[1]), s, font=fnt, fill=color)
        tmp = tmp.rotate(90, expand=True)
        self.img.alpha_composite(tmp, dest=(int(cx * SC - tmp.width / 2), int(cy * SC - tmp.height / 2)))

    def paste(self, img, cx, cy, box_logical, alpha=0.85):
        bw = bh = box_logical * SC
        ar = img.width / img.height
        if ar >= 1:
            dh = bw / ar; dw = bw
        else:
            dw = bh * ar; dh = bh
        im = img.resize((max(1, int(dw)), max(1, int(dh))))
        if alpha < 1:
            a = im.split()[3].point(lambda v: int(v * alpha))
            im.putalpha(a)
        self.img.alpha_composite(im, dest=(int(cx * SC - im.width / 2), int(cy * SC - im.height / 2)))


def _dash(pts, on, off):
    out, cur = [], [pts[0]]
    pen, rem = True, on * SC
    for k in range(1, len(pts)):
        x0, y0 = pts[k - 1]; x1, y1 = pts[k]
        seg = math.hypot((x1 - x0) * SC, (y1 - y0) * SC)
        pos = 0.0
        while seg - pos > rem:
            t = (pos + rem) / seg
            mx, my = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            if pen:
                cur.append((mx, my)); out.append(cur); cur = []
            else:
                cur = [(mx, my)]
            pos += rem
            pen = not pen
            rem = (on if pen else off) * SC
        rem -= (seg - pos)
        if pen:
            cur.append((x1, y1))
    if pen and len(cur) >= 2:
        out.append(cur)
    return out


# ---------- data ----------

def _loads(text):
    d = json.loads(text)
    return json.loads(d) if isinstance(d, str) else d


def load_lapforcetime(swim_dir: Path) -> dict:
    return _loads((swim_dir / "lapforcetime.json").read_text())


def load_paths(swim_dir: Path, kind: str):
    """Merge all lap-NN-<kind>.json stroke lists (times are absolute)."""
    files = sorted(swim_dir.glob(f"lap-*-{kind}.json"))
    if not files:
        return None
    merged = {"strokesLeft": [], "strokesRight": []}
    for f in files:
        d = _loads(f.read_text())
        for side in ("strokesLeft", "strokesRight"):
            merged[side].extend(d.get(side) or [])
    for side in ("strokesLeft", "strokesRight"):
        merged[side].sort(key=lambda s: (s.get("time") or [0])[0])
    return merged


def is_num_array(v):
    return isinstance(v, list) and len(v) > 0 and isinstance(v[0], (int, float))


def label_of(i):
    base = i.split(".")[-1]
    return FRIENDLY.get(base) or FRIENDLY.get(base.lower()) or base


def kind_of(i):
    return "velocity" if re.search(r"velocit|speed", i, re.I) else "force"


def discover_series(d: dict) -> list[dict]:
    out = []
    left = d.get("left") if isinstance(d.get("left"), dict) else {}
    right = d.get("right") if isinstance(d.get("right"), dict) else {}
    keys = list(dict.fromkeys(list(left.keys()) + list(right.keys())))
    ci = 0
    for k in keys:
        l = left.get(k) if is_num_array(left.get(k)) else None
        r = right.get(k) if is_num_array(right.get(k)) else None
        if l is None and r is None:
            continue
        out.append({"id": k, "label": label_of(k), "kind": kind_of(k),
                    "color": PALETTE[ci % len(PALETTE)], "data": {"left": l, "right": r}})
        ci += 1
    for k in d:
        if k in ("time", "left", "right"):
            continue
        if is_num_array(d[k]):
            out.append({"id": k, "label": label_of(k), "kind": kind_of(k),
                        "color": PALETTE[ci % len(PALETTE)], "data": {"single": d[k]}})
            ci += 1
        elif isinstance(d[k], dict):
            for sub in d[k]:
                if is_num_array(d[k][sub]):
                    sid = f"{k}.{sub}"
                    out.append({"id": sid, "label": label_of(sid), "kind": kind_of(sid),
                                "color": PALETTE[ci % len(PALETTE)], "data": {"single": d[k][sub]}})
                    ci += 1
    return out


def env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# Maps the keys a user may type in the SHOW_FORCES field to internal series groups.
FORCE_KEYS = {
    "propulsive": "propulsive", "propulsion": "propulsive", "forward": "propulsive",
    "totalforce": "total", "total": "total",
    "vertical": "vertical",
    "lateral": "lateral",
    "handvelocity": "handvelocity", "velocity": "handvelocity",
    "handspeed": "handvelocity", "speed": "handvelocity",
}


def parse_show_forces(spec: str) -> dict:
    """Parse 'propulsive=1;totalForce=0;...' into a {group: bool} selection.
    Unlisted groups keep their default (propulsive on, the rest off)."""
    want = {"propulsive": True, "total": False, "vertical": False,
            "lateral": False, "handvelocity": False}
    for part in re.split(r"[;,]", spec or ""):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        key = FORCE_KEYS.get(k.strip().lower())
        if key:
            want[key] = _truthy(v)
    return want


def select_enabled(series: list[dict]) -> list[dict]:
    want = parse_show_forces(os.environ.get("SHOW_FORCES", ""))
    enabled = []
    for s in series:
        i = s["id"].lower()
        on = False
        if re.search(r"forward|propuls", i):
            on = want["propulsive"]
        elif i == "total":
            on = want["total"]
        elif i == "vertical":
            on = want["vertical"]
        elif i == "lateral":
            on = want["lateral"]
        elif re.search(r"velocit|speed", i):
            on = want["handvelocity"]
        if on:
            enabled.append(s)
    return enabled


def value_at(values, now_ms):
    idx = int(now_ms // 10)
    if idx < 0 or idx >= len(values):
        return 0.0
    return values[idx]


def range_of(lst):
    mn, mx = math.inf, -math.inf
    for s in lst:
        for side in ("left", "right", "single"):
            arr = s["data"].get(side)
            if not arr:
                continue
            for v in arr:
                if v < mn:
                    mn = v
                if v > mx:
                    mx = v
    if mn == math.inf:
        return 0.0, 1.0
    if mn > 0:
        mn = 0.0
    if mx < 0:
        mx = 0.0
    pad = (mx - mn) * 0.1 or 1.0
    return mn - (pad if mn < 0 else 0.0), mx + pad


def pick_stroke(strokes, t):
    if not strokes:
        return None
    fb = strokes[0]
    for s in strokes:
        ts = s.get("time")
        if not ts:
            continue
        if ts[0] <= t <= ts[-1]:
            return s
        if ts[0] <= t:
            fb = s
    return fb


def phase_at(stroke, t):
    for name in ("catch", "pull", "recovery"):
        arr = stroke.get(f"{name}.time")
        if arr and arr[0] <= t <= arr[-1]:
            return name
    return "none"


def sample_index(stroke, t):
    ts = stroke.get("time")
    if not ts:
        return -1
    if t <= ts[0]:
        return 0
    if t >= ts[-1]:
        return len(ts) - 1
    return max(0, min(len(ts) - 1, int(round((t - ts[0]) / 10))))


def path_points(now_ms, side, xspec, yspec, sweep, depth):
    def strokes(fkey):
        f = sweep if fkey == "sweep" else depth
        if not f:
            return []
        return f["strokesLeft"] if side == "left" else f["strokesRight"]
    xs_stroke = pick_stroke(strokes(xspec[0]), now_ms)
    ys_stroke = pick_stroke(strokes(yspec[0]), now_ms)
    if not xs_stroke or not ys_stroke:
        return None
    xv = xs_stroke.get(xspec[1]); yv = ys_stroke.get(yspec[1]); tv = xs_stroke.get("time")
    if not xv or not yv or not tv:
        return None
    n = min(len(xv), len(yv), len(tv))
    return {"cmX": [xv[i] * 100 for i in range(n)],
            "cmY": [yv[i] * 100 for i in range(n)],
            "time": tv[:n], "stroke": xs_stroke}


# ---------- views ----------

def path_panel_geom(w, h, n, layout=1):
    gap, titleH = 8, 18
    S = min(w * 0.19, (h - 24 - gap * (n - 1)) / n - titleH)
    S = max(78, S)
    ox = 12 if layout == 2 else w - S - 12
    return gap, titleH, S, ox


def build_views():
    """Same three panels as the preview, in the same order, with the same
    Overhead rotation + mirror. Gated by env toggles and data availability."""
    return [
        {"title": "Head On", "glyph": "headon", "xLabel": "fwd (cm)", "yLabel": "depth (cm)",
         "x": ("sweep", "sweep"), "y": ("depth", "depth"), "rotate": False, "mirror": False,
         "needs": ("sweep", "depth"), "env": "VIEW_HEADON"},
        {"title": "Overhead", "glyph": "overhead", "xLabel": "lat (cm)", "yLabel": "fwd (cm)",
         "x": ("sweep", "xAxis"), "y": ("sweep", "sweep"), "rotate": True, "mirror": True,
         "needs": ("sweep",), "env": "VIEW_OVERHEAD"},
        {"title": "Side On", "glyph": "side", "xLabel": "lat (cm)", "yLabel": "depth (cm)",
         "x": ("depth", "xAxis"), "y": ("depth", "depth"), "rotate": False, "mirror": False,
         "needs": ("depth",), "env": "VIEW_SIDEON"},
    ]


# worker globals
G = {}


def init_worker(payload):
    G.update(payload)
    G["glyphs"] = {}
    for k, fname in GLYPH_FILES.items():
        p = Path("docs") / fname
        if p.exists():
            G["glyphs"][k] = Image.open(p).convert("RGBA")


def draw_chart(cv, now_ms, w, h, active, show_left, show_right):
    times = G["times"]
    layout = G.get("layout", 1)
    chartH = h * 0.28
    chartX = w * 0.08
    chartW = w * 0.84
    pv = G["views"] if G["show_path"] else []
    if layout == 2:
        # mode 2: chart along the top, to the right of the left-hand panels
        chartY = 40
        if pv:
            _, _, S, ox = path_panel_geom(w, h, len(pv), layout)
            chartX = ox + S + 18
            chartW = w * 0.92 - chartX
    else:
        # mode 1: chart along the bottom, clear of the right-hand panels
        chartY = h - chartH - 10
        if pv:
            _, _, _, ox = path_panel_geom(w, h, len(pv), layout)
            chartW = min(chartW, ox - 12 - chartX)

    cv.rrect(chartX - 6, chartY - 30, chartW + 12, chartH + 50, 8, fill=rgba("#00352f", 0.55))
    cv.rrect(chartX, chartY, chartW, chartH, 0, stroke=rgba("#ffffff", 0.25), stroke_w=1)

    tLeft = now_ms - WINDOW_MS / 2
    tRight = now_ms + WINDOW_MS / 2
    xOf = lambda t: chartX + ((t - tLeft) / (tRight - tLeft)) * chartW

    force = [s for s in active if s["kind"] == "force"]
    vel = [s for s in active if s["kind"] == "velocity"]
    fmn, fmx = range_of(force)
    vmn, vmx = range_of(vel)
    yForce = lambda v: chartY + chartH - ((v - fmn) / (fmx - fmn)) * chartH
    yVel = lambda v: chartY + chartH - ((v - vmn) / (vmx - vmn)) * chartH

    if force:
        y0 = yForce(0)
        cv.line((chartX, y0), (chartX + chartW, y0), rgba("#ffffff", 0.25), 1)

    f11 = font(FONT_SANS, 11)
    if force:
        cv.text(chartX, chartY - 8, "Force (N)", f11, rgba("#ffffff", 1.0), anchor="ls")
    if vel:
        cv.text(chartX + chartW, chartY - 8, "Hand speed (m/s)", f11, rgba("#cfe9ff", 1.0), anchor="rs")

    f10 = font(FONT_MONO, 10)
    s = math.ceil(tLeft / 1000)
    while s * 1000 <= tRight:
        x = xOf(s * 1000)
        if chartX <= x <= chartX + chartW:
            cv.text(x, chartY + chartH + 14, f"{s}s", f10, rgba("#ffffff", 1.0), anchor="ms")
        s += 1

    iN = len(times)
    for sObj in active:
        yfn = yVel if sObj["kind"] == "velocity" else yForce
        for side, dashed in (("left", False), ("right", True), ("single", False)):
            arr = sObj["data"].get(side)
            if not arr:
                continue
            if side == "left" and not show_left:
                continue
            if side == "right" and not show_right:
                continue
            i0 = max(0, int(tLeft // 10))
            i1 = min(iN, len(arr), int(math.ceil(tRight / 10)) + 1)
            pts = [(xOf(times[i]), yfn(arr[i])) for i in range(i0, i1)]
            cv.polyline(pts, rgba(sObj["color"], 1.0), 1.8, dash=(5, 4) if dashed else None)

    xn = chartX + chartW / 2
    cv.line((xn, chartY), (xn, chartY + chartH), rgba("#ff4040", 0.85), 2)


def draw_metrics(cv, now_ms, w, h, active, in_range, show_left, show_right):
    times = G["times"]
    rows = []
    for s in active:
        unit = "m/s" if s["kind"] == "velocity" else "N"
        dec = 2 if s["kind"] == "velocity" else 1
        if s["data"].get("single"):
            v = value_at(s["data"]["single"], now_ms) if in_range else 0.0
            rows.append((s["color"], f"{s['label']}  {v:.{dec}f} {unit}"))
        else:
            parts = []
            if in_range and s["data"].get("left") and show_left:
                parts.append(f"L {value_at(s['data']['left'], now_ms):.{dec}f}")
            if in_range and s["data"].get("right") and show_right:
                parts.append(f"R {value_at(s['data']['right'], now_ms):.{dec}f}")
            rows.append((s["color"], f"{s['label']}  {'  '.join(parts)} {unit}"))

    lineH = max(16, min(22, h * 0.03))
    pw = min(320, w * 0.30)
    ph = 14 + lineH * (len(rows) + 1) + 8
    # mode 2 is a 180-degree mirror of mode 1: readout moves to the bottom-right
    # (panels are full-size on the left, chart top-right)
    if G.get("layout", 1) == 2:
        px, py = w - pw - 14, h - ph - 14
    else:
        px, py = 14, 14
    cv.rrect(px, py, pw, ph, 8, fill=rgba("#00352f", 0.7), stroke=rgba("#ffffff", 0.4), stroke_w=1)

    tdisp = f"{now_ms / 1000:.2f}" if in_range else "—"
    cv.text(px + 12, py + lineH, f"t = {tdisp} s", font(FONT_SANS_BOLD, round(lineH * 0.8)),
            rgba("#ffffff", 1.0), anchor="ls")
    fmono = font(FONT_MONO, round(lineH * 0.72))
    for i, (color, text) in enumerate(rows):
        cv.text(px + 12, py + lineH * (i + 2), text, fmono, rgba(color, 1.0), anchor="ls")


def draw_path_square(cv, ox, oy, S, view, now_ms, show_left, show_right):
    sweep, depth = G["sweep"], G["depth"]
    titleH = 18
    cv.rrect(ox, oy, S, S + titleH, 8, fill=rgba("#00352f", 0.72), stroke=rgba("#ffffff", 0.35), stroke_w=1)
    cv.text(ox + 6, oy + 13, view["title"], font(FONT_SANS_BOLD, max(9, round(S * 0.085))),
            rgba("#cfe9ff", 1.0), anchor="ls")
    g = G["glyphs"].get(view["glyph"])
    if g:
        cv.paste(g, ox + S - 16, oy + 14, 10 * 2.4, alpha=0.85)  # box = s*2.4, s=10

    pad = max(16, S * 0.17)
    plotX, plotY, plotS = ox + pad, oy + titleH + 4, S - pad - 8
    mapX = lambda cm: plotX + ((cm + 100) / 200) * plotS
    mapY = lambda cm: plotY + plotS - ((cm + 100) / 200) * plotS

    ftick = font(FONT_MONO, max(7, round(S * 0.058)))
    for c in (-100, -50, 0, 50, 100):
        y, x = mapY(c), mapX(c)
        col = rgba("#ffffff", 0.3) if c == 0 else rgba("#ffffff", 0.1)
        cv.line((plotX, y), (plotX + plotS, y), col, 1)
        cv.line((x, plotY), (x, plotY + plotS), col, 1)
        cv.text(plotX - 2, y + 3, str(c), ftick, rgba("#cfe9ff", 0.7), anchor="rs")
    cv.text(plotX + plotS / 2, oy + S + titleH - 3, view["xLabel"], ftick, rgba("#cfe9ff", 0.6), anchor="ms")
    cv.text_vertical(ox + 7, plotY + plotS / 2, view["yLabel"], ftick, rgba("#cfe9ff", 0.6))

    rot, mir = view["rotate"], view["mirror"]

    def PX(cx, cy):
        x = -cy if rot else cx
        if mir:
            x = -x
        return mapX(x)

    def PY(cx, cy):
        return mapY(cx if rot else cy)

    for side, dashed in (("left", False), ("right", True)):
        if side == "left" and not show_left:
            continue
        if side == "right" and not show_right:
            continue
        pts = path_points(now_ms, side, view["x"], view["y"], sweep, depth)
        if not pts:
            continue
        i = 0
        n = len(pts["cmX"])
        while i < n:
            ph = phase_at(pts["stroke"], pts["time"][i])
            j = i + 1
            while j < n and phase_at(pts["stroke"], pts["time"][j]) == ph:
                j += 1
            span = [(PX(pts["cmX"][k], pts["cmY"][k]), PY(pts["cmX"][k], pts["cmY"][k])) for k in range(i, min(j + 1, n))]
            cv.polyline(span, rgba(PHASE_COLOR[ph], 1.0), 1.8, dash=(6, 4) if dashed else None)
            i = j
        ts = pts["stroke"].get("time")
        if ts and ts[0] <= now_ms <= ts[-1]:
            idx = sample_index(pts["stroke"], now_ms)
            if 0 <= idx < n:
                r = max(3.5, S * 0.045)
                cv.disc(PX(pts["cmX"][idx], pts["cmY"][idx]), PY(pts["cmX"][idx], pts["cmY"][idx]),
                        r, rgba("#ff8a3d" if side == "left" else "#19e0ff", 1.0),
                        stroke=rgba("#ffffff", 1.0), stroke_w=1.5)


def draw_path_panel(cv, now_ms, w, h, show_left, show_right):
    views = G["views"]
    if not views:
        return
    gap, titleH, S, ox = path_panel_geom(w, h, len(views), G.get("layout", 1))
    oy = 12
    for v in views:
        draw_path_square(cv, ox, oy, S, v, now_ms, show_left, show_right)
        oy += S + titleH + gap


def render_frame(args):
    frame_idx, now_ms, frames_dir = args
    w, h = REF_W, REF_H
    times = G["times"]
    active = G["active"]
    show_left, show_right = G["show_left"], G["show_right"]
    in_range = times[0] <= now_ms <= times[-1]

    cv = Canvas(w, h)
    draw_chart(cv, now_ms, w, h, active, show_left, show_right)
    draw_metrics(cv, now_ms, w, h, active, in_range, show_left, show_right)
    if G["show_path"]:
        draw_path_panel(cv, now_ms, w, h, show_left, show_right)

    cv.img.save(frames_dir / f"frame_{frame_idx:06d}.png")


def encode_prores(frames_dir: Path, out_path: Path, fps: int) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "prores_ks", "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le", "-vendor", "apl0",
        str(out_path),
    ]
    print("  encoding:", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True)


def render_overlay(swim_dir: Path, fps: int = FRAME_RATE, keep_frames: bool = False,
                   layout: int = 1) -> Path:
    data = load_lapforcetime(swim_dir)
    times = data.get("time") or []
    if not times:
        raise RuntimeError(f"No time data in {swim_dir}/lapforcetime.json")

    series = discover_series(data)
    active = select_enabled(series)
    if not active:
        active = [s for s in series if re.search(r"forward|propuls", s["id"], re.I)][:1] or series[:1]

    sweep = load_paths(swim_dir, "pathsweep")
    depth = load_paths(swim_dir, "pathdepth")
    n_sweep = len(list(swim_dir.glob("lap-*-pathsweep.json")))
    n_depth = len(list(swim_dir.glob("lap-*-pathdepth.json")))
    show_path = env_bool("SHOW_PATH", True)
    views = []
    for v in build_views():
        if not env_bool(v["env"], True):
            continue
        ok = all((sweep if n == "sweep" else depth) for n in v["needs"])
        if ok:
            views.append(v)

    show_left = env_bool("SHOW_LEFT", True)
    show_right = env_bool("SHOW_RIGHT", True)

    print(f"  series: {[s['label'] for s in active]}")
    print(f"  path files found: pathsweep={n_sweep} pathdepth={n_depth}")
    print(f"  path views: {[v['title'] for v in views] if show_path else 'off (SHOW_PATH disabled)'}  L={show_left} R={show_right}")
    if show_path and not views:
        print("  WARNING: no hand-path panels will be drawn. "
              "This swim has no pathsweep/pathdepth data in its folder "
              f"({swim_dir}), so there is nothing to plot on the right.")

    # The overlay timeline must start at data t=0 so it matches the browser sync
    # tool (docs/index.html), which maps video time to data via
    # (video_time - swim_start). swim_start aligns data t=0 to the video, so the
    # render must not apply t0_trim here or it shifts the graph out of sync.
    start_ms = 0
    end_ms = times[-1]
    total_frames = int((end_ms - start_ms) * fps / 1000)
    print(f"  duration {(end_ms - start_ms) / 1000:.2f}s, {total_frames} frames @ {fps}fps")

    frames_dir = swim_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir()

    _l = data.get("left") or {}
    _r = data.get("right") or {}
    forces = {
        "left": {"forward": _l.get("forward") or [], "lateral": _l.get("lateral") or []},
        "right": {"forward": _r.get("forward") or [], "lateral": _r.get("lateral") or []},
    }
    max_total = max([1.0] + (_l.get("total") or []) + (_r.get("total") or []))

    payload = {"times": times, "active": active, "sweep": sweep, "depth": depth,
               "views": views, "show_path": show_path, "show_left": show_left,
               "show_right": show_right, "layout": layout,
               "forces": forces, "max_total": max_total}
    work = [(i, start_ms + i * 1000 / fps, frames_dir) for i in range(total_frames)]

    workers = max(1, cpu_count())
    print(f"  rendering with {workers} workers")
    with Pool(workers, initializer=init_worker, initargs=(payload,)) as pool:
        for i, _ in enumerate(pool.imap_unordered(render_frame, work, chunksize=20)):
            if (i + 1) % 100 == 0 or i + 1 == total_frames:
                print(f"    {i + 1}/{total_frames}")

    out_path = swim_dir / "overlay.mov"
    encode_prores(frames_dir, out_path, fps)
    if not keep_frames:
        shutil.rmtree(frames_dir)
    print(f"  wrote {out_path}")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("swim_dir", nargs="?")
    parser.add_argument("--fps", type=int, default=FRAME_RATE)
    parser.add_argument("--keep-frames", action="store_true")
    parser.add_argument("--layout", default="default",
                        help="'default'/'1' = paths right + chart bottom + readout top-left; "
                             "'mirrored'/'2' = 180-deg flip: paths left + chart top + readout bottom-right")
    args = parser.parse_args()
    layout = 2 if str(args.layout).strip().lower() in ("2", "mirrored", "mirror") else 1

    if not shutil.which("ffmpeg"):
        print("ffmpeg not found in PATH", file=sys.stderr)
        return 1

    if args.swim_dir:
        targets = [Path(args.swim_dir)]
    else:
        data_dir = Path("data")
        if not data_dir.exists():
            print("No data/ directory.", file=sys.stderr)
            return 1
        targets = sorted(d for d in data_dir.iterdir()
                         if d.is_dir() and (d / "swim.json").exists() and (d / "lapforcetime.json").exists())
    if not targets:
        print("No swims with lapforcetime.json found.", file=sys.stderr)
        return 1

    for swim_dir in targets:
        print(f"==> {swim_dir.name}")
        try:
            render_overlay(swim_dir, fps=args.fps, keep_frames=args.keep_frames, layout=layout)
        except Exception as exc:
            print(f"  failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
