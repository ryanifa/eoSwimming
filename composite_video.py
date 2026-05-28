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
    speed: float = 1.0,
    out_fps: str = "",
    audio: bool = True,
) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH")

    overlay_filter = f"[1:v]setpts=PTS+{swim_start_seconds}/TB"
    if overlay_scale != 1.0:
        overlay_filter += f",scale=iw*{overlay_scale}:ih*{overlay_scale}"
    overlay_filter += "[ov]"

    graph = f"{overlay_filter};[0:v][ov]overlay=0:0:format=auto:eof_action=pass"
    # slow (or speed up) the *composited* result so video + overlay stay in sync
    slowed = abs(speed - 1.0) > 1e-6
    if slowed:
        # slowing doubles the duration *and* re-encodes; on 4K footage that
        # bloats the file badly, so cap slow-motion output at 1080p (analysis
        # detail survives) and use a lighter CRF.
        graph += rf"[cv];[cv]scale=min(1920\,iw):-2,setpts=PTS/{speed}[v]"
    else:
        graph += "[v]"

    crf = "24" if slowed else "20"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(overlay),
        "-filter_complex", graph,
        "-map", "[v]",
    ]
    # a changed playback speed makes the original audio useless, so drop it then
    if audio and not slowed:
        cmd += ["-map", "0:a?", "-c:a", "copy"]
    cmd += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", crf,
        # put the moov index at the front so the file streams on mobile
        # (iOS Safari won't start a network MP4 with the index at the end)
        "-movflags", "+faststart",
    ]
    # force the output framerate to the source's, so slow motion stays smooth
    # (setpts otherwise loses the framerate and ffmpeg falls back to 25 fps)
    if out_fps and out_fps not in ("0/0", "N/A"):
        cmd += ["-r", out_fps]
    cmd += [str(out)]
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
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed of the final result (0.5 = half speed / slow motion, 1.0 = normal)",
    )
    parser.add_argument(
        "--fps",
        default="",
        help="Force output framerate (e.g. the source's r_frame_rate); keeps slow motion smooth",
    )
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()

    speed = args.speed if args.speed and args.speed > 0 else 1.0
    composite(
        video=args.video,
        overlay=args.overlay,
        out=args.out,
        swim_start_seconds=args.swim_start,
        overlay_scale=args.overlay_scale,
        speed=speed,
        out_fps=args.fps,
        audio=not args.no_audio,
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
