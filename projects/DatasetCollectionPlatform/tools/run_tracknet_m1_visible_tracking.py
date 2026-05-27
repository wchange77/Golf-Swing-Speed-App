from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib.tracknet_m1_visible_tracking import build_visible_tracking_artifact


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _require_directory(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")


def _clear_stale_trajectory_jsons(trajectories_dir: Path) -> None:
    if trajectories_dir.exists() and not trajectories_dir.is_dir():
        raise ValueError(f"output trajectories path is not a directory: {trajectories_dir}")
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in trajectories_dir.glob("*.json"):
        stale_path.unlink()


def run_visible_tracking(
    *,
    ball_trajectories_dir: Path | str,
    clubhead_trajectories_dir: Path | str,
    output_dir: Path | str,
) -> dict[str, Any]:
    ball_trajectories_dir = Path(ball_trajectories_dir)
    clubhead_trajectories_dir = Path(clubhead_trajectories_dir)
    output_dir = Path(output_dir)
    trajectories_dir = output_dir / "trajectories"

    _require_directory(ball_trajectories_dir, "ball trajectories directory")
    _clear_stale_trajectory_jsons(trajectories_dir)

    processed = 0
    failed = 0
    trajectories: list[str] = []
    missing_clubhead: list[str] = []
    failures: list[dict[str, str]] = []
    status_counts: dict[str, int] = {"ok": 0, "needs_review": 0, "failed": 0}

    for ball_path in sorted(ball_trajectories_dir.glob("*.json")):
        try:
            ball_trajectory = _read_json(ball_path)
            sample_id = str(ball_trajectory.get("sampleId") or ball_path.stem)
            clubhead_path = clubhead_trajectories_dir / ball_path.name
            clubhead_trajectory = _read_json(clubhead_path) if clubhead_path.exists() else {}
            if not clubhead_trajectory:
                missing_clubhead.append(sample_id)

            artifact = build_visible_tracking_artifact(ball_trajectory, clubhead_trajectory)
            output_path = trajectories_dir / ball_path.name
            _write_json(output_path, artifact)

            processed += 1
            status = str((artifact.get("qc") or {}).get("status") or "needs_review")
            status_counts[status] = status_counts.get(status, 0) + 1
            trajectories.append(str(output_path))
        except Exception as exc:
            failed += 1
            status_counts["failed"] = status_counts.get("failed", 0) + 1
            failures.append({"path": str(ball_path), "error": str(exc)})

    report = {
        "version": "1.0",
        "stage": "m1_visible_tracking",
        "ballTrajectoriesDir": str(ball_trajectories_dir),
        "clubheadTrajectoriesDir": str(clubhead_trajectories_dir),
        "outputDir": str(output_dir),
        "processed": processed,
        "failed": failed,
        "missingClubhead": missing_clubhead,
        "statusCounts": status_counts,
        "trajectories": trajectories,
        "failures": failures,
    }
    _write_json(output_dir / "visible_tracking_report.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Build M1 stage-one visible tracking artifacts")
    parser.add_argument(
        "--ball-trajectories-dir",
        type=Path,
        default=annotation_root / "work/m1_flight_tracking_batch/trajectories",
    )
    parser.add_argument(
        "--clubhead-trajectories-dir",
        type=Path,
        default=annotation_root / "work/m1_sota_tracking/trajectories",
    )
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "work/m1_visible_tracking")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_visible_tracking(
        ball_trajectories_dir=args.ball_trajectories_dir,
        clubhead_trajectories_dir=args.clubhead_trajectories_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps({"processed": report["processed"], "outputDir": report["outputDir"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
