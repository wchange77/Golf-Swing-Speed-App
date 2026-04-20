from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = ROOT / "datasets" / "registry"
SAMPLES_FILE = REGISTRY_DIR / "samples.jsonl"
DUPLICATES_FILE = REGISTRY_DIR / "duplicates.jsonl"
SESSIONS_FILE = REGISTRY_DIR / "sessions.jsonl"
CONTRACTS_DIR = ROOT / "contracts"
SAMPLE_SCHEMA_FILE = CONTRACTS_DIR / "sample_record.schema.json"
SESSION_SCHEMA_FILE = CONTRACTS_DIR / "session_record.schema.json"
MANIFEST_SCHEMA_FILE = CONTRACTS_DIR / "dataset_manifest.schema.json"

ALLOWED_DOMAINS = {"human_club", "golf_ball_detection"}


def ensure_registry_files() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    for p in (SAMPLES_FILE, DUPLICATES_FILE, SESSIONS_FILE):
        if not p.exists():
            p.touch()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_asset_path(domain: str, source_file: Path, sha256: str) -> Path:
    ext = source_file.suffix.lower() or ".bin"
    return ROOT / "datasets" / "raw" / domain / "assets" / sha256[:2] / f"{sha256}{ext}"


def canonical_annotation_path(domain: str, sha256: str, annotation_file: Path | None) -> Path | None:
    if annotation_file is None:
        return None
    ext = annotation_file.suffix.lower() or ".json"
    return ROOT / "datasets" / "raw" / domain / "annotations" / sha256[:2] / f"{sha256}{ext}"


def copy_if_needed(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)


def make_session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:12]}"


def make_sample_id(domain: str, sha256: str) -> str:
    return f"{domain}_{sha256[:12]}"


def validate_domain(domain: str) -> str:
    if domain not in ALLOWED_DOMAINS:
        raise ValueError(f"Unsupported domain: {domain}. Allowed: {sorted(ALLOWED_DOMAINS)}")
    return domain


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml_file(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def relative_to_root(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def find_session(session_id: str) -> dict[str, Any] | None:
    for row in read_jsonl(SESSIONS_FILE):
        if row.get("sessionId") == session_id:
            return row
    return None


def ensure_session_exists(session_id: str) -> dict[str, Any]:
    session = find_session(session_id)
    if not session:
        raise ValueError(f"sessionId not found: {session_id}")
    return session


def validate_with_schema(record: dict[str, Any], schema_file: Path) -> None:
    schema = load_json_file(schema_file)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(record), key=lambda e: e.path)
    if not errors:
        return
    head = errors[0]
    path = ".".join(str(p) for p in head.path) if head.path else "<root>"
    raise ValueError(f"Schema validation failed at {path}: {head.message}")
