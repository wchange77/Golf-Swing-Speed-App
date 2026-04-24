from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PLATFORM_ROOT / "tools"


def run_tool(name: str, args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / name)] + args,
        cwd=str(cwd or PLATFORM_ROOT),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result.stdout.strip()


@pytest.fixture()
def workspace(tmp_path):
    import shutil
    ws = tmp_path / "DatasetCollectionPlatform"
    shutil.copytree(PLATFORM_ROOT, ws, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
    return ws


def _run_in_workspace(workspace: Path, name: str, args: list[str]) -> str:
    result = subprocess.run(
        [sys.executable, f"tools/{name}"] + args,
        cwd=str(workspace),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result.stdout.strip()


class TestStartSession:
    def test_creates_session(self, workspace):
        output = _run_in_workspace(workspace, "start_session.py", [
            "--collector", "tester",
            "--device", "TestDevice",
            "--scene-type", "indoor",
            "--lighting", "indoor_led",
            "--tripod",
        ])
        session_id = output.splitlines()[-1]
        assert session_id.startswith("sess_")

        sessions_file = workspace / "datasets" / "registry" / "sessions.jsonl"
        assert sessions_file.exists()
        lines = [json.loads(l) for l in sessions_file.read_text().strip().splitlines()]
        assert len(lines) == 1
        assert lines[0]["sessionId"] == session_id
        assert lines[0]["collector"] == "tester"


class TestEndToEnd:
    def test_full_pipeline(self, workspace):
        session_id = _run_in_workspace(workspace, "start_session.py", [
            "--collector", "e2e_tester",
            "--device", "TestDevice",
            "--scene-type", "indoor",
            "--lighting", "indoor_led",
            "--tripod",
            "--target-domains", "human_club,golf_ball_detection",
        ]).splitlines()[-1]

        sample_dir = workspace / "test_samples"
        sample_dir.mkdir()
        ann_dir = workspace / "test_annotations"
        ann_dir.mkdir()

        (sample_dir / "img_001.jpg").write_bytes(b"human-sample-001")
        (ann_dir / "img_001.json").write_text('{"keypoints": []}', encoding="utf-8")
        (sample_dir / "img_002.jpg").write_bytes(b"human-sample-002")
        (sample_dir / "ball_001.jpg").write_bytes(b"ball-sample-001")
        (ann_dir / "ball_001.txt").write_text("0 0.5 0.5 0.1 0.1", encoding="utf-8")
        (sample_dir / "img_001_dup.jpg").write_bytes(b"human-sample-001")

        _run_in_workspace(workspace, "register_sample.py", [
            "--domain", "human_club",
            "--file", str(sample_dir / "img_001.jpg"),
            "--annotation", str(ann_dir / "img_001.json"),
            "--session-id", session_id,
            "--collector", "e2e_tester",
            "--shot-id", "shot_001",
        ])
        _run_in_workspace(workspace, "register_sample.py", [
            "--domain", "human_club",
            "--file", str(sample_dir / "img_002.jpg"),
            "--session-id", session_id,
            "--collector", "e2e_tester",
            "--shot-id", "shot_002",
        ])
        dup_output = _run_in_workspace(workspace, "register_sample.py", [
            "--domain", "human_club",
            "--file", str(sample_dir / "img_001_dup.jpg"),
            "--session-id", session_id,
            "--collector", "e2e_tester",
            "--shot-id", "shot_003",
        ])
        assert "DUPLICATE" in dup_output

        _run_in_workspace(workspace, "register_sample.py", [
            "--domain", "golf_ball_detection",
            "--file", str(sample_dir / "ball_001.jpg"),
            "--annotation", str(ann_dir / "ball_001.txt"),
            "--session-id", session_id,
            "--collector", "e2e_tester",
            "--shot-id", "ball_001",
        ])

        _run_in_workspace(workspace, "split_dataset.py", [
            "--domain", "human_club", "--strategy", "session", "--seed", "42",
        ])
        _run_in_workspace(workspace, "split_dataset.py", [
            "--domain", "golf_ball_detection", "--strategy", "session", "--seed", "42",
        ])

        _run_in_workspace(workspace, "generate_manifest.py", [])

        manifest_path = workspace / "exports" / "dataset_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["registry"]["uniqueSamples"] == 3
        assert manifest["registry"]["duplicateSamples"] == 1

        human_ds = next(d for d in manifest["datasets"] if d["key"] == "human_club")
        assert human_ds["samples"] == 2
        ball_ds = next(d for d in manifest["datasets"] if d["key"] == "golf_ball_detection")
        assert ball_ds["samples"] == 1

        assert len(manifest["consumers"]) == 3

        validation_output = _run_in_workspace(workspace, "validate_registry.py", [])
        validation = json.loads(validation_output.splitlines()[0])
        assert validation["errors"] == 0

        _run_in_workspace(workspace, "generate_quality_report.py", [])
        report_json = workspace / "analysis" / "reports" / "quality_report.json"
        assert report_json.exists()
        report = json.loads(report_json.read_text())
        assert report["summary"]["activeSamples"] == 3
        assert report["summary"]["duplicateEvents"] == 1


class TestSplitDataset:
    def test_session_isolation(self, workspace):
        s1 = _run_in_workspace(workspace, "start_session.py", [
            "--collector", "a", "--device", "D1",
            "--scene-type", "indoor", "--lighting", "led", "--tripod",
            "--target-domains", "human_club",
        ]).splitlines()[-1]
        s2 = _run_in_workspace(workspace, "start_session.py", [
            "--collector", "b", "--device", "D2",
            "--scene-type", "outdoor", "--lighting", "sun",
            "--target-domains", "human_club",
        ]).splitlines()[-1]

        sample_dir = workspace / "split_samples"
        sample_dir.mkdir()
        for i in range(5):
            (sample_dir / f"s1_{i}.jpg").write_bytes(f"session1-sample-{i}".encode())
        for i in range(3):
            (sample_dir / f"s2_{i}.jpg").write_bytes(f"session2-sample-{i}".encode())

        for i in range(5):
            _run_in_workspace(workspace, "register_sample.py", [
                "--domain", "human_club",
                "--file", str(sample_dir / f"s1_{i}.jpg"),
                "--session-id", s1,
                "--shot-id", f"s1_shot_{i}",
            ])
        for i in range(3):
            _run_in_workspace(workspace, "register_sample.py", [
                "--domain", "human_club",
                "--file", str(sample_dir / f"s2_{i}.jpg"),
                "--session-id", s2,
                "--shot-id", f"s2_shot_{i}",
            ])

        output = _run_in_workspace(workspace, "split_dataset.py", [
            "--domain", "human_club", "--strategy", "session", "--seed", "42",
        ])
        counts = json.loads(output)
        assert counts["train"] + counts["val"] + counts["test"] == 8

        split_file = workspace / "exports" / "splits" / "human_club.json"
        assert split_file.exists()
        split_meta = json.loads(split_file.read_text())
        train_ids = set(split_meta["sampleIds"]["train"])
        val_ids = set(split_meta["sampleIds"]["val"])
        test_ids = set(split_meta["sampleIds"]["test"])
        assert not (train_ids & val_ids)
        assert not (train_ids & test_ids)
        assert not (val_ids & test_ids)
