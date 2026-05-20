"""Render a transparent video overlay (ProRes 4444 .mov) from eo SwimBETTER data.

Reads a swim directory and produces overlay.mov with scrolling force-vs-time and
live metrics, suitable for compositing onto pool-camera footage in a video editor.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patches
from matplotlib.figure import Figure


FRAME_RATE = 60
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
WINDOW_MS = 4000


def load_swim(swim_dir: Path) -> dict:
    raw = json.loads((swim_dir / "swim.json").read_text())
    return raw[0] if isinstance(raw, list) and raw else raw


def load_lapforcetime(swim_dir: Path) -> dict:
    text = (swim_dir / "lapforcetime.json").read_text()
    data = json.loads(text)
    if isinstance(data, str):
        data = json.loads(data)
    return data


def render_frame(args: tuple[int, float, dict, Path]) -> None:
    frame_idx, now_ms, data, frames_dir = args
    times = data["time"]
    lf = data["left"]["forward"]
    rf = data["right"]["forward"]

    fig: Figure = plt.figure(
        figsize=(FRAME_WIDTH / 100, FRAME_HEIGHT / 100), dpi=100
    )
    fig.patch.set_alpha(0)

    ax = fig.add_axes([0.08, 0.06, 0.84, 0.28])
    ax.patch.set_facecolor((0, 0.21, 0.18, 0.55))
    for spine in ax.spines.values():
        spine.set_color("white")
        spine.set_alpha(0.4)
    ax.tick_params(colors="white", labelsize=10)
    ax.set_xlabel("Time (s)", color="white", fontsize=11)
    ax.set_ylabel("Propulsion (N)", color="white", fontsize=11)
    ax.grid(True, alpha=0.2, color="white")

    left = now_ms - WINDOW_MS / 2
    right = now_ms + WINDOW_MS / 2
    ax.set_xlim(left / 1000, right / 1000)

    visible = [(t, l, r) for t, l, r in zip(times, lf, rf) if left <= t <= right]
    if visible:
        ts = [t / 1000 for t, _, _ in visible]
        ls = [l for _, l, _ in visible]
        rs = [r for _, _, r in visible]
        ax.plot(ts, ls, color="#4ea1ff", linewidth=2.0, label="Left")
        ax.plot(ts, rs, color="#ff8a3d", linewidth=2.0, label="Right")

    ax.axvline(now_ms / 1000, color="#ff4040", linewidth=2, alpha=0.85)

    ymin, ymax = -50, max(max(lf), max(rf)) * 1.1
    ax.set_ylim(ymin, ymax)
    ax.legend(
        loc="upper right",
        labelcolor="white",
        facecolor=(0, 0.21, 0.18, 0.55),
        edgecolor="white",
        fontsize=11,
    )

    current_l = _value_at(times, lf, now_ms)
    current_r = _value_at(times, rf, now_ms)

    panel = fig.add_axes([0.02, 0.78, 0.22, 0.18])
    panel.patch.set_facecolor((0, 0.21, 0.18, 0.7))
    panel.set_xticks([])
    panel.set_yticks([])
    for spine in panel.spines.values():
        spine.set_color("white")
        spine.set_alpha(0.6)
    panel.text(0.06, 0.78, f"t = {now_ms / 1000:5.2f} s", color="white", fontsize=22, weight="bold", transform=panel.transAxes)
    panel.text(0.06, 0.45, f"L  {current_l:6.1f} N", color="#4ea1ff", fontsize=20, family="monospace", transform=panel.transAxes)
    panel.text(0.06, 0.15, f"R  {current_r:6.1f} N", color="#ff8a3d", fontsize=20, family="monospace", transform=panel.transAxes)

    out = frames_dir / f"frame_{frame_idx:06d}.png"
    fig.savefig(out, transparent=True, dpi=100)
    plt.close(fig)


def _value_at(times: list[int], values: list[float], now_ms: float) -> float:
    if not times:
        return 0.0
    idx = int(now_ms // 10)
    if idx < 0 or idx >= len(values):
        return 0.0
    return values[idx]


def encode_prores(frames_dir: Path, out_path: Path, fps: int) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-vendor", "apl0",
        str(out_path),
    ]
    print("  encoding:", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True)


def render_overlay(swim_dir: Path, fps: int = FRAME_RATE, keep_frames: bool = False) -> Path:
    swim = load_swim(swim_dir)
    data = load_lapforcetime(swim_dir)
    times = data.get("time") or []
    if not times:
        raise RuntimeError(f"No time data in {swim_dir}/lapforcetime.json")

    start_ms = swim.get("t0_trim", 0) or 0
    end_ms = times[-1]
    duration_ms = end_ms - start_ms
    total_frames = int(duration_ms * fps / 1000)
    print(f"  swim duration: {duration_ms / 1000:.2f}s, frames: {total_frames} @ {fps}fps")

    frames_dir = swim_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir()

    work = [
        (i, start_ms + (i * 1000 / fps), data, frames_dir)
        for i in range(total_frames)
    ]

    workers = max(1, cpu_count())
    print(f"  rendering with {workers} workers")
    with Pool(workers) as pool:
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
    parser.add_argument("swim_dir", nargs="?", help="Specific swim directory; default: all under data/")
    parser.add_argument("--fps", type=int, default=FRAME_RATE)
    parser.add_argument("--keep-frames", action="store_true", help="Keep PNG frames after encoding")
    args = parser.parse_args()

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
        targets = sorted(
            d for d in data_dir.iterdir()
            if d.is_dir() and (d / "swim.json").exists() and (d / "lapforcetime.json").exists()
        )

    if not targets:
        print("No swims with lapforcetime.json found.", file=sys.stderr)
        return 1

    for swim_dir in targets:
        print(f"==> {swim_dir.name}")
        try:
            render_overlay(swim_dir, fps=args.fps, keep_frames=args.keep_frames)
        except Exception as exc:
            print(f"  failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
