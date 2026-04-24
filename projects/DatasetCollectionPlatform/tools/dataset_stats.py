from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from lib.registry import DUPLICATES_FILE, SAMPLES_FILE, SESSIONS_FILE, ROOT, read_jsonl


def gather_stats() -> dict:
    samples = [s for s in read_jsonl(SAMPLES_FILE) if s.get("status") == "active"]
    duplicates = read_jsonl(DUPLICATES_FILE)
    sessions = read_jsonl(SESSIONS_FILE)

    by_domain: dict[str, int] = Counter()
    by_club_type: dict[str, int] = Counter()
    by_handedness: dict[str, int] = Counter()
    by_swing_intensity: dict[str, int] = Counter()
    by_surface: dict[str, int] = Counter()
    by_session: dict[str, int] = Counter()
    dup_by_domain: dict[str, int] = Counter()

    for s in samples:
        domain = s.get("domain", "unknown")
        by_domain[domain] += 1
        by_session[s.get("sessionId", "unknown")] += 1
        meta = s.get("metadata", {})
        by_club_type[meta.get("clubType", "unknown")] += 1
        by_handedness[meta.get("handedness", "unknown")] += 1
        by_swing_intensity[meta.get("swingIntensity", "unknown")] += 1
        by_surface[meta.get("surface", "unknown")] += 1

    for d in duplicates:
        dup_by_domain[d.get("domain", "unknown")] += 1

    session_counts = list(by_session.values()) if by_session else [0]

    missing_assets = 0
    with_annotation = 0
    for s in samples:
        asset = ROOT / s["assetPath"]
        if not asset.exists():
            missing_assets += 1
        if s.get("annotationPath"):
            with_annotation += 1

    return {
        "summary": {
            "sessions": len(sessions),
            "activeSamples": len(samples),
            "duplicateEvents": len(duplicates),
            "missingAssets": missing_assets,
            "annotationCoverage": f"{with_annotation}/{len(samples)}",
        },
        "byDomain": dict(by_domain.most_common()),
        "duplicateByDomain": dict(dup_by_domain.most_common()),
        "byClubType": dict(by_club_type.most_common()),
        "byHandedness": dict(by_handedness.most_common()),
        "bySwingIntensity": dict(by_swing_intensity.most_common()),
        "bySurface": dict(by_surface.most_common()),
        "sessionDistribution": {
            "count": len(by_session),
            "min": min(session_counts),
            "max": max(session_counts),
            "avg": round(sum(session_counts) / len(session_counts), 1),
        },
    }


def print_table(stats: dict) -> None:
    s = stats["summary"]
    print(f"会话数: {s['sessions']}  |  活跃样本: {s['activeSamples']}  |  重复事件: {s['duplicateEvents']}")
    print(f"缺失资产: {s['missingAssets']}  |  标注覆盖: {s['annotationCoverage']}")
    print()

    _print_section("按域", stats["byDomain"])
    _print_section("重复(按域)", stats["duplicateByDomain"])
    _print_section("球杆类型", stats["byClubType"])
    _print_section("惯用手", stats["byHandedness"])
    _print_section("挥杆强度", stats["bySwingIntensity"])
    _print_section("场地", stats["bySurface"])

    sd = stats["sessionDistribution"]
    print(f"会话样本分布: {sd['count']} 个会话, min={sd['min']} max={sd['max']} avg={sd['avg']}")


def _print_section(title: str, data: dict) -> None:
    if not data:
        return
    items = "  ".join(f"{k}: {v}" for k, v in data.items())
    print(f"[{title}]  {items}")


def main() -> None:
    parser = argparse.ArgumentParser(description="数据集统计概览")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    stats = gather_stats()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print_table(stats)


if __name__ == "__main__":
    main()
