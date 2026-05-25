from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def workspace(tmp_path):
    ws = tmp_path / "DatasetCollectionPlatform"
    shutil.copytree(
        PLATFORM_ROOT,
        ws,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "tests",
            ".pytest_cache",
            "DatasetCollectorExport",
            "datasets",
            "exports",
        ),
    )
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


def test_tracknet_m1_smoke_runs_fixture_pipeline(workspace):
    output = _run_in_workspace(workspace, "smoke_tracknet_m1.py", ["--output-dir", "exports/tracknet_m1_smoke"])
    report = json.loads(output)
    assert report["status"] == "ok"
    assert report["sota"]["processed"] == 1
    assert report["sota"]["reviewTasks"] == 1
    assert (workspace / "exports" / "tracknet_m1_smoke" / "package" / "manifest.json").exists()
    assert (workspace / "exports" / "tracknet_m1_smoke" / "package" / "labels.csv").exists()
    assert (workspace / "exports" / "tracknet_m1_smoke" / "sota_tracking" / "tracking_report.json").exists()
    assert (workspace / "exports" / "tracknet_m1_smoke" / "sota_review" / "labelstudio" / "tracknet_m1_tasks.json").exists()
