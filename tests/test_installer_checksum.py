from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


def test_installer_checksum_script_targets_requested_version(tmp_path: Path) -> None:
    installer = tmp_path / "UOM自动打印-Setup-v9.8.7.exe"
    installer.write_bytes(b"demo-installer")
    script = Path(__file__).resolve().parents[1] / "scripts" / "write_installer_checksum.py"

    subprocess.run(
        [
            sys.executable,
            str(script),
            "--release-dir",
            str(tmp_path),
            "--version",
            "9.8.7",
        ],
        check=True,
    )

    expected = hashlib.sha256(b"demo-installer").hexdigest()
    assert (tmp_path / "安装包-SHA256.txt").read_text(encoding="utf-8") == (
        f"{expected}  {installer.name}\n"
    )
