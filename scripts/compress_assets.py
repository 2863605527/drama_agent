"""P2-10 媒体资产治理工具：压缩 assets/images|uploads 下的过重图片。

用法：
    python scripts/compress_assets.py [--threshold-kb 500] [--quality 82] [--dry-run]

规则：
- 只处理 images/ 与 uploads/（uuid 文件名，内容变则 URL 变，原地覆盖不影响引用）；
- 跳过小于阈值的文件；PNG 转成压缩 PNG（optimize），JPEG/WEBP 重压缩；
- videos/ audio/ final/ 不在范围内（视频压缩涉及编码质量权衡，不自动做）；
- --dry-run 只统计不写盘。支持断点续跑（已压缩过且低于阈值的自动跳过）。

依赖：Pillow（pip install pillow）
"""
import argparse
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("缺少 Pillow：pip install pillow")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("assets/images", "assets/uploads")
_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _size_kb(p: Path) -> float:
    return p.stat().st_size / 1024


def compress_file(p: Path, quality: int, dry: bool) -> tuple[float, float]:
    """返回 (压缩前KB, 压缩后KB)；dry 模式不写盘。"""
    before = _size_kb(p)
    with Image.open(p) as im:
        fmt = im.format or "PNG"
        if fmt == "PNG":
            im.save(p, "PNG", optimize=True) if not dry else None
        elif fmt in ("JPEG", "WEBP", "BMP"):
            save_fmt = "WEBP" if fmt == "BMP" else fmt
            if fmt == "BMP":  # BMP 无压缩，转 WebP 最划算
                im = im.convert("RGB")
            im.save(p, save_fmt, quality=quality, optimize=True) if not dry else None
        else:
            return before, before
    after = _size_kb(p)
    return before, after


def main():
    ap = argparse.ArgumentParser(description="压缩 assets/images|uploads 过重图片")
    ap.add_argument("--threshold-kb", type=float, default=500, help="超过该大小（KB）才压缩，默认 500")
    ap.add_argument("--quality", type=int, default=82, help="重压缩质量（1-95），默认 82")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写盘")
    args = ap.parse_args()

    total_before = total_after = 0.0
    count = 0
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.suffix.lower() not in _IMG_EXT:
                continue
            if _size_kb(p) <= args.threshold_kb:
                continue
            try:
                before, after = compress_file(p, args.quality, args.dry_run)
            except Exception as e:  # noqa: BLE001
                print(f"  SKIP {p.relative_to(ROOT)}: {e}")
                continue
            total_before += before
            total_after += after
            count += 1
            print(f"  {'[dry]' if args.dry_run else '[ok ]'} {before:8.1f}KB -> {after:8.1f}KB  {p.relative_to(ROOT)}")

    saved = total_before - total_after
    print(f"\n共处理 {count} 个文件，压缩前 {total_before/1024:.1f}MB，压缩后 {total_after/1024:.1f}MB，节省 {saved/1024:.1f}MB"
          + ("（dry-run 未写盘）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
