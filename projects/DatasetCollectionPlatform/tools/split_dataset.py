from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

from lib.registry import ROOT, SAMPLES_FILE, read_jsonl, validate_domain


def clear_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def split_items(items, train_ratio=0.8, val_ratio=0.1, seed=42):
    rng = random.Random(seed)
    rng.shuffle(items)
    train_end = int(len(items) * train_ratio)
    val_end = train_end + int(len(items) * val_ratio)
    return items[:train_end], items[train_end:val_end], items[val_end:]


def split_by_session(items, train_ratio=0.8, val_ratio=0.1, seed=42):
    rng = random.Random(seed)
    groups = {}
    for item in items:
        groups.setdefault(item.get("sessionId", "unknown"), []).append(item)

    session_ids = list(groups.keys())
    rng.shuffle(session_ids)

    total = len(items)
    target_train = int(total * train_ratio)
    target_val = int(total * val_ratio)

    train, val, test = [], [], []
    train_count = 0
    val_count = 0

    for sid in session_ids:
        batch = groups[sid]
        if train_count < target_train:
            train.extend(batch)
            train_count += len(batch)
            continue
        if val_count < target_val:
            val.extend(batch)
            val_count += len(batch)
            continue
        test.extend(batch)

    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    return train, val, test


def copy_record_to_split(record, split_root: Path):
    domain = record["domain"]
    asset_src = ROOT / record["assetPath"]
    ann_src = ROOT / record["annotationPath"] if record.get("annotationPath") else None

    img_dst = split_root / domain / "images" / asset_src.name
    img_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(asset_src, img_dst)

    if ann_src and ann_src.exists():
        ann_dst = split_root / domain / "labels" / ann_src.name
        ann_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ann_src, ann_dst)


def main():
    parser = argparse.ArgumentParser(description="Split unique active samples into train/val/test")
    parser.add_argument("--domain", required=True, choices=["human_club", "golf_ball_detection"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train", type=float, default=0.8)
    parser.add_argument("--val", type=float, default=0.1)
    parser.add_argument("--test", type=float, default=0.1)
    parser.add_argument("--strategy", default="session", choices=["sample", "session"])
    args = parser.parse_args()

    domain = validate_domain(args.domain)
    if round(args.train + args.val + args.test, 6) != 1.0:
        raise ValueError("train + val + test must equal 1.0")

    records = [
        r for r in read_jsonl(SAMPLES_FILE)
        if r.get("domain") == domain and r.get("status") == "active"
    ]

    processed_domain = ROOT / "datasets" / "processed" / domain
    clear_dir(processed_domain)

    if args.strategy == "sample":
        train, val, test = split_items(records, train_ratio=args.train, val_ratio=args.val, seed=args.seed)
    else:
        train, val, test = split_by_session(records, train_ratio=args.train, val_ratio=args.val, seed=args.seed)

    for r in train:
        copy_record_to_split(r, processed_domain / "train")
    for r in val:
        copy_record_to_split(r, processed_domain / "val")
    for r in test:
        copy_record_to_split(r, processed_domain / "test")

    split_meta = {
        "domain": domain,
        "strategy": args.strategy,
        "seed": args.seed,
        "ratios": {"train": args.train, "val": args.val, "test": args.test},
        "counts": {"train": len(train), "val": len(val), "test": len(test)},
        "sessionCounts": {
            "train": len({r["sessionId"] for r in train}),
            "val": len({r["sessionId"] for r in val}),
            "test": len({r["sessionId"] for r in test}),
        },
        "sampleIds": {
            "train": [r["sampleId"] for r in train],
            "val": [r["sampleId"] for r in val],
            "test": [r["sampleId"] for r in test],
        },
    }

    split_file = ROOT / "exports" / "splits" / f"{domain}.json"
    split_file.parent.mkdir(parents=True, exist_ok=True)
    split_file.write_text(json.dumps(split_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(split_meta["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
