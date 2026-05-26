"""Rotate and/or trim a video with ffmpeg.

Built for footage shot upside down (e.g. a GoPro mounted inverted): rotate
the whole clip 180 degrees and optionally cut a start/end off it.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROTATE_FILTERS = {
    "none": None,
    "180": "hflip,vflip",
    "90_cw": "transpose=1",
    "90_ccw": "transpose=2",
}


def ffprobe_duration(video: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def transform(
    video: Path,
    out: Path,
    rotate: str = "180",
    start: float = 0.0,
    end: float = 0.0,
) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH")
    if rotate not in ROTATE_FILTERS:
        raise ValueError(f"rotate must be one of {list(ROTATE_FILTERS)}")

    cmd = ["ffmpeg", "-y", "-i", str(video)]

    # output-side trim (accurate with re-encode); end<=start means "until the end"
    if start and start > 0:
        cmd += ["-ss", str(start)]
    if end and end > start:
        cmd += ["-to", str(end)]

    vf = ROTATE_FILTERS[rotate]
    if vf:
        cmd += ["-vf", vf]

    cmd += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path, help="Input video file")
    parser.add_argument("--out", required=True, type=Path, help="Output mp4 path")
    parser.add_argument("--rotate", default="180", choices=list(ROTATE_FILTERS),
                        help="Rotation to apply (default 180 for upside-down footage)")
    parser.add_argument("--start", type=float, default=0.0,
                        help="Trim: seconds to cut from the start (default 0)")
    parser.add_argument("--end", type=float, default=0.0,
                        help="Trim: end time in seconds (0 = keep until the end)")
    args = parser.parse_args()

    dur = ffprobe_duration(args.video)
    print(f"input duration: {dur:.2f}s, rotate={args.rotate}, start={args.start}, end={args.end or 'end'}")
    transform(args.video, args.out, rotate=args.rotate, start=args.start, end=args.end)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
