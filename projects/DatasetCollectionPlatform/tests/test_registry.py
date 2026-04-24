from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib import registry


@pytest.fixture()
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "REGISTRY_DIR", tmp_path / "datasets" / "registry")
    monkeypatch.setattr(registry, "SAMPLES_FILE", tmp_path / "datasets" / "registry" / "samples.jsonl")
    monkeypatch.setattr(registry, "DUPLICATES_FILE", tmp_path / "datasets" / "registry" / "duplicates.jsonl")
    monkeypatch.setattr(registry, "SESSIONS_FILE", tmp_path / "datasets" / "registry" / "sessions.jsonl")
    monkeypatch.setattr(registry, "CONTRACTS_DIR", PLATFORM_ROOT / "contracts")
    monkeypatch.setattr(registry, "SAMPLE_SCHEMA_FILE", PLATFORM_ROOT / "contracts" / "sample_record.schema.json")
    monkeypatch.setattr(registry, "SESSION_SCHEMA_FILE", PLATFORM_ROOT / "contracts" / "session_record.schema.json")
    monkeypatch.setattr(registry, "MANIFEST_SCHEMA_FILE", PLATFORM_ROOT / "contracts" / "dataset_manifest.schema.json")
    registry.ensure_registry_files()
    return tmp_path


def _create_session(domain_list=None):
    domains = domain_list or ["human_club", "golf_ball_detection"]
    session_id = registry.make_session_id()
    record = {
        "sessionId": session_id,
        "collector": "tester",
        "device": "TestDevice",
        "deviceProfile": "test_profile",
        "createdAt": registry.utc_now_iso(),
        "status": "active",
        "iosVersion": "",
        "appVersion": "",
        "captureConfig": {"fps": 240, "resolution": "1920x1080"},
        "environment": {"sceneType": "indoor", "lighting": "indoor_led", "tripod": True},
        "targetDomains": domains,
        "profileSnapshot": {},
        "notes": "",
    }
    registry.validate_with_schema(record, registry.SESSION_SCHEMA_FILE)
    registry.append_jsonl(registry.SESSIONS_FILE, record)
    return session_id


def _make_sample_file(tmp_path, content=b"test-sample-data"):
    f = tmp_path / "sample.jpg"
    f.write_bytes(content)
    return f


class TestSha256:
    def test_correct_hash(self, tmp_path):
        f = tmp_path / "data.bin"
        payload = b"hello world"
        f.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()
        assert registry.sha256_of_file(f) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert registry.sha256_of_file(f) == expected


class TestIdGeneration:
    def test_session_id_format(self):
        sid = registry.make_session_id()
        assert sid.startswith("sess_")
        assert len(sid) == 17

    def test_sample_id_format(self):
        sample_id = registry.make_sample_id("human_club", "a" * 64)
        assert sample_id == "human_club_aaaaaaaaaaaa"


