from __future__ import annotations

import json
import sys
from pathlib import Path

from lib.registry import load_yaml_file

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "AppleOSDatasetCollectorApp"
PROJECT_FILE = APP_ROOT / "project.yml"


def _validate_sources(target: dict, errors: list[str], warnings: list[str]) -> None:
    sources = target.get("sources", [])
    if not isinstance(sources, list) or not sources:
        errors.append("DatasetCollectorApp target missing sources.")
        return

    for idx, source in enumerate(sources, start=1):
        source_path = source.get("path") if isinstance(source, dict) else None
        if not source_path:
            errors.append(f"DatasetCollectorApp.sources[{idx}] missing path.")
            continue
        disk_path = APP_ROOT / source_path
        if not disk_path.exists():
            if source_path.endswith("/Resources"):
                warnings.append(
                    f"Optional resources path not found: {source_path} (xcodegen may still generate empty directory)."
                )
            else:
                errors.append(f"Missing source path on disk: {source_path}")


def _validate_project() -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not PROJECT_FILE.exists():
        return {
            "projectFile": str(PROJECT_FILE),
            "ok": False,
            "errors": [f"Missing project spec: {PROJECT_FILE}"],
            "warnings": [],
            "targets": {},
        }

    spec = load_yaml_file(PROJECT_FILE)
    if not isinstance(spec, dict):
        return {
            "projectFile": str(PROJECT_FILE),
            "ok": False,
            "errors": ["project.yml is not a valid YAML mapping."],
            "warnings": [],
            "targets": {},
        }

    if not spec.get("name"):
        errors.append("Missing top-level project name.")

    options = spec.get("options", {})
    deployment = options.get("deploymentTarget", {})
    ios_target = deployment.get("iOS")
    if not ios_target:
        errors.append("Missing options.deploymentTarget.iOS.")

    targets = spec.get("targets", {})
    if not isinstance(targets, dict):
        errors.append("targets must be a mapping.")
        targets = {}

    app_target = targets.get("DatasetCollectorApp")
    tests_target = targets.get("DatasetCollectorAppTests")
    if not app_target:
        errors.append("Missing target: DatasetCollectorApp.")
    if not tests_target:
        errors.append("Missing target: DatasetCollectorAppTests.")

    if isinstance(app_target, dict):
        if app_target.get("platform") != "iOS":
            errors.append("DatasetCollectorApp platform must be iOS.")
        if app_target.get("type") != "application":
            errors.append("DatasetCollectorApp type must be application.")
        _validate_sources(app_target, errors, warnings)

        info = app_target.get("info", {})
        info_path = info.get("path") if isinstance(info, dict) else None
        if not info_path:
            errors.append("DatasetCollectorApp.info.path is required.")
        elif not (APP_ROOT / info_path).exists():
            errors.append(f"Missing info plist: {info_path}")

        entitlements = app_target.get("entitlements", {})
        entitlements_path = entitlements.get("path") if isinstance(entitlements, dict) else None
        if not entitlements_path:
            errors.append("DatasetCollectorApp.entitlements.path is required.")
        elif not (APP_ROOT / entitlements_path).exists():
            errors.append(f"Missing entitlements file: {entitlements_path}")

    if isinstance(tests_target, dict):
        if tests_target.get("platform") != "iOS":
            errors.append("DatasetCollectorAppTests platform must be iOS.")
        if tests_target.get("type") != "bundle.unit-test":
            errors.append("DatasetCollectorAppTests type must be bundle.unit-test.")
        test_sources = tests_target.get("sources", [])
        if not isinstance(test_sources, list) or not test_sources:
            errors.append("DatasetCollectorAppTests target missing sources.")
        else:
            for idx, source in enumerate(test_sources, start=1):
                source_path = source.get("path") if isinstance(source, dict) else None
                if not source_path:
                    errors.append(f"DatasetCollectorAppTests.sources[{idx}] missing path.")
                    continue
                if not (APP_ROOT / source_path).exists():
                    errors.append(f"Missing test source path on disk: {source_path}")

    swift_sources = list((APP_ROOT / "DatasetCollectorApp" / "Sources").rglob("*.swift"))
    if not swift_sources:
        errors.append("No Swift source files found under DatasetCollectorApp/Sources.")

    swift_tests = list((APP_ROOT / "DatasetCollectorApp" / "Tests" / "Unit").rglob("*.swift"))
    if not swift_tests:
        errors.append("No Swift test files found under DatasetCollectorApp/Tests/Unit.")

    return {
        "projectFile": str(PROJECT_FILE),
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "targets": {
            "DatasetCollectorApp": bool(app_target),
            "DatasetCollectorAppTests": bool(tests_target),
        },
        "counts": {
            "swiftSources": len(swift_sources),
            "swiftTests": len(swift_tests),
        },
        "deploymentTargetiOS": ios_target,
    }


def main() -> None:
    result = _validate_project()
    print(json.dumps(result, ensure_ascii=False))
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
