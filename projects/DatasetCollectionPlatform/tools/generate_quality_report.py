from __future__ import annotations

import json
from pathlib import Path

from lib.registry import DUPLICATES_FILE, ROOT, SAMPLES_FILE, SESSIONS_FILE, read_jsonl


def main() -> None:
    samples = read_jsonl(SAMPLES_FILE)
    duplicates = read_jsonl(DUPLICATES_FILE)
    sessions = read_jsonl(SESSIONS_FILE)
    active_samples = [s for s in samples if s.get("status") == "active"]

    by_domain = {}
    by_domain_session = {}
    for row in active_samples:
        domain = row.get("domain", "unknown")
        by_domain.setdefault(domain, 0)
        by_domain[domain] += 1
        by_domain_session.setdefault(domain, set()).add(row.get("sessionId"))

    dup_by_domain = {}
    for row in duplicates:
        domain = row.get("domain", "unknown")
        dup_by_domain.setdefault(domain, 0)
        dup_by_domain[domain] += 1

    session_by_device = {}
    for row in sessions:
        device = row.get("device", "unknown")
        session_by_device.setdefault(device, 0)
        session_by_device[device] += 1

    duplicate_ratio = 0.0
    if active_samples or duplicates:
        duplicate_ratio = len(duplicates) / max(len(active_samples) + len(duplicates), 1)

    report = {
        "summary": {
            "activeSamples": len(active_samples),
            "duplicateEvents": len(duplicates),
            "sessions": len(sessions),
            "duplicateRatio": round(duplicate_ratio, 6),
        },
        "byDomain": by_domain,
        "duplicateByDomain": dup_by_domain,
        "sessionByDevice": session_by_device,
        "domainSessionCoverage": {k: len(v) for k, v in by_domain_session.items()},
    }

    out_json = ROOT / "analysis" / "reports" / "quality_report.json"
    out_md = ROOT / "analysis" / "reports" / "quality_report.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 数据质量报告",
        "",
        f"- 活跃样本数: {report['summary']['activeSamples']}",
        f"- 重复事件数: {report['summary']['duplicateEvents']}",
        f"- 采集会话数: {report['summary']['sessions']}",
        f"- 重复率: {report['summary']['duplicateRatio']}",
        "",
        "## 按域统计",
    ]
    for domain, count in sorted(by_domain.items()):
        lines.append(f"- {domain}: {count}")

    lines.append("")
    lines.append("## 按域重复统计")
    for domain, count in sorted(dup_by_domain.items()):
        lines.append(f"- {domain}: {count}")

    lines.append("")
    lines.append("## 设备覆盖")
    for device, count in sorted(session_by_device.items()):
        lines.append(f"- {device}: {count} 会话")

    lines.append("")
    lines.append("## 域会话覆盖")
    for domain, count in sorted(report["domainSessionCoverage"].items()):
        lines.append(f"- {domain}: {count} 个会话")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote reports: {out_json} and {out_md}")


if __name__ == "__main__":
    main()
