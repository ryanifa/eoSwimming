"""Apply a Trim & rotate EDL (from docs/edit.html) to a video, server-side.

The EDL is JSON: {"regions":[{"a":<s>,"b":<s>,"op":"cut|90_cw|90_ccw|180"}, ...]}.
Regions with op "cut" are removed; regions with a rotation op rotate only that
range (later regions win on overlap). Kept ranges are split at rotation
boundaries, each piece encoded with its own rotation and normalised to one
padded canvas so differing orientations concatenate cleanly. Read the EDL from
the $EDL env var (or --edl).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROT = {"90_cw": "transpose=1", "90_ccw": "transpose=2", "180": "hflip,vflip"}
EPS = 0.04


def probe(video: Path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-show_entries", "format=duration",
         "-of", "json", str(video)],
        check=True, capture_output=True, text=True).stdout
    d = json.loads(out)
    st = (d.get("streams") or [{}])[0]
    return float(d["format"]["duration"]), int(st["width"]), int(st["height"])


def merge(cuts):
    cuts = sorted([list(c) for c in cuts])
    out = []
    for a, b in cuts:
        if out and a <= out[-1][1] + EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [c for c in out if c[1] - c[0] > EPS]


def kept(dur, cuts):
    segs, pos = [], 0.0
    for a, b in cuts:
        if a - pos > EPS:
            segs.append([pos, a])
        pos = max(pos, b)
    if dur - pos > EPS:
        segs.append([pos, dur])
    return segs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("video", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--edl", default=None, help="EDL JSON (else read $EDL)")
    args = p.parse_args()

    if not shutil.which("ffmpeg"):
        print("ffmpeg not found", file=sys.stderr)
        return 1

    raw = args.edl if args.edl is not None else os.environ.get("EDL", "")
    try:
        edl = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(f"Invalid EDL JSON: {e}", file=sys.stderr)
        return 1
    regions = edl.get("regions") or []

    dur, W, H = probe(args.video)
    for r in regions:
        r["a"] = max(0.0, float(r["a"]))
        r["b"] = min(dur, float(r["b"]))

    cuts = merge([[r["a"], r["b"]] for r in regions if r.get("op") == "cut"])
    rots = [r for r in regions if r.get("op") in ROT]

    def rot_at(t):
        for r in reversed(rots):
            if r["a"] - EPS <= t < r["b"] - EPS:
                return r["op"]
        return None

    edges = []
    for r in rots:
        edges += [r["a"], r["b"]]

    segs = []
    for a, b in kept(dur, cuts):
        pts = sorted([a, b] + [x for x in edges if a + EPS < x < b - EPS])
        for i in range(len(pts) - 1):
            s, e = pts[i], pts[i + 1]
            if e - s > EPS:
                segs.append((s, e, rot_at((s + e) / 2)))
    if not segs:
        print("Nothing left after the edits.", file=sys.stderr)
        return 1

    # common canvas that fits every piece's orientation (pad the rest)
    TW = TH = 0
    for _, _, rot in segs:
        w, h = (H, W) if rot in ("90_cw", "90_ccw") else (W, H)
        TW, TH = max(TW, w), max(TH, h)
    # cap to 1080p so the result stays under GitHub Pages' 100 MB serving limit
    big = max(TW, TH)
    if big > 1920:
        TW = int(TW * 1920 / big)
        TH = int(TH * 1920 / big)
    TW += TW % 2
    TH += TH % 2

    def vf(rot):
        f = []
        if rot in ROT:
            f.append(ROT[rot])
        f += [f"scale={TW}:{TH}:force_original_aspect_ratio=decrease",
              f"pad={TW}:{TH}:(ow-iw)/2:(oh-ih)/2", "setsar=1"]
        return ",".join(f)

    workdir = args.out.parent
    workdir.mkdir(parents=True, exist_ok=True)
    parts = []
    print(f"input {dur:.2f}s {W}x{H} -> {len(segs)} piece(s), canvas {TW}x{TH}")
    for i, (s, e, rot) in enumerate(segs):
        part = workdir / f"part_{i:03d}.mp4"
        print(f"  piece {i + 1}/{len(segs)}: {s:.2f}-{e:.2f}s rot={rot or 'none'}")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{s:.3f}", "-i", str(args.video), "-t", f"{e - s:.3f}",
             "-vf", vf(rot),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "20",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(part)],
            check=True)
        parts.append(part)

    if len(parts) == 1:
        shutil.copy(parts[0], args.out)
    else:
        lst = workdir / "concat.txt"
        lst.write_text("\n".join(f"file '{p.name}'" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt",
                        "-c", "copy", "-movflags", "+faststart", args.out.name],
                       check=True, cwd=str(workdir))

    # keep the result under GitHub Pages' 100 MB per-file serving limit
    MAX = 99_000_000
    for crf in (26, 30, 34):
        if args.out.stat().st_size <= MAX:
            break
        print(f"  result {args.out.stat().st_size} bytes > 100 MB — shrinking (crf={crf})")
        tmp = args.out.with_suffix(".fit.mp4")
        subprocess.run(["ffmpeg", "-y", "-i", str(args.out), "-vf", "scale='min(1920,iw)':-2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", str(crf),
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)], check=True)
        tmp.replace(args.out)

    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
