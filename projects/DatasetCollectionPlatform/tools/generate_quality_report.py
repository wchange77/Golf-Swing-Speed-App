from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lib.registry import (
    DUPLICATES_FILE,
    SAMPLES_FILE,
    SESSIONS_FILE,
    ROOT,
    read_jsonl,
)

REPORT_DIR = ROOT / "analysis" / "reports"


def build_report() -> dict:
    samples = read_jsonl(SAMPLES_FILE)
    duplicates = read_jsonl(DUPLICATES_FILE)
    sessions = read_jsonl(SESSIONS_FILE)

    active = [s for s in samples if s.get("status") == "active"]
    by_domain: dict[str, list[dict]] = {}
    for s in active:
        by_domain.setdefault(s["domain"], []).append(s)

    by_session: dict[str, int] = Counter()
    by_club_type: dict[str, int] = Counter()
    by_handedness: dict[str, int] = Counter()
    by_swing_intensity: dict[str, int] = Counter()
    by_surface: dict[str, int] = Counter()
    missing_assets = []
    with_annotation = 0

    for s in active:
        by_session[s.get("sessionId", "unknown")] += 1
        meta = s.get("metadata", {})
        by_club_type[meta.get("clubType", "unknown")] += 1
        by_handedness[meta.get("handedness", "unknown")] += 1
        by_swing_intensity[meta.get("swingIntensity", "unknown")] += 1
        by_surface[meta.get("surface", "unknown")] += 1
        asset = ROOT / s["assetPath"]
        if not asset.exists():
            missing_assets.append(s["sampleId"])
        if s.get("annotationPath"):
            with_annotation += 1

    session_counts = list(by_session.values()) if by_session else [0]

    domain_stats = {}
    for domain, domain_samples in by_domain.items():
        domain_stats[domain] = {
            "samples": len(domain_samples),
            "sessions": len({s["sessionId"] for s in domain_samples}),
        }

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "sessions": len(sessions),
            "activeSamples": len(active),
            "duplicateEvents": len(duplicates),
            "missingAssets": len(missing_assets),
            "missingAssetIds": missing_assets[:20],
            "annotationCoverage": f"{with_annotation}/{len(active)}",
            "annotationRate": round(with_annotation / len(active), 3) if active else 0,
        },
        "byDomain": domain_stats,
        "metadata": {
            "clubType": dict(by_club_type.most_common()),
            "handedness": dict(by_handedness.most_common()),
            "swingIntensity": dict(by_swing_intensity.most_common()),
            "surface": dict(by_surface.most_common()),
        },
        "sessionDistribution": {
            "count": len(by_session),
            "min": min(session_counts),
            "max": max(session_counts),
            "avg": round(sum(session_counts) / len(session_counts), 1),
        },
    }


def write_markdown(report: dict, path: Path) -> None:
    s = report["summary"]
    lines = [
        "# 数据集质量报告",
        "",
        f"生成时间: {report['generatedAt']}",
        "",
        "## 总览",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 会话数 | {s['sessions']} |",
        f"| 活跃样本 | {s['activeSamples']} |",
        f"| 重复事件 | {s['duplicateEvents']} |",
        f"| 缺失资产 | {s['missingAssets']} |",
        f"| 标注覆盖 | {s['annotationCoverage']} ({s['annotationRate']:.1%}) |",
        "",
        "## 按域统计",
        "",
    ]
    for domain, ds in report["byDomain"].items():
        lines.append(f"- **{domain}**: {ds['samples']} 样本, {ds['sessions']} 会话")
    lines.append("")

    lines.append("## Metadata 分布")
    lines.append("")
    for field, dist in report["metadata"].items():
        items = ", ".join(f"{k}: {v}" for k, v in dist.items())
        lines.append(f"- **{field}**: {items}")
    lines.append("")

    sd = report["sessionDistribution"]
    lines.append("## 会话样本分布")
    lines.append("")
    lines.append(f"- 会话数: {sd['count']}")
    lines.append(f"- 每会话样本: min={sd['min']}, max={sd['max']}, avg={sd['avg']}")
    lines.append("")

    if s["missingAssets"] > 0:
        lines.append("## 缺失资产")
        lines.append("")
        for sid in report["summary"]["missingAssetIds"]:
            lines.append(f"- {sid}")
        if s["missingAssets"] > 20:
            lines.append(f"- ... 及其他 {s['missingAssets'] - 20} 个")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成数据集质量报告")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    report = build_report()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "quality_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON report: {json_path}")

    if not args.json_only:
        md_path = REPORT_DIR / "quality_report.md"
        write_markdown(report, md_path)
        print(f"Markdown report: {md_path}")

    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
