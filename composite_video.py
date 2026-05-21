"""Composite an overlay.mov onto a user video at a given start offset."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def composite(
    video: Path,
    overlay: Path,
    out: Path,
    swim_start_seconds: float,
    overlay_scale: float = 1.0,
    audio: bool = True,
) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH")

    overlay_filter = f"[1:v]setpts=PTS+{swim_start_seconds}/TB"
    if overlay_scale != 1.0:
        overlay_filter += f",scale=iw*{overlay_scale}:ih*{overlay_scale}"
    overlay_filter += "[ov]"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(overlay),
        "-filter_complex",
        f"{overlay_filter};[0:v][ov]overlay=0:0:format=auto:eof_action=pass[v]",
        "-map", "[v]",
    ]
    if audio:
        cmd += ["-map", "0:a?", "-c:a", "copy"]
    cmd += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "20",
        str(out),
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path, help="Input video file")
    parser.add_argument("--overlay", required=True, type=Path, help="overlay.mov file")
    parser.add_argument("--out", required=True, type=Path, help="Output mp4 path")
    parser.add_argument(
        "--swim-start",
        type=float,
        default=0.0,
        help="Seconds into the video where the swim begins (overlay t=0 aligns here)",
    )
    parser.add_argument(
        "--overlay-scale",
        type=float,
        default=1.0,
        help="Scale factor for the overlay (e.g. 2.0 for 4K video on 1080p overlay)",
    )
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()

    composite(
        video=args.video,
        overlay=args.overlay,
        out=args.out,
        swim_start_seconds=args.swim_start,
        overlay_scale=args.overlay_scale,
        audio=not args.no_audio,
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
