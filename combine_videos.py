"""Join several finished videos into one, server-side (hard cuts).

Each input is first normalised to one common canvas (default 1920x1080 @ 60fps,
AAC 48k stereo) so the clips concatenate cleanly and fill the frame. A clip
whose shape differs from the canvas (e.g. a portrait clip in a landscape
canvas) is centred sharp over a blurred, zoomed copy of itself instead of
getting black bars. The normalised clips are then joined with a plain
concatenation (hard cut) into one MP4.

Usage:
    python3 combine_videos.py OUT.mp4 in1.mp4 in2.mp4 [in3.mp4 ...]
            [--width 1920] [--height 1080] [--fps 60]

Note: inputs are expected to have an audio track (everything our pipeline
produces does). A mix of some clips with audio and some without won't
concatenate with a stream copy.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def norm_filter(tw: int, th: int, fps: int) -> str:
    """filter_complex that fits a frame onto tw x th, filling any empty area
    with a blurred, zoomed copy of the frame (no black bars)."""
    return (
        "[0:v]split=2[pbg][pfg];"
        f"[pbg]scale={tw}:{th}:force_original_aspect_ratio=increase,"
        f"crop={tw}:{th},gblur=sigma=20[bg];"
        f"[pfg]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={fps}[v]"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("inputs", nargs="+", type=Path)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=60)
    args = p.parse_args()

    if not shutil.which("ffmpeg"):
        print("ffmpeg not found", file=sys.stderr)
        return 1

    tw, th, fps = args.width, args.height, args.fps
    tw += tw % 2
    th += th % 2

    workdir = args.out.parent
    workdir.mkdir(parents=True, exist_ok=True)

    fc = norm_filter(tw, th, fps)
    parts = []
    print(f"combining {len(args.inputs)} clip(s) -> {tw}x{th} @ {fps}fps")
    for i, src in enumerate(args.inputs):
        if not src.exists():
            print(f"missing input: {src}", file=sys.stderr)
            return 1
        part = workdir / f"norm_{i:03d}.mp4"
        print(f"  normalising {i + 1}/{len(args.inputs)}: {src.name}")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "20",
             "-r", str(fps),
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", str(part)],
            check=True)
        parts.append(part)

    lst = workdir / "combine.txt"
    lst.write_text("\n".join(f"file '{p.name}'" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "combine.txt",
                    "-c", "copy", "-movflags", "+faststart", args.out.name],
                   check=True, cwd=str(workdir))

    # keep the result under GitHub Pages' 100 MB per-file serving limit
    MAX = 99_000_000
    for crf in (26, 30, 34):
        if args.out.stat().st_size <= MAX:
            break
        print(f"  result {args.out.stat().st_size} bytes > 100 MB — shrinking (crf={crf})")
        tmp = args.out.with_suffix(".fit.mp4")
        subprocess.run(["ffmpeg", "-y", "-i", str(args.out), "-vf", f"scale='min({tw},iw)':-2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", str(crf),
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)], check=True)
        tmp.replace(args.out)

    print(f"wrote {args.out} ({len(parts)} clip(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
