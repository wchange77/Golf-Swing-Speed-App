from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

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


class TestStartSession:
    def test_creates_session(self, workspace):
        output = _run_in_workspace(workspace, "start_session.py", [
            "--collector", "tester",
            "--session-name", "1",
            "--device", "TestDevice",
            "--scene-type", "indoor",
            "--lighting", "indoor_led",
            "--tripod",
            "--latitude", "37.3318",
            "--longitude", "-122.0312",
            "--horizontal-accuracy-m", "3.5",
        ])
        session_id = output.splitlines()[-1]
        assert session_id.startswith("sess_")

        sessions_file = workspace / "datasets" / "registry" / "sessions.jsonl"
        assert sessions_file.exists()
        lines = [json.loads(l) for l in sessions_file.read_text().strip().splitlines()]
        assert len(lines) == 1
        assert lines[0]["sessionId"] == session_id
        assert lines[0]["sessionName"] == "1"
        assert lines[0]["collector"] == "tester"
        assert lines[0]["location"]["source"] == "manual_cli"

    def test_import_android_landing_gps(self, workspace):
        session_id = _run_in_workspace(workspace, "start_session.py", [
            "--collector", "landing_tester",
            "--session-name", "7",
            "--device", "TestDevice",
            "--scene-type", "outdoor",
            "--lighting", "sunlight",
            "--tripod",
            "--target-domains", "golf_ball_detection",
        ]).splitlines()[-1]

        sample_dir = workspace / "landing_samples"
        sample_dir.mkdir()
        sample_file = sample_dir / "ball.mov"
        sample_file.write_bytes(b"landing-sample")
        _run_in_workspace(workspace, "register_sample.py", [
            "--domain", "golf_ball_detection",
            "--file", str(sample_file),
            "--session-id", session_id,
            "--collector", "landing_tester",
            "--shot-id", "shot_landing",
        ])

        android_jsonl = workspace / "landing_points.jsonl"
        android_jsonl.write_text(json.dumps({
            "sessionName": "7",
            "capturedAt": "2026-04-24T00:00:00.000Z",
            "source": "android_landing_point",
            "device": "Xiaomi flagship",
            "landingLocation": {
                "latitude": 37.3318,
                "longitude": -122.0312,
                "horizontalAccuracyMeters": 2.4,
                "altitudeMeters": 10.0,
                "verticalAccuracyMeters": 3.0,
                "capturedAt": "2026-04-24T00:00:00.000Z",
                "source": "android_landing_point",
            },
        }, ensure_ascii=False) + "\n", encoding="utf-8")

        output = _run_in_workspace(workspace, "import_android_landing_gps.py", [
            "--android-jsonl", str(android_jsonl),
        ])
        stats = json.loads(output)
        assert stats["matchedRows"] == 1
        assert stats["updatedSamples"] == 1

        samples_file = workspace / "datasets" / "registry" / "samples.jsonl"
        samples = [json.loads(l) for l in samples_file.read_text().strip().splitlines()]
        measurement = samples[0]["metadata"]["referenceMeasurements"][0]
        assert measurement["source"] == "android_landing_point"
        assert measurement["landingLocation"]["horizontalAccuracyMeters"] == 2.4

    def test_import_android_landing_gps_prefers_take_index_match(self, workspace):
        session_id = _run_in_workspace(workspace, "start_session.py", [
            "--collector", "landing_tester",
            "--session-name", "8",
            "--device", "TestDevice",
            "--scene-type", "outdoor",
            "--lighting", "sunlight",
            "--tripod",
            "--target-domains", "golf_ball_detection",
        ]).splitlines()[-1]

        sample_dir = workspace / "landing_take_samples"
        sample_dir.mkdir()
        for take in (1, 2):
            sample_file = sample_dir / f"ball_take_{take}.mov"
            sample_file.write_bytes(f"landing-sample-take-{take}".encode())
            _run_in_workspace(workspace, "register_sample.py", [
                "--domain", "golf_ball_detection",
                "--file", str(sample_file),
                "--session-id", session_id,
                "--collector", "landing_tester",
                "--shot-id", f"shot_landing_{take}",
                "--take-index", str(take),
            ])

        android_jsonl = workspace / "landing_points_take.jsonl"
        android_jsonl.write_text(json.dumps({
            "sessionName": "8",
            "takeIndex": 2,
            "capturedAt": "2026-04-24T00:00:02.000Z",
            "device": "AndroidTest",
            "landingLocation": {
                "latitude": 37.3319,
                "longitude": -122.0313,
                "horizontalAccuracyMeters": 1.8,
                "capturedAt": "2026-04-24T00:00:02.000Z",
                "source": "android_landing_point",
            },
        }, ensure_ascii=False) + "\n", encoding="utf-8")

        output = _run_in_workspace(workspace, "import_android_landing_gps.py", [
            "--android-jsonl", str(android_jsonl),
            "--strict",
        ])
        stats = json.loads(output)
        assert stats["matchedRows"] == 1
        assert stats["updatedSamples"] == 1
        assert stats["takeIndexMatches"] == 1
        assert stats["sessionFallbackMatches"] == 0

        samples_file = workspace / "datasets" / "registry" / "samples.jsonl"
        samples = [json.loads(l) for l in samples_file.read_text().strip().splitlines()]
        by_take = {sample["takeIndex"]: sample for sample in samples}
        assert "referenceMeasurements" not in by_take[1]["metadata"]
        measurement = by_take[2]["metadata"]["referenceMeasurements"][0]
        assert measurement["landingLocation"]["horizontalAccuracyMeters"] == 1.8

    def test_import_android_landing_gps_skips_ambiguous_session_name(self, workspace):
        for collector in ("a", "b"):
            _run_in_workspace(workspace, "start_session.py", [
                "--collector", collector,
                "--session-name", "dup",
                "--device", "TestDevice",
                "--scene-type", "outdoor",
                "--lighting", "sunlight",
                "--target-domains", "golf_ball_detection",
            ])

        android_jsonl = workspace / "landing_points_ambiguous.jsonl"
        android_jsonl.write_text(json.dumps({
            "sessionName": "dup",
            "capturedAt": "2026-04-24T00:00:00.000Z",
            "landingLocation": {
                "latitude": 37.3318,
                "longitude": -122.0312,
                "horizontalAccuracyMeters": 2.4,
                "capturedAt": "2026-04-24T00:00:00.000Z",
                "source": "android_landing_point",
            },
        }, ensure_ascii=False) + "\n", encoding="utf-8")

        output = _run_in_workspace(workspace, "import_android_landing_gps.py", [
            "--android-jsonl", str(android_jsonl),
        ])
        stats = json.loads(output)
        assert stats["matchedRows"] == 0
        assert stats["updatedSamples"] == 0
        assert stats["ambiguousRows"] == 1

    def test_register_sample_rejects_domain_outside_session_targets(self, workspace):
        session_id = _run_in_workspace(workspace, "start_session.py", [
            "--collector", "domain_tester",
            "--device", "TestDevice",
            "--scene-type", "indoor",
            "--lighting", "indoor_led",
            "--target-domains", "human_club",
        ]).splitlines()[-1]

        sample_dir = workspace / "domain_samples"
        sample_dir.mkdir()
        sample_file = sample_dir / "ball.jpg"
        sample_file.write_bytes(b"ball-domain-mismatch")

        result = subprocess.run(
            [
                sys.executable,
                "tools/register_sample.py",
                "--domain", "golf_ball_detection",
                "--file", str(sample_file),
                "--session-id", session_id,
            ],
            cwd=str(workspace),
            text=True,
            capture_output=True,
        )
        assert result.returncode != 0
        assert "not declared in session targetDomains" in result.stderr

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


