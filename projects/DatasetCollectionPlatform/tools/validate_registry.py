from __future__ import annotations

import argparse
import json
import sys

from lib.registry import (
    SAMPLE_SCHEMA_FILE,
    SAMPLES_FILE,
    SESSION_SCHEMA_FILE,
    SESSIONS_FILE,
    ROOT,
    ensure_registry_files,
    read_jsonl,
    validate_with_schema,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate registry records against schemas and file links")
    parser.add_argument("--strict", action="store_true", help="Treat missing annotation files as error")
    args = parser.parse_args()

    ensure_registry_files()
    sessions = read_jsonl(SESSIONS_FILE)
    samples = read_jsonl(SAMPLES_FILE)

    errors: list[str] = []

    session_ids = set()
    for idx, row in enumerate(sessions, start=1):
        try:
            validate_with_schema(row, SESSION_SCHEMA_FILE)
        except Exception as exc:
            errors.append(f"sessions[{idx}] schema error: {exc}")
        sid = row.get("sessionId")
        if sid in session_ids:
            errors.append(f"sessions[{idx}] duplicate sessionId: {sid}")
        if sid:
            session_ids.add(sid)

    for idx, row in enumerate(samples, start=1):
        try:
            validate_with_schema(row, SAMPLE_SCHEMA_FILE)
        except Exception as exc:
            errors.append(f"samples[{idx}] schema error: {exc}")
            continue

        sid = row.get("sessionId")
        if sid not in session_ids:
            errors.append(f"samples[{idx}] unknown sessionId: {sid}")

        asset_path = ROOT / row["assetPath"]
        if not asset_path.exists():
            errors.append(f"samples[{idx}] missing asset: {asset_path}")

        annotation_path = row.get("annotationPath")
        if annotation_path:
            ann = ROOT / annotation_path
            if not ann.exists() and args.strict:
                errors.append(f"samples[{idx}] missing annotation: {ann}")

    summary = {
        "sessions": len(sessions),
        "samples": len(samples),
        "errors": len(errors),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if errors:
        for err in errors:
            print(f"ERROR: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
