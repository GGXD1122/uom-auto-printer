from __future__ import annotations

import sys
from pathlib import Path


KEEP_TRANSLATIONS = {
    "qt_en.qm",
    "qt_zh_CN.qm",
    "qtbase_en.qm",
    "qtbase_zh_CN.qm",
    "qtwebengine_en.qm",
    "qtwebengine_zh_CN.qm",
}
KEEP_WEBENGINE_LOCALES = {"en-US.pak", "zh-CN.pak"}


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: prune_windows_bundle.py <pyinstaller-dist-directory>")
    distribution = Path(sys.argv[1]).resolve()
    translations = distribution / "_internal" / "PySide6" / "translations"
    if not translations.is_dir() or distribution.name != "UOMAutoPrinter":
        raise SystemExit(f"refusing to prune unexpected directory: {distribution}")

    removed = 0
    for path in translations.glob("*.qm"):
        if path.name not in KEEP_TRANSLATIONS:
            removed += path.stat().st_size
            path.unlink()
    locales = translations / "qtwebengine_locales"
    if locales.is_dir():
        for path in locales.glob("*.pak"):
            if path.name not in KEEP_WEBENGINE_LOCALES:
                removed += path.stat().st_size
                path.unlink()
    print(f"Pruned unused Qt translations: {removed / 1024 / 1024:.1f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
