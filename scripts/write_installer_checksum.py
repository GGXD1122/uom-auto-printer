from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    release_dir = args.release_dir.resolve()
    candidates = sorted(
        release_dir.glob(f"*-Setup-v{args.version}.exe"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"未找到 v{args.version} 安装包")
    installer = candidates[0]
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    manifest = release_dir / "安装包-SHA256.txt"
    manifest.write_text(f"{digest}  {installer.name}\n", encoding="utf-8")
    print(f"已生成安装包校验：{manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
