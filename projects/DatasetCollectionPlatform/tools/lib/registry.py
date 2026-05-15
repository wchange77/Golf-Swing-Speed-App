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
ANNOTATIONS_FILE = REGISTRY_DIR / "annotations.jsonl"
CONTRACTS_DIR = ROOT / "contracts"
SAMPLE_SCHEMA_FILE = CONTRACTS_DIR / "sample_record.schema.json"
SESSION_SCHEMA_FILE = CONTRACTS_DIR / "session_record.schema.json"
MANIFEST_SCHEMA_FILE = CONTRACTS_DIR / "dataset_manifest.schema.json"

ALLOWED_DOMAINS = {"human_club", "golf_ball_detection"}


def ensure_registry_files() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    for p in (SAMPLES_FILE, DUPLICATES_FILE, SESSIONS_FILE, ANNOTATIONS_FILE):
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


def register_one_sample(
    *,
    domain: str,
    source_file: Path,
    annotation_file: Path | None = None,
    session_id: str,
    collector: str = "unknown",
    shot_id: str = "",
    take_index: int = 1,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    source_path: str = "",
    captured_at: str = "",
) -> str | None:
    domain = validate_domain(domain)
    source_file = source_file.resolve()
    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError(f"Sample file not found: {source_file}")
    if take_index < 1:
        raise ValueError("take_index must be >= 1")
    if annotation_file is not None:
        annotation_file = annotation_file.resolve()
        if not annotation_file.exists():
            raise FileNotFoundError(f"Annotation file not found: {annotation_file}")

    ensure_registry_files()
    session = ensure_session_exists(session_id)
    target_domains = session.get("targetDomains", [])
    if target_domains and domain not in target_domains:
        raise ValueError(f"domain {domain} not declared in session targetDomains={target_domains}")

    meta = metadata or {}
    captured = captured_at or utc_now_iso()
    src_path = source_path or str(source_file)
    tag_list = tags or []

    checksum = sha256_of_file(source_file)
    existing = [
        r for r in read_jsonl(SAMPLES_FILE)
        if r.get("domain") == domain and r.get("sha256") == checksum and r.get("status") == "active"
    ]
    if existing:
        duplicate_record = {
            "duplicateAt": utc_now_iso(),
            "domain": domain,
            "sha256": checksum,
            "incomingFile": str(source_file),
            "incomingSourcePath": src_path,
            "existingSampleId": existing[0]["sampleId"],
            "sessionId": session_id,
            "collector": collector,
            "metadata": meta,
        }
        append_jsonl(DUPLICATES_FILE, duplicate_record)
        return None

    sample_id = make_sample_id(domain, checksum)
    asset_path = canonical_asset_path(domain, source_file, checksum)
    ann_path = canonical_annotation_path(domain, checksum, annotation_file)

    copy_if_needed(source_file, asset_path)
    if annotation_file and ann_path:
        copy_if_needed(annotation_file, ann_path)

    record = {
        "sampleId": sample_id,
        "domain": domain,
        "sha256": checksum,
        "hashAlgorithm": "sha256",
        "assetPath": relative_to_root(asset_path),
        "annotationPath": relative_to_root(ann_path) if ann_path else None,
        "fileSize": source_file.stat().st_size,
        "sessionId": session_id,
        "collector": collector,
        "device": session.get("device", "unknown"),
        "deviceProfile": session.get("deviceProfile", "unknown"),
        "capturedAt": captured,
        "sourcePath": src_path,
        "shotId": shot_id or None,
        "takeIndex": take_index,
        "tags": tag_list,
        "metadata": meta,
        "status": "active",
    }
    validate_with_schema(record, SAMPLE_SCHEMA_FILE)
    append_jsonl(SAMPLES_FILE, record)
    return sample_id


ANNOTATION_KINDS = ("yolo_bbox", "coco_keypoints", "frame_index")


def list_samples(
    domain: str | None = None,
    *,
    status: str | None = "active",
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    ensure_registry_files()
    rows = read_jsonl(SAMPLES_FILE)
    if domain is not None:
        rows = [r for r in rows if r.get("domain") == domain]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if session_id is not None:
        rows = [r for r in rows if r.get("sessionId") == session_id]
    return rows


def annotation_dir_for(sample_id: str, kind: str) -> Path:
    if kind not in ANNOTATION_KINDS:
        raise ValueError(f"annotation kind must be one of {ANNOTATION_KINDS}")
    return ROOT / "datasets" / "annotations" / kind / sample_id


def annotation_path_for(sample_id: str, kind: str, *, filename: str | None = None) -> Path:
    base = annotation_dir_for(sample_id, kind)
    return base / filename if filename else base


def upsert_annotation_record(record: dict[str, Any]) -> None:
    ensure_registry_files()
    required = {"sampleId", "sha256", "domain", "kind", "framesTotal", "framesLabeled", "updatedAt"}
    missing = required - record.keys()
    if missing:
        raise ValueError(f"annotation record missing fields: {sorted(missing)}")
    if record["kind"] not in ANNOTATION_KINDS:
        raise ValueError(f"annotation kind must be one of {ANNOTATION_KINDS}")

    rows = read_jsonl(ANNOTATIONS_FILE)
    key = (record["sampleId"], record["kind"])
    replaced = False
    for idx, row in enumerate(rows):
        if (row.get("sampleId"), row.get("kind")) == key:
            rows[idx] = record
            replaced = True
            break
    if not replaced:
        rows.append(record)

    tmp = ANNOTATIONS_FILE.with_suffix(ANNOTATIONS_FILE.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(ANNOTATIONS_FILE)


def read_annotation_records(
    *, sample_id: str | None = None, domain: str | None = None, kind: str | None = None
) -> list[dict[str, Any]]:
    ensure_registry_files()
    rows = read_jsonl(ANNOTATIONS_FILE)
    if sample_id is not None:
        rows = [r for r in rows if r.get("sampleId") == sample_id]
    if domain is not None:
        rows = [r for r in rows if r.get("domain") == domain]
    if kind is not None:
        rows = [r for r in rows if r.get("kind") == kind]
    return rows


def annotation_coverage(sample_id: str) -> float:
    records = read_annotation_records(sample_id=sample_id)
    if not records:
        return 0.0
    total = max((r.get("framesTotal") or 0) for r in records)
    labeled = max((r.get("framesLabeled") or 0) for r in records)
    if total <= 0:
        return 0.0
    return min(labeled / total, 1.0)