class TestJsonl:
    def test_roundtrip(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.touch()
        registry.append_jsonl(f, {"key": "value1"})
        registry.append_jsonl(f, {"key": "value2"})
        rows = registry.read_jsonl(f)
        assert len(rows) == 2
        assert rows[0]["key"] == "value1"
        assert rows[1]["key"] == "value2"

    def test_read_empty(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.touch()
        assert registry.read_jsonl(f) == []

    def test_read_nonexistent(self, tmp_path):
        f = tmp_path / "missing.jsonl"
        assert registry.read_jsonl(f) == []


class TestValidateWithSchema:
    def test_valid_session(self, tmp_root):
        session_id = registry.make_session_id()
        record = {
            "sessionId": session_id,
            "collector": "alice",
            "device": "iPhone17Max",
            "deviceProfile": "iphone17max",
            "createdAt": registry.utc_now_iso(),
            "status": "active",
            "captureConfig": {"fps": 240, "resolution": "1920x1080"},
            "environment": {"sceneType": "indoor", "lighting": "led", "tripod": True},
            "targetDomains": ["human_club"],
        }
        registry.validate_with_schema(record, registry.SESSION_SCHEMA_FILE)

    def test_invalid_session_missing_field(self, tmp_root):
        record = {"sessionId": "sess_abc123def456", "collector": "alice"}
        with pytest.raises(ValueError, match="Schema validation failed"):
            registry.validate_with_schema(record, registry.SESSION_SCHEMA_FILE)


class TestRegisterOneSample:
    def test_register_new_sample(self, tmp_root):
        session_id = _create_session()
        sample_file = _make_sample_file(tmp_root, b"unique-content-1")
        result = registry.register_one_sample(
            domain="human_club",
            source_file=sample_file,
            session_id=session_id,
            metadata={"fps": 240, "resolution": "1920x1080", "clubType": "driver",
                       "handedness": "right", "swingIntensity": "normal", "surface": "unknown"},
        )
        assert result is not None
        assert result.startswith("human_club_")
        samples = registry.read_jsonl(registry.SAMPLES_FILE)
        assert len(samples) == 1
        assert samples[0]["sampleId"] == result

    def test_duplicate_detection(self, tmp_root):
        session_id = _create_session()
        content = b"duplicate-content"
        f1 = tmp_root / "file1.jpg"
        f1.write_bytes(content)
        f2 = tmp_root / "file2.jpg"
        f2.write_bytes(content)

        meta = {"fps": 240, "resolution": "1920x1080", "clubType": "driver",
                "handedness": "right", "swingIntensity": "normal", "surface": "unknown"}
        r1 = registry.register_one_sample(domain="human_club", source_file=f1, session_id=session_id, metadata=meta)
        r2 = registry.register_one_sample(domain="human_club", source_file=f2, session_id=session_id, metadata=meta)

        assert r1 is not None
        assert r2 is None
        assert len(registry.read_jsonl(registry.SAMPLES_FILE)) == 1
        assert len(registry.read_jsonl(registry.DUPLICATES_FILE)) == 1

    def test_wrong_domain_rejected(self, tmp_root):
        session_id = _create_session(domain_list=["human_club"])
        sample_file = _make_sample_file(tmp_root)
        with pytest.raises(ValueError, match="not declared in session"):
            registry.register_one_sample(
                domain="golf_ball_detection",
                source_file=sample_file,
                session_id=session_id,
                metadata={"fps": 240, "resolution": "1920x1080", "clubType": "unknown",
                           "handedness": "unknown", "swingIntensity": "unknown", "surface": "unknown"},
            )

    def test_missing_session_rejected(self, tmp_root):
        sample_file = _make_sample_file(tmp_root)
        with pytest.raises(ValueError, match="sessionId not found"):
            registry.register_one_sample(
                domain="human_club",
                source_file=sample_file,
                session_id="sess_nonexistent0",
                metadata={"fps": 240, "resolution": "1920x1080", "clubType": "unknown",
                           "handedness": "unknown", "swingIntensity": "unknown", "surface": "unknown"},
            )

    def test_with_annotation(self, tmp_root):
        session_id = _create_session()
        sample_file = _make_sample_file(tmp_root, b"annotated-sample")
        ann_file = tmp_root / "ann.json"
        ann_file.write_text('{"label": "test"}', encoding="utf-8")

        result = registry.register_one_sample(
            domain="human_club",
            source_file=sample_file,
            annotation_file=ann_file,
            session_id=session_id,
            metadata={"fps": 240, "resolution": "1920x1080", "clubType": "driver",
                       "handedness": "right", "swingIntensity": "normal", "surface": "unknown"},
        )
        assert result is not None
        samples = registry.read_jsonl(registry.SAMPLES_FILE)
        assert samples[0]["annotationPath"] is not None

    def test_asset_copied_to_canonical_path(self, tmp_root):
        session_id = _create_session()
        content = b"asset-copy-test"
        sample_file = _make_sample_file(tmp_root, content)

        result = registry.register_one_sample(
            domain="human_club",
            source_file=sample_file,
            session_id=session_id,
            metadata={"fps": 240, "resolution": "1920x1080", "clubType": "driver",
                       "handedness": "right", "swingIntensity": "normal", "surface": "unknown"},
        )
        samples = registry.read_jsonl(registry.SAMPLES_FILE)
        asset_path = tmp_root / samples[0]["assetPath"]
        assert asset_path.exists()
        assert asset_path.read_bytes() == content