class TestTrackmanExportImport:
    def _make_jpeg(self, size=(32, 32), color=(120, 80, 40)) -> bytes:
        image = Image.new("RGB", size, color)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()

    def test_time_alignment_and_bundle_output(self, workspace):
        export_dir = workspace / "DatasetCollectorExport"
        export_dir.mkdir()

        sessions = [{
            "sessionId": "sess_trackman_001",
            "sessionName": "1",
            "collector": "tester",
            "device": "iPhone17Max",
            "deviceProfile": "iphone17max",
            "createdAt": "2026-05-10T02:00:00.000Z",
            "status": "active",
        }]
        (export_dir / "sessions.jsonl").write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in sessions) + "\n",
            encoding="utf-8",
        )

        sample_rows = [
            {
                "sampleId": "human_001",
                "domain": "human_club",
                "sha256": "1" * 64,
                "hashAlgorithm": "sha256",
                "assetPath": "datasets/raw/human_club/assets/11/1111111111111111111111111111111111111111111111111111111111111111.mov",
                "annotationPath": None,
                "fileSize": 100,
                "sessionId": "sess_trackman_001",
                "collector": "tester",
                "device": "iPhone17Max",
                "deviceProfile": "iphone17max",
                "capturedAt": "2026-05-10T10:00:00.000Z",
                "sourcePath": "ios://capture/sess_trackman_001/shot_001",
                "shotId": "shot_001",
                "takeIndex": 1,
                "tags": [],
                "metadata": {
                    "fps": 240,
                    "resolution": "1920x1080",
                    "clubType": "driver",
                    "handedness": "right",
                    "swingIntensity": "normal",
                    "surface": "mat",
                },
                "status": "active",
            },
            {
                "sampleId": "ball_001",
                "domain": "golf_ball_detection",
                "sha256": "2" * 64,
                "hashAlgorithm": "sha256",
                "assetPath": "datasets/raw/golf_ball_detection/assets/22/2222222222222222222222222222222222222222222222222222222222222222.mov",
                "annotationPath": None,
                "fileSize": 100,
                "sessionId": "sess_trackman_001",
                "collector": "tester",
                "device": "iPhone17Max",
                "deviceProfile": "iphone17max",
                "capturedAt": "2026-05-10T10:00:00.000Z",
                "sourcePath": "ios://capture/sess_trackman_001/shot_001",
                "shotId": "shot_001",
                "takeIndex": 1,
                "tags": [],
                "metadata": {
                    "fps": 240,
                    "resolution": "1920x1080",
                    "clubType": "driver",
                    "handedness": "right",
                    "swingIntensity": "normal",
                    "surface": "mat",
                },
                "status": "active",
            },
            {
                "sampleId": "human_002",
                "domain": "human_club",
                "sha256": "3" * 64,
                "hashAlgorithm": "sha256",
                "assetPath": "datasets/raw/human_club/assets/33/3333333333333333333333333333333333333333333333333333333333333333.mov",
                "annotationPath": None,
                "fileSize": 100,
                "sessionId": "sess_trackman_001",
                "collector": "tester",
                "device": "iPhone17Max",
                "deviceProfile": "iphone17max",
                "capturedAt": "2026-05-10T10:00:30.000Z",
                "sourcePath": "ios://capture/sess_trackman_001/shot_002",
                "shotId": "shot_002",
                "takeIndex": 1,
                "tags": [],
                "metadata": {
                    "fps": 240,
                    "resolution": "1920x1080",
                    "clubType": "iron",
                    "handedness": "right",
                    "swingIntensity": "normal",
                    "surface": "mat",
                },
                "status": "active",
            },
            {
                "sampleId": "ball_002",
                "domain": "golf_ball_detection",
                "sha256": "4" * 64,
                "hashAlgorithm": "sha256",
                "assetPath": "datasets/raw/golf_ball_detection/assets/44/4444444444444444444444444444444444444444444444444444444444444444.mov",
                "annotationPath": None,
                "fileSize": 100,
                "sessionId": "sess_trackman_001",
                "collector": "tester",
                "device": "iPhone17Max",
                "deviceProfile": "iphone17max",
                "capturedAt": "2026-05-10T10:00:30.000Z",
                "sourcePath": "ios://capture/sess_trackman_001/shot_002",
                "shotId": "shot_002",
                "takeIndex": 1,
                "tags": [],
                "metadata": {
                    "fps": 240,
                    "resolution": "1920x1080",
                    "clubType": "iron",
                    "handedness": "right",
                    "swingIntensity": "normal",
                    "surface": "mat",
                },
                "status": "active",
            },
            {
                "sampleId": "human_003",
                "domain": "human_club",
                "sha256": "5" * 64,
                "hashAlgorithm": "sha256",
                "assetPath": "datasets/raw/human_club/assets/55/5555555555555555555555555555555555555555555555555555555555555555.mov",
                "annotationPath": None,
                "fileSize": 100,
                "sessionId": "sess_trackman_001",
                "collector": "tester",
                "device": "iPhone17Max",
                "deviceProfile": "iphone17max",
                "capturedAt": "2026-05-10T10:01:00.000Z",
                "sourcePath": "ios://capture/sess_trackman_001/shot_003",
                "shotId": "shot_003",
                "takeIndex": 1,
                "tags": [],
                "metadata": {
                    "fps": 240,
                    "resolution": "1920x1080",
                    "clubType": "driver",
                    "handedness": "right",
                    "swingIntensity": "normal",
                    "surface": "mat",
                },
                "status": "active",
            },
            {
                "sampleId": "ball_003",
                "domain": "golf_ball_detection",
                "sha256": "6" * 64,
                "hashAlgorithm": "sha256",
                "assetPath": "datasets/raw/golf_ball_detection/assets/66/6666666666666666666666666666666666666666666666666666666666666666.mov",
                "annotationPath": None,
                "fileSize": 100,
                "sessionId": "sess_trackman_001",
                "collector": "tester",
                "device": "iPhone17Max",
                "deviceProfile": "iphone17max",
                "capturedAt": "2026-05-10T10:01:00.000Z",
                "sourcePath": "ios://capture/sess_trackman_001/shot_003",
                "shotId": "shot_003",
                "takeIndex": 1,
                "tags": [],
                "metadata": {
                    "fps": 240,
                    "resolution": "1920x1080",
                    "clubType": "driver",
                    "handedness": "right",
                    "swingIntensity": "normal",
                    "surface": "mat",
                },
                "status": "active",
            },
        ]
        (export_dir / "samples.jsonl").write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in sample_rows) + "\n",
            encoding="utf-8",
        )

        zip_path = export_dir / "trackman.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename in [
                "IMG_20260510_180002.jpg",
                "IMG_20260510_180101.jpg",
                "IMG_20260510_180500.jpg",
            ]:
                archive.writestr(filename, self._make_jpeg())

        output_dir = workspace / "exports" / "trackman_alignment"
        output = _run_in_workspace(workspace, "import_trackman_export.py", [
            "--export-dir", str(export_dir.relative_to(workspace)),
            "--output-dir", str(output_dir.relative_to(workspace)),
            "--threshold-seconds", "10",
            "--skip-ocr",
        ])
        report = json.loads(output)
        assert report["matchedBundles"] == 2
        assert report["unmatchedShots"] == 1
        assert report["unmatchedPhotos"] == 1

        index_path = output_dir / "index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text())
        assert index["summary"]["matchedShots"] == 2
        assert index["summary"]["unmatchedShots"] == 1
        assert index["summary"]["unmatchedPhotos"] == 1

        bundle_1 = output_dir / "collections" / "sess_trackman_001" / "0001_shot_001" / "bundle.json"
        bundle_2 = output_dir / "collections" / "sess_trackman_001" / "0002_shot_003" / "bundle.json"
        assert bundle_1.exists()
        assert bundle_2.exists()

        bundle_data = json.loads(bundle_1.read_text())
        assert bundle_data["shotId"] == "shot_001"
        assert bundle_data["match"]["timeDeltaSeconds"] == 2.0
        assert bundle_data["trackmanPhotos"][0]["archiveName"] == "IMG_20260510_180002.jpg"
        assert bundle_data["trackmanPhotos"][0]["ocr"]["status"] == "skipped"

        review_path = output_dir / "review" / "review.json"
        review = json.loads(review_path.read_text())
        assert len(review["unmatchedShots"]) == 1
        assert len(review["unmatchedPhotos"]) == 1

    def test_time_alignment_dry_run_does_not_write_output(self, workspace):
        export_dir = workspace / "DatasetCollectorExport"
        export_dir.mkdir()
        (export_dir / "sessions.jsonl").write_text(json.dumps({
            "sessionId": "sess_trackman_dry",
            "sessionName": "dry",
            "collector": "tester",
            "device": "iPhone17Max",
            "deviceProfile": "iphone17max",
            "createdAt": "2026-05-10T02:00:00.000Z",
            "status": "active",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        (export_dir / "samples.jsonl").write_text(json.dumps({
            "sampleId": "human_dry",
            "domain": "human_club",
            "sha256": "7" * 64,
            "hashAlgorithm": "sha256",
            "assetPath": "datasets/raw/human_club/assets/77/7777777777777777777777777777777777777777777777777777777777777777.mov",
            "annotationPath": None,
            "fileSize": 100,
            "sessionId": "sess_trackman_dry",
            "collector": "tester",
            "device": "iPhone17Max",
            "deviceProfile": "iphone17max",
            "capturedAt": "2026-05-10T10:00:00.000Z",
            "sourcePath": "ios://capture/sess_trackman_dry/shot_dry",
            "shotId": "shot_dry",
            "takeIndex": 1,
            "tags": [],
            "metadata": {
                "fps": 240,
                "resolution": "1920x1080",
                "clubType": "driver",
                "handedness": "right",
                "swingIntensity": "normal",
                "surface": "mat",
            },
            "status": "active",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        with zipfile.ZipFile(export_dir / "trackman.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("IMG_20260510_180001.jpg", self._make_jpeg())

        output_dir = workspace / "exports" / "trackman_dry_run"
        output = _run_in_workspace(workspace, "import_trackman_export.py", [
            "--export-dir", str(export_dir.relative_to(workspace)),
            "--output-dir", str(output_dir.relative_to(workspace)),
            "--threshold-seconds", "5",
            "--skip-ocr",
            "--dry-run",
        ])
        report = json.loads(output)
        assert report["matchedBundles"] == 1
        assert report["unmatchedShots"] == 0
        assert report["unmatchedPhotos"] == 0
        assert not output_dir.exists()

    def _make_tracknet_video(self, path: Path, *, fps: int = 60, frames: int = 90) -> None:
        import cv2
        import numpy as np

        path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            float(fps),
            (320, 180),
        )
        assert writer.isOpened()
        try:
            for idx in range(frames):
                frame = np.zeros((180, 320, 3), dtype=np.uint8)
                frame[:, :] = (24, 96, 28)
                # 大面积高速目标：模拟手臂/杆头区域，应该进入 exclusionZones。
                if 31 <= idx <= 60:
                    x = 40 + (idx - 31) * 5
                    cv2.rectangle(frame, (x, 70), (x + 70, 105), (210, 210, 210), -1)
                # 小球：从 impact 后连续向右上方飞出。
                if 33 <= idx <= 58:
                    ball_x = 82 + (idx - 33) * 5
                    ball_y = 120 - (idx - 33) * 2
                    cv2.circle(frame, (ball_x, ball_y), 3, (255, 255, 255), -1)
                writer.write(frame)
        finally:
            writer.release()

    def test_tracknet_autolabel_outputs_non_destructive_candidates(self, workspace):
        export_dir = workspace / "DatasetCollectorExport"
        export_dir.mkdir()
        asset_rel = "ios_export/assets/golf_ball_detection/aa/ball.mov"
        asset_path = export_dir / "assets/golf_ball_detection/aa/ball.mov"
        self._make_tracknet_video(asset_path)

        label_rel = "ios_export/assets/golf_ball_detection/aa/ball.label_candidates.json"
        timeline_rel = "ios_export/assets/golf_ball_detection/aa/ball.timeline.json"
        label_path = export_dir / "assets/golf_ball_detection/aa/ball.label_candidates.json"
        timeline_path = export_dir / "assets/golf_ball_detection/aa/ball.timeline.json"
        label_path.write_text(json.dumps({
            "version": "1.0",
            "status": "needs_review",
            "swingWindow": {
                "impactTimeSeconds": 0.5,
                "startTimeSeconds": 0.35,
                "endTimeSeconds": 0.95,
                "source": "test_fixture",
                "confidence": 0.8,
            },
        }), encoding="utf-8")
        timeline_path.write_text(json.dumps({
            "durationSeconds": 1.5,
            "estimatedFPS": 60,
            "frameCount": 90,
        }), encoding="utf-8")

        sessions = [{
            "sessionId": "sess_tracknet_001",
            "sessionName": "tracknet",
            "collector": "tester",
            "device": "iPhone17Max",
            "deviceProfile": "iphone17max",
            "createdAt": "2026-05-10T10:00:00.000Z",
            "status": "active",
        }]
        (export_dir / "sessions.jsonl").write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in sessions) + "\n",
            encoding="utf-8",
        )
        samples = [{
            "sampleId": "golf_ball_detection_auto_001",
            "domain": "golf_ball_detection",
            "sha256": "a" * 64,
            "hashAlgorithm": "sha256",
            "assetPath": asset_rel,
            "annotationPath": None,
            "fileSize": asset_path.stat().st_size,
            "sessionId": "sess_tracknet_001",
            "collector": "tester",
            "device": "iPhone17Max",
            "deviceProfile": "iphone17max",
            "capturedAt": "2026-05-10T10:00:00.000Z",
            "sourcePath": "ios://capture/sess_tracknet_001/shot_001",
            "shotId": "shot_001",
            "takeIndex": 1,
            "tags": ["needs_review"],
            "metadata": {
                "fps": 60,
                "actualFPS": 60,
                "resolution": "320x180",
                "durationSeconds": 1.5,
                "frameCount": 90,
                "qualityPassed": True,
                "sidecars": {
                    "labelCandidates": label_rel,
                    "timeline": timeline_rel,
                },
            },
            "status": "active",
        }]
        (export_dir / "samples.jsonl").write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in samples) + "\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(export_dir / "trackman.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("IMG_20260510_180000.jpg", self._make_jpeg())

        output_dir = workspace / "exports" / "tracknet_autolabel_priors"
        output = _run_in_workspace(workspace, "autolabel_tracknet_dataset.py", [
            "--export-dir", str(export_dir.relative_to(workspace)),
            "--output-dir", str(output_dir.relative_to(workspace)),
            "--threshold-seconds", "5",
            "--skip-ocr",
            "--max-shots", "1",
            "--score-threshold", "0.45",
            "--min-confirmed-run", "3",
        ])
        report = json.loads(output)
        assert report["summary"]["processedSamples"] == 1
        assert (output_dir / "alignment_summary.json").exists()

        observations_path = output_dir / "samples" / "sess_tracknet_001" / "shot_001" / "ball_observations.json"
        labels_path = output_dir / "samples" / "sess_tracknet_001" / "shot_001" / "tracknet_labels.csv"
        assert observations_path.exists()
        assert labels_path.exists()

        observations = json.loads(observations_path.read_text())
        assert observations["nonDestructive"] is True
        assert observations["summary"]["selectedTrackLength"] > 0
        assert any(frame["exclusionZones"] for frame in observations["frames"])

        label_lines = labels_path.read_text().splitlines()
        assert label_lines[0] == "frame_index,x,y,visible,confidence,label_source,needs_review"
        assert any("auto_motion_prior" in line for line in label_lines[1:])
        # 大目标矩形中心约在 y=87，不应成为主要球心轨迹；球应在更低/向上飞行区域。
        confirmed_y = [
            float(line.split(",")[2])
            for line in label_lines[1:]
            if "auto_motion_prior" in line
        ]
        assert confirmed_y
        assert max(confirmed_y) > 95
