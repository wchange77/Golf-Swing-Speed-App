"""
外部高尔夫数据集下载脚本
运行前：pip install roboflow gdown requests tqdm
"""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent / "datasets" / "external"

def run(cmd: list[str]) -> bool:
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0

# ─────────────────────────────────────────────
# 1. Roboflow Universe — Golf Ball Detection
#    需要免费注册获取 API key: https://app.roboflow.com
# ─────────────────────────────────────────────
def download_roboflow(api_key: str):
    try:
        from roboflow import Roboflow
    except ImportError:
        print("请先运行: pip install roboflow")
        return

    out = BASE / "roboflow_golf_ball"
    out.mkdir(exist_ok=True)
    os.chdir(out)

    rf = Roboflow(api_key=api_key)
    # 数据集1：golf-ball-detection（最多图片）
    project = rf.workspace("golf-ball-detection-ljdwx").project("golf-ball-detection-ljdwx")
    project.version(1).download("yolov8", location=str(out / "dataset1"))

    # 数据集2：golf-ball（多场景）
    project2 = rf.workspace("golf-4xtjb").project("golf-ball-yjkzm")
    project2.version(3).download("yolov8", location=str(out / "dataset2"))

    print(f"✓ Roboflow 数据集已下载到 {out}")


# ─────────────────────────────────────────────
# 2. GolfDB — 1400 段挥杆视频（含 impact 帧标注）
#    Google Drive，需要 gdown
# ─────────────────────────────────────────────
def download_golfdb():
    try:
        import gdown
    except ImportError:
        print("请先运行: pip install gdown")
        return

    out = BASE / "golfdb"
    out.mkdir(exist_ok=True)

    # 标注 CSV（轻量，直接下载）
    # 来源：https://github.com/wmcnally/golfdb
    annotations_id = "1watUPSHCMR1UWkBMGFBFMFMFMFMFMFMF"  # 需替换为实际 ID
    print("GolfDB 视频需从 GitHub README 获取 Google Drive 链接后手动下载")
    print("  → https://github.com/wmcnally/golfdb")
    print(f"  → 下载后放入: {out}/")

    # 克隆代码（含标注文件，不含视频）
    code_dir = out / "code"
    if not code_dir.exists():
        run(["git", "clone", "--depth=1",
             "https://github.com/wmcnally/golfdb.git", str(code_dir)])
        print(f"✓ GolfDB 代码/标注已克隆到 {code_dir}")


# ─────────────────────────────────────────────
# 3. TrackNet — 高速小目标追踪（羽毛球/网球）
#    用于参考热力图检测架构
# ─────────────────────────────────────────────
def download_tracknet():
    out = BASE / "tracknet"
    code_dir = out / "code"
    if not code_dir.exists():
        run(["git", "clone", "--depth=1",
             "https://github.com/weekenddeeplearning/TrackNet.git", str(code_dir)])
        print(f"✓ TrackNet 代码已克隆到 {code_dir}")
    else:
        print(f"TrackNet 已存在: {code_dir}")

    # 数据集需从论文作者处申请，打印说明
    print("TrackNet 数据集申请地址：")
    print("  → https://nol.cs.nctu.edu.tw:234/open-source/TrackNet")


# ─────────────────────────────────────────────
# 4. CaddieSet — CVPR 2025，含球速/发射角真值
#    需联系作者申请
# ─────────────────────────────────────────────
def download_caddieSet():
    out = BASE / "caddieSet"
    out.mkdir(exist_ok=True)
    print("CaddieSet 数据集（CVPR 2025）需联系作者申请：")
    print("  → 论文: https://arxiv.org/abs/2508.20491")
    print("  → CVPR: https://openaccess.thecvf.com/content/CVPR2025W/CVSPORTS/")
    print(f"  → 下载后放入: {out}/")


# ─────────────────────────────────────────────
# 5. 合并 Roboflow 数据到训练目录
# ─────────────────────────────────────────────
def merge_to_training():
    import shutil
    train_dir = Path(__file__).parent.parent / "datasets" / "processed" / "golf_ball_detection"
    roboflow_dir = BASE / "roboflow_golf_ball"

    for dataset in roboflow_dir.glob("dataset*"):
        for split in ["train", "valid", "test"]:
            src_images = dataset / split / "images"
            src_labels = dataset / split / "labels"
            dst_split = "val" if split == "valid" else split
            dst_images = train_dir / dst_split / "images"
            dst_labels = train_dir / dst_split / "labels"
            dst_images.mkdir(parents=True, exist_ok=True)
            dst_labels.mkdir(parents=True, exist_ok=True)

            if src_images.exists():
                for f in src_images.glob("*"):
                    shutil.copy2(f, dst_images / f"roboflow_{f.name}")
            if src_labels.exists():
                for f in src_labels.glob("*"):
                    shutil.copy2(f, dst_labels / f"roboflow_{f.name}")

    print(f"✓ Roboflow 数据已合并到 {train_dir}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--roboflow-key", help="Roboflow API key（从 app.roboflow.com 获取）")
    parser.add_argument("--all", action="store_true", help="下载所有可自动下载的数据集")
    parser.add_argument("--merge", action="store_true", help="合并 Roboflow 数据到训练目录")
    args = parser.parse_args()

    if args.roboflow_key or args.all:
        key = args.roboflow_key or input("请输入 Roboflow API key: ")
        download_roboflow(key)

    download_golfdb()
    download_tracknet()
    download_caddieSet()

    if args.merge:
        merge_to_training()

    print("\n─── 数据集状态汇总 ───")
    for name in ["roboflow_golf_ball", "golfdb", "tracknet", "caddieSet"]:
        d = BASE / name
        files = list(d.rglob("*")) if d.exists() else []
        print(f"  {name}: {len([f for f in files if f.is_file()])} 个文件")
