from __future__ import annotations

import os
import sys
import ctypes
import shutil
from pathlib import Path


APP_FOLDER_NAME = "UOM-Auto-Printer"
LEGACY_APP_FOLDER_NAME = "OUM-Auto-Printer"


def resource_path(relative: str) -> Path:
    """Resolve bundled PyInstaller assets as well as source-tree assets."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return bundle_root / relative


def app_data_dir() -> Path:
    override = os.environ.get("UOM_PRINTER_APP_DATA")
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home())
    else:
        root = Path.home() / ".local" / "share"
    path = root / APP_FOLDER_NAME
    legacy_path = root / LEGACY_APP_FOLDER_NAME
    if not path.exists() and legacy_path.exists():
        try:
            legacy_path.rename(path)
        except OSError:
            path = legacy_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    data_dir = app_data_dir()
    path = data_dir / "auto-printer-config.json"
    legacy_path = data_dir / "config.json"
    if not path.exists() and legacy_path.exists():
        try:
            shutil.copy2(legacy_path, path)
        except OSError:
            return legacy_path
    return path


def layout_template_path() -> Path:
    return app_data_dir() / "custom-layout.json"


def database_path() -> Path:
    return app_data_dir() / "history.sqlite3"


def model_catalog_path() -> Path:
    return app_data_dir() / "model-catalog.json"


def inbox_dir() -> Path:
    path = app_data_dir() / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir(custom_path: str = "") -> Path:
    path = Path(custom_path).expanduser() if custom_path.strip() else desktop_dir() / "UOM实名登记标识"
    path.mkdir(parents=True, exist_ok=True)
    return path


def preview_dir() -> Path:
    path = app_data_dir() / "previews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def desktop_dir() -> Path:
    override = os.environ.get("UOM_PRINTER_DESKTOP")
    if override:
        return Path(override)
    if os.name == "nt":
        try:
            buffer = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY resolves redirected/OneDrive desktops.
            result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buffer)  # type: ignore[attr-defined]
            if result == 0 and buffer.value:
                return Path(buffer.value)
        except Exception:
            pass
    return Path.home() / "Desktop"


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
