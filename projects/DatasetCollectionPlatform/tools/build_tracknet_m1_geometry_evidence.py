from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from lib.tracknet_m1_geometry_evidence import build_geometry_evidence


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sample_id(path: Path, payload: dict[str, Any]) -> str:
    value = payload.get("sampleId") or path.stem
    if not isinstance(value, str) or not value or Path(value).name != value or "/" in value or "\\" in value or ".." in value:
        raise ValueError(f"unsafe sampleId: {value}")
    return value


def _camera_path(camera_models_dir: Path, sample_id: str) -> Path | None:
    candidates = [
        camera_models_dir / f"{sample_id}.camera_model.json",
        camera_models_dir / "models" / f"{sample_id}.camera_model.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _read_json(path)


def build_geometry_evidence_batch(
    *,
    visible_trajectories_dir: Path | str,
    camera_models_dir: Path | str | None = None,
    depth_evidence_dir: Path | str | None = None,
    output_dir: Path | str,
) -> dict[str, Any]:
    visible_trajectories_dir = Path(visible_trajectories_dir)
    output_dir = Path(output_dir)
    camera_models_dir = Path(camera_models_dir) if camera_models_dir is not None else None
    depth_evidence_dir = Path(depth_evidence_dir) if depth_evidence_dir is not None else None
    if not visible_trajectories_dir.exists() or not visible_trajectories_dir.is_dir():
        raise ValueError(f"visible trajectories dir does not exist or is not a directory: {visible_trajectories_dir}")

    evidence_dir = output_dir / "evidence"
    status_counts: Counter[str] = Counter()
    evidence_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    processed = 0
    for visible_path in sorted(visible_trajectories_dir.glob("*.json")):
        try:
            visible = _read_json(visible_path)
            sample_id = _sample_id(visible_path, visible)
            camera_payload: dict[str, Any] = {}
            if camera_models_dir is not None:
                path = _camera_path(camera_models_dir, sample_id)
                if path is not None:
                    camera_payload = _read_json(path)
            depth_payload = None
            if depth_evidence_dir is not None:
                depth_payload = _optional_json(depth_evidence_dir / f"{sample_id}.depth.json")
            evidence = build_geometry_evidence(visible, camera_payload, depth_evidence=depth_payload)
            output_path = evidence_dir / f"{sample_id}.geometry_evidence.json"
            _write_json(output_path, evidence)
            processed += 1
            status_counts[str(evidence.get("status"))] += 1
            evidence_rows.append({"sampleId": sample_id, "status": evidence.get("status"), "path": str(output_path)})
        except Exception as exc:
            failures.append({"path": str(visible_path), "error": str(exc)})
            status_counts["failed"] += 1
    report = {
        "version": "1.0",
        "visibleTrajectoriesDir": str(visible_trajectories_dir),
        "cameraModelsDir": None if camera_models_dir is None else str(camera_models_dir),
        "depthEvidenceDir": None if depth_evidence_dir is None else str(depth_evidence_dir),
        "outputDir": str(output_dir),
        "processed": processed,
        "failed": len(failures),
        "statusCounts": dict(status_counts),
        "evidence": evidence_rows,
        "failures": failures,
    }
    _write_json(output_dir / "geometry_evidence_report.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Build M2 geometry evidence packages")
    parser.add_argument("--visible-trajectories-dir", type=Path, default=annotation_root / "work/m1_visible_tracking/trajectories")
    parser.add_argument("--camera-models-dir", type=Path, default=annotation_root / "work/m1_camera_models/models")
    parser.add_argument("--depth-evidence-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "work/m1_geometry_evidence")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_geometry_evidence_batch(
        visible_trajectories_dir=args.visible_trajectories_dir,
        camera_models_dir=args.camera_models_dir,
        depth_evidence_dir=args.depth_evidence_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps({"processed": report["processed"], "failed": report["failed"], "outputDir": report["outputDir"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
