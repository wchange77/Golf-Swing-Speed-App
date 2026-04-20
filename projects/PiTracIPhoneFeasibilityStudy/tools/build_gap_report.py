from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "module_mapping.json"
OUT = ROOT / "artifacts" / "gap_report.md"


def main() -> None:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    modules = data["modules"]

    lines = [
        "# PiTrac -> iPhone 复现差距报告",
        "",
        f"- 目标设备: {data['targetDevice']}",
        f"- 来源仓库: {data['sourceRepo']}",
        "",
        "| 模块 | 可行性 | 风险 | iOS 目标实现 |",
        "|---|---|---|---|",
    ]

    for m in modules:
        lines.append(f"| {m['name']} | {m['feasibility']} | {m['risk']} | {m['ios_target']} |")

    lines.append("")
    lines.append("## 高风险项")
    for m in modules:
        if m.get("risk") == "high":
            lines.append(f"- {m['name']}: 需替代方案，不可 1:1 复现")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
