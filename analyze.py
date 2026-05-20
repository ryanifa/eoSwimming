"""Generate CSV summary, per-swim analysis and plots from fetched eo SwimBETTER data."""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = Path("data")

SUMMARY_FIELDS = [
    "swimId", "date", "poolName", "poolDistance", "stroke",
    "distance", "laps", "duration_s", "pace_per100m_s",
    "avgVelocity", "peakVelocity", "avgStrokeRate",
    "avgDps", "avgFps", "avgPps2", "propulsion", "work",
    "totalStrokesLeft", "totalStrokesRight", "lrBalance",
    "maxForce", "isFavorite",
]


def load_swim(swim_dir: Path) -> dict:
    raw = json.loads((swim_dir / "swim.json").read_text())
    return raw[0] if isinstance(raw, list) and raw else raw


def load_lap_files(swim_dir: Path, suffix: str) -> list[tuple[int, dict]]:
    files = sorted(swim_dir.glob(f"lap-*-{suffix}.json"))
    result = []
    for f in files:
        try:
            lap_num = int(f.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        result.append((lap_num, json.loads(f.read_text())))
    return result


def safe(value, default=0):
    return value if value is not None else default


def summarize_swim(swim_dir: Path) -> dict:
    swim = load_swim(swim_dir)
    distance = safe(swim.get("distance"))
    duration_ms = safe(swim.get("duration"))
    duration_s = duration_ms / 1000 if duration_ms else 0
    pace = (duration_s / distance * 100) if distance else 0

    left = safe(swim.get("totalStrokesLeft"))
    right = safe(swim.get("totalStrokesRight"))
    lr_balance = (left / (left + right) * 100) if (left + right) else 0

    return {
        "swimId": swim.get("swimId", ""),
        "date": swim.get("date", ""),
        "poolName": swim.get("poolName", ""),
        "poolDistance": swim.get("poolDistance", ""),
        "stroke": swim.get("stroke", ""),
        "distance": distance,
        "laps": safe(swim.get("laps")),
        "duration_s": round(duration_s, 2),
        "pace_per100m_s": round(pace, 2),
        "avgVelocity": safe(swim.get("avgVelocity")),
        "peakVelocity": safe(swim.get("peakVelocity")),
        "avgStrokeRate": safe(swim.get("avgStrokeRate")),
        "avgDps": safe(swim.get("avgDps")),
        "avgFps": safe(swim.get("avgFps")),
        "avgPps2": safe(swim.get("avgPps2")),
        "propulsion": safe(swim.get("propulsion")),
        "work": safe(swim.get("work")),
        "totalStrokesLeft": left,
        "totalStrokesRight": right,
        "lrBalance": round(lr_balance, 1),
        "maxForce": safe(swim.get("maxForce")),
        "isFavorite": swim.get("isFavorite", False),
    }


def format_seconds(s: float) -> str:
    m, sec = divmod(s, 60)
    return f"{int(m)}:{sec:05.2f}" if m else f"{sec:.2f}s"


def write_summary_csv(swim_dirs: list[Path], out_path: Path) -> int:
    rows = []
    for d in swim_dirs:
        try:
            rows.append(summarize_swim(d))
        except Exception as exc:
            print(f"  skip {d.name}: {exc}")
    rows.sort(key=lambda r: r["date"], reverse=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def analyze_strokephase(phase: dict) -> dict:
    ind = phase.get("indicator", {})
    force_l = ind.get("forceLeft") or []
    force_r = ind.get("forceRight") or []
    pps_l = ind.get("PPSLeft") or []
    pps_r = ind.get("PPSRight") or []
    rates_l = [s.get("strokeRate", 0) for s in phase.get("strokesLeft", [])[1:]]
    rates_r = [s.get("strokeRate", 0) for s in phase.get("strokesRight", [])[1:]]
    return {
        "strokes_l": len(force_l),
        "strokes_r": len(force_r),
        "peak_force_l": max(force_l) if force_l else 0,
        "peak_force_r": max(force_r) if force_r else 0,
        "avg_force_l": statistics.mean(force_l) if force_l else 0,
        "avg_force_r": statistics.mean(force_r) if force_r else 0,
        "avg_pps_l": statistics.mean(pps_l) if pps_l else 0,
        "avg_pps_r": statistics.mean(pps_r) if pps_r else 0,
        "stroke_rate_l": statistics.mean(rates_l) if rates_l else 0,
        "stroke_rate_r": statistics.mean(rates_r) if rates_r else 0,
        "stroke_rate_cv_l": (statistics.stdev(rates_l) / statistics.mean(rates_l) * 100) if len(rates_l) > 1 and statistics.mean(rates_l) else 0,
        "stroke_rate_cv_r": (statistics.stdev(rates_r) / statistics.mean(rates_r) * 100) if len(rates_r) > 1 and statistics.mean(rates_r) else 0,
        "avg_glide_l": phase.get("lapAvgGlideLeft", 0),
        "avg_pull_l": phase.get("lapAvgPullLeft", 0),
        "avg_recovery_l": phase.get("lapAvgRecoveryLeft", 0),
        "avg_glide_r": phase.get("lapAvgGlideRight", 0),
        "avg_pull_r": phase.get("lapAvgPullRight", 0),
        "avg_recovery_r": phase.get("lapAvgRecoveryRight", 0),
    }


def write_swim_analysis(swim_dir: Path) -> Path:
    swim = load_swim(swim_dir)
    phases = load_lap_files(swim_dir, "strokephase")
    summary = summarize_swim(swim_dir)

    lines = []
    lines.append(f"# Swim analysis — {swim.get('date', '')[:16].replace('T', ' ')}\n")
    lines.append(f"**Location**: {swim.get('poolName', '')} ({swim.get('poolDistance', '')})  ")
    lines.append(f"**Stroke**: {swim.get('stroke', '')}  ")
    lines.append(f"**Distance**: {summary['distance']} m in {summary['laps']} laps  ")
    lines.append(f"**Duration**: {format_seconds(summary['duration_s'])}  ")
    lines.append(f"**Pace**: {format_seconds(summary['pace_per100m_s'])} / 100m\n")

    lines.append("## Session metrics\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Avg velocity | {summary['avgVelocity']} m/s |")
    lines.append(f"| Avg stroke rate | {summary['avgStrokeRate']} strokes/min |")
    lines.append(f"| Avg distance per stroke (DPS) | {summary['avgDps']} m |")
    lines.append(f"| Avg force per stroke | {summary['avgFps']} N |")
    lines.append(f"| Avg power per stroke | {summary['avgPps2']} W |")
    lines.append(f"| Propulsion | {summary['propulsion']} |")
    lines.append(f"| Work | {summary['work']} J |")
    lines.append(f"| Strokes L / R | {summary['totalStrokesLeft']} / {summary['totalStrokesRight']} |")
    lines.append(f"| L/R balance | {summary['lrBalance']}% left |\n")

    if phases:
        lines.append("## Per-lap stroke analysis\n")
        lines.append("| Lap | Strokes L/R | Peak force L/R (N) | Avg PPS L/R (W) | Pull L/R (ms) | Stroke rate CV L/R (%) |")
        lines.append("|---|---|---|---|---|---|")
        for lap_num, phase in phases:
            a = analyze_strokephase(phase)
            lines.append(
                f"| {lap_num} | {a['strokes_l']}/{a['strokes_r']} "
                f"| {a['peak_force_l']:.1f} / {a['peak_force_r']:.1f} "
                f"| {a['avg_pps_l']:.1f} / {a['avg_pps_r']:.1f} "
                f"| {a['avg_pull_l']} / {a['avg_pull_r']} "
                f"| {a['stroke_rate_cv_l']:.1f} / {a['stroke_rate_cv_r']:.1f} |"
            )
        lines.append("")

        lines.append("## Observations\n")
        observations = generate_observations(summary, phases)
        for obs in observations:
            lines.append(f"- {obs}")

    out = swim_dir / "analysis.md"
    out.write_text("\n".join(lines))
    return out


def generate_observations(summary: dict, phases: list[dict]) -> list[str]:
    obs = []
    bal = summary["lrBalance"]
    if abs(bal - 50) > 3:
        side = "left" if bal > 50 else "right"
        obs.append(f"L/R imbalance: {bal:.1f}% strokes on left — slight {side} dominance.")
    else:
        obs.append(f"L/R balance is even ({bal:.1f}% left).")

    all_left_force = []
    all_right_force = []
    for _, phase in phases:
        ind = phase.get("indicator", {})
        all_left_force.extend(ind.get("forceLeft") or [])
        all_right_force.extend(ind.get("forceRight") or [])

    if all_left_force and all_right_force:
        l_avg = statistics.mean(all_left_force)
        r_avg = statistics.mean(all_right_force)
        diff_pct = (r_avg - l_avg) / ((l_avg + r_avg) / 2) * 100
        stronger = "right" if diff_pct > 0 else "left"
        obs.append(
            f"Avg force {l_avg:.1f} N (L) vs {r_avg:.1f} N (R) — {stronger} hand "
            f"produces {abs(diff_pct):.1f}% more force on average."
        )

    rates = []
    for _, phase in phases:
        for s in (phase.get("strokesLeft") or [])[1:]:
            r = s.get("strokeRate")
            if r:
                rates.append(r)
        for s in (phase.get("strokesRight") or [])[1:]:
            r = s.get("strokeRate")
            if r:
                rates.append(r)
    if len(rates) > 2:
        cv = statistics.stdev(rates) / statistics.mean(rates) * 100
        verdict = "very consistent" if cv < 5 else "consistent" if cv < 10 else "variable"
        obs.append(f"Stroke-rate consistency: CV {cv:.1f}% across all strokes — {verdict}.")

    if summary["pace_per100m_s"]:
        obs.append(f"Pace equivalent: {format_seconds(summary['pace_per100m_s'])} per 100 m.")

    return obs


def plot_force_time(swim_dir: Path, plots_dir: Path) -> None:
    phases = load_lap_files(swim_dir, "strokephase")
    for lap_num, phase in phases:
        ind = phase.get("indicator", {})
        t_l = [t / 1000 for t in (ind.get("timeLeft") or [])]
        f_l = ind.get("forceLeft") or []
        t_r = [t / 1000 for t in (ind.get("timeRight") or [])]
        f_r = ind.get("forceRight") or []
        if not t_l and not t_r:
            continue
        fig, ax = plt.subplots(figsize=(10, 4))
        if t_l:
            ax.plot(t_l, f_l, "o-", color="#1f77b4", label="Left")
        if t_r:
            ax.plot(t_r, f_r, "o-", color="#d62728", label="Right")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Peak force per stroke (N)")
        ax.set_title(f"Lap {lap_num} — peak force per stroke")
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(plots_dir / f"lap-{lap_num:02d}-force.png", dpi=120)
        plt.close(fig)


def _all_strokes(payload: dict, side: str) -> list[dict]:
    return payload.get(f"strokes{side}") or []


def plot_path_sweep(swim_dir: Path, plots_dir: Path) -> None:
    sweeps = load_lap_files(swim_dir, "pathsweep")
    for lap_num, sweep in sweeps:
        fig, ax = plt.subplots(figsize=(8, 5))
        for stroke in _all_strokes(sweep, "Left"):
            x = stroke.get("xAxis") or []
            y = stroke.get("sweep") or []
            if x and y:
                ax.plot(x, y, color="#1f77b4", alpha=0.4, linewidth=0.8)
        for stroke in _all_strokes(sweep, "Right"):
            x = stroke.get("xAxis") or []
            y = stroke.get("sweep") or []
            if x and y:
                ax.plot(x, y, color="#d62728", alpha=0.4, linewidth=0.8)
        ax.set_xlabel("Stroke axis (m)")
        ax.set_ylabel("Sweep (m)")
        ax.set_title(f"Lap {lap_num} — hand path (overhead view)")
        ax.axhline(0, color="black", linewidth=0.5, alpha=0.4)
        ax.axvline(0, color="black", linewidth=0.5, alpha=0.4)
        ax.grid(True, alpha=0.3)
        ax.set_aspect("equal", adjustable="datalim")
        from matplotlib.lines import Line2D
        ax.legend(handles=[
            Line2D([], [], color="#1f77b4", label="Left"),
            Line2D([], [], color="#d62728", label="Right"),
        ])
        fig.tight_layout()
        fig.savefig(plots_dir / f"lap-{lap_num:02d}-sweep.png", dpi=120)
        plt.close(fig)


def plot_path_depth(swim_dir: Path, plots_dir: Path) -> None:
    depths = load_lap_files(swim_dir, "pathdepth")
    for lap_num, depth in depths:
        fig, ax = plt.subplots(figsize=(8, 5))
        for stroke in _all_strokes(depth, "Left"):
            x = stroke.get("xAxis") or []
            y = stroke.get("depth") or []
            if x and y:
                ax.plot(x, y, color="#1f77b4", alpha=0.4, linewidth=0.8)
        for stroke in _all_strokes(depth, "Right"):
            x = stroke.get("xAxis") or []
            y = stroke.get("depth") or []
            if x and y:
                ax.plot(x, y, color="#d62728", alpha=0.4, linewidth=0.8)
        ax.set_xlabel("Stroke axis (m)")
        ax.set_ylabel("Depth (m) — negative = below water")
        ax.set_title(f"Lap {lap_num} — hand path (side view)")
        ax.axhline(0, color="black", linewidth=0.5, alpha=0.4)
        ax.grid(True, alpha=0.3)
        ax.set_aspect("equal", adjustable="datalim")
        from matplotlib.lines import Line2D
        ax.legend(handles=[
            Line2D([], [], color="#1f77b4", label="Left"),
            Line2D([], [], color="#d62728", label="Right"),
        ])
        fig.tight_layout()
        fig.savefig(plots_dir / f"lap-{lap_num:02d}-depth.png", dpi=120)
        plt.close(fig)


def plot_trend(swim_dirs: list[Path], out_path: Path) -> None:
    summaries = []
    for d in swim_dirs:
        try:
            summaries.append(summarize_swim(d))
        except Exception:
            pass
    summaries = [s for s in summaries if s["date"]]
    summaries.sort(key=lambda s: s["date"])
    if len(summaries) < 2:
        return
    dates = [s["date"][:10] for s in summaries]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    axes[0, 0].plot(dates, [s["avgVelocity"] for s in summaries], "o-")
    axes[0, 0].set_title("Avg velocity (m/s)")
    axes[0, 1].plot(dates, [s["avgStrokeRate"] for s in summaries], "o-", color="#d62728")
    axes[0, 1].set_title("Avg stroke rate (strokes/min)")
    axes[1, 0].plot(dates, [s["avgDps"] for s in summaries], "o-", color="#2ca02c")
    axes[1, 0].set_title("Avg distance per stroke (m)")
    axes[1, 1].plot(dates, [s["propulsion"] for s in summaries], "o-", color="#9467bd")
    axes[1, 1].set_title("Propulsion")
    for ax in axes.flat:
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def main() -> int:
    if not DATA_DIR.exists():
        print(f"No data directory at {DATA_DIR}. Run fetch_all_swims.py first.", file=sys.stderr)
        return 1

    swim_dirs = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and (d / "swim.json").exists()])
    if not swim_dirs:
        print(f"No swim subdirectories found in {DATA_DIR}.", file=sys.stderr)
        return 1

    summary_path = DATA_DIR / "summary.csv"
    count = write_summary_csv(swim_dirs, summary_path)
    print(f"Wrote {summary_path} ({count} swims)")

    for d in swim_dirs:
        analysis_path = write_swim_analysis(d)
        plots_dir = d / "plots"
        plots_dir.mkdir(exist_ok=True)
        plot_force_time(d, plots_dir)
        plot_path_sweep(d, plots_dir)
        plot_path_depth(d, plots_dir)
        print(f"  {d.name}: analysis + plots")

    trend_path = DATA_DIR / "trend.png"
    plot_trend(swim_dirs, trend_path)
    if trend_path.exists():
        print(f"Wrote {trend_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
