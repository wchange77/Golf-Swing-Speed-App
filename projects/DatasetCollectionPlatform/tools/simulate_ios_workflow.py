from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def write_demo_inputs(workspace: Path) -> dict[str, Path]:
    inputs = workspace / "sim_input"
    inputs.mkdir(parents=True, exist_ok=True)
    ann = workspace / "sim_ann"
    ann.mkdir(parents=True, exist_ok=True)

    human_a = inputs / "human_a.jpg"
    human_dup = inputs / "human_dup.jpg"
    ball_a = inputs / "ball_a.jpg"

    payload_h = b"ios-mock-human-sample-seed"
    payload_b = b"ios-mock-ball-sample-seed"

    human_a.write_bytes(payload_h)
    human_dup.write_bytes(payload_h)  # exact duplicate
    ball_a.write_bytes(payload_b)

    (ann / "human_a.json").write_text('{"label":"club_head"}', encoding="utf-8")
    (ann / "human_dup.json").write_text('{"label":"club_head"}', encoding="utf-8")
    (ann / "ball_a.txt").write_text("0 0.5 0.5 0.1 0.1", encoding="utf-8")

    return {
        "human_a": human_a,
        "human_dup": human_dup,
        "ball_a": ball_a,
        "ann_human_a": ann / "human_a.json",
        "ann_human_dup": ann / "human_dup.json",
        "ann_ball_a": ann / "ball_a.txt",
    }


def write_report(summary: dict, output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Windows 端 iOS 采集流程模拟报告",
        "",
        f"- 会话 ID: `{summary['sessionId']}`",
        f"- human_club 样本数: {summary['humanSamples']}",
        f"- golf_ball_detection 样本数: {summary['ballSamples']}",
        f"- 重复样本事件: {summary['duplicateEvents']}",
        f"- 校验错误数: {summary['validationErrors']}",
        f"- 总样本数（manifest）: {summary['manifestUniqueSamples']}",
        "",
        "## 命令状态",
        f"- `start_session`: {summary['steps']['start_session']}",
        f"- `register_samples`: {summary['steps']['register_samples']}",
        f"- `split_dataset`: {summary['steps']['split_dataset']}",
        f"- `generate_manifest`: {summary['steps']['generate_manifest']}",
        f"- `validate_registry`: {summary['steps']['validate_registry']}",
        "",
        "## 说明",
        "- 该模拟在 Windows 上执行，不依赖 Xcode。",
        "- 目标是验证 Apple 采集端输出字段与 Dataset 平台契约兼容。",
    ]
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate iOS collector workflow on Windows")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()

    tmp_base = Path(tempfile.mkdtemp(prefix="ios-workflow-sim-"))
    workspace = tmp_base / "DatasetCollectionPlatform"
    shutil.copytree(ROOT, workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    steps = {
        "start_session": "pending",
        "register_samples": "pending",
        "split_dataset": "pending",
        "generate_manifest": "pending",
        "validate_registry": "pending",
    }

    try:
        sample_paths = write_demo_inputs(workspace)

        session_id = run(
            [
                sys.executable,
                "tools/start_session.py",
                "--collector",
                "windows_sim",
                "--device",
                "iPhone17Max",
                "--device-profile",
                "iphone17max",
                "--target-domains",
                "human_club,golf_ball_detection",
                "--scene-type",
                "indoor",
                "--lighting",
                "indoor_led",
                "--tripod",
            ],
            workspace,
        ).splitlines()[-1]
        steps["start_session"] = "ok"

        register_cmds = [
            [
                sys.executable,
                "tools/register_sample.py",
                "--domain",
                "human_club",
                "--file",
                str(sample_paths["human_a"]),
                "--annotation",
                str(sample_paths["ann_human_a"]),
                "--session-id",
                session_id,
                "--collector",
                "windows_sim",
                "--shot-id",
                "human_001",
            ],
            [
                sys.executable,
                "tools/register_sample.py",
                "--domain",
                "human_club",
                "--file",
                str(sample_paths["human_dup"]),
                "--annotation",
                str(sample_paths["ann_human_dup"]),
                "--session-id",
                session_id,
                "--collector",
                "windows_sim",
                "--shot-id",
                "human_002",
            ],
            [
                sys.executable,
                "tools/register_sample.py",
                "--domain",
                "golf_ball_detection",
                "--file",
                str(sample_paths["ball_a"]),
                "--annotation",
                str(sample_paths["ann_ball_a"]),
                "--session-id",
                session_id,
                "--collector",
                "windows_sim",
                "--shot-id",
                "ball_001",
            ],
        ]
        for cmd in register_cmds:
            run(cmd, workspace)
        steps["register_samples"] = "ok"

        run(
            [sys.executable, "tools/split_dataset.py", "--domain", "human_club", "--strategy", "session", "--seed", "42"],
            workspace,
        )
        run(
            [sys.executable, "tools/split_dataset.py", "--domain", "golf_ball_detection", "--strategy", "session", "--seed", "42"],
            workspace,
        )
        steps["split_dataset"] = "ok"

        run([sys.executable, "tools/generate_manifest.py"], workspace)
        run([sys.executable, "tools/generate_quality_report.py"], workspace)
        steps["generate_manifest"] = "ok"

        validation_json = run([sys.executable, "tools/validate_registry.py"], workspace).splitlines()[0]
        steps["validate_registry"] = "ok"

        manifest = json.loads((workspace / "exports/dataset_manifest.json").read_text(encoding="utf-8"))
        quality = json.loads((workspace / "analysis/reports/quality_report.json").read_text(encoding="utf-8"))
        validation = json.loads(validation_json)

        human_samples = 0
        ball_samples = 0
        for ds in manifest["datasets"]:
            if ds["key"] == "human_club":
                human_samples = ds["samples"]
            if ds["key"] == "golf_ball_detection":
                ball_samples = ds["samples"]

        summary = {
            "sessionId": session_id,
            "humanSamples": human_samples,
            "ballSamples": ball_samples,
            "duplicateEvents": quality["summary"]["duplicateEvents"],
            "validationErrors": validation["errors"],
            "manifestUniqueSamples": manifest["registry"]["uniqueSamples"],
            "steps": steps,
        }

        report_json = ROOT / "analysis/reports/windows_ios_simulation_report.json"
        report_md = ROOT / "analysis/reports/windows_ios_simulation_report.md"
        write_report(summary, report_json, report_md)
        print(json.dumps(summary, ensure_ascii=False))

    finally:
        if not args.keep_workspace:
            shutil.rmtree(tmp_base, ignore_errors=True)
        else:
            print(f"KEPT_WORKSPACE={tmp_base}")


if __name__ == "__main__":
    main()
