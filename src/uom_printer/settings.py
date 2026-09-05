from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .layout_template import (
    DEFAULT_PAPER_HEIGHT_MM,
    DEFAULT_PAPER_WIDTH_MM,
    MAX_PAPER_HEIGHT_MM,
    MAX_PAPER_WIDTH_MM,
    MIN_PAPER_HEIGHT_MM,
    MIN_PAPER_WIDTH_MM,
)
from .paths import config_path

DEFAULT_POLL_MIN_SECONDS = 3
DEFAULT_POLL_MAX_SECONDS = 10


@dataclass(slots=True)
class AppSettings:
    poll_seconds: int = 7
    poll_jitter_min_seconds: int = DEFAULT_POLL_MIN_SECONDS
    poll_jitter_max_seconds: int = DEFAULT_POLL_MAX_SECONDS
    auto_monitor: bool = False
    auto_print: bool = True
    manual_import_auto_print: bool = True
    floating_on_monitor: bool = False
    printer_name: str = ""
    output_directory: str = ""
    copies: int = 1
    qr_label_copies: int = 2
    info_label_copies: int = 1
    paper_width_mm: float = DEFAULT_PAPER_WIDTH_MM
    paper_height_mm: float = DEFAULT_PAPER_HEIGHT_MM
    label_dpi: int = 600
    uom_auto_open_registration: bool = True
    uom_keep_logged_in: bool = True
    sidebar_collapsed: bool = False
    custom_layout_enabled: bool = False
    layout_template_name: str = "60×40 安全预设"
    layout_preset_file: str = ""
    floating_x: int | None = None
    floating_y: int | None = None


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()

    def load(self) -> AppSettings:
        raw = self._read_json(self.path)
        restored_from_backup = False
        if raw is None:
            raw = self._read_json(self.backup_path)
            restored_from_backup = raw is not None
        if raw is None:
            return AppSettings()

        values: dict[str, Any] = {}
        for key in AppSettings.__dataclass_fields__:
            if key in raw:
                values[key] = raw[key]
        legacy_copies = raw.get("copies")
        if "qr_label_copies" not in raw and legacy_copies is not None:
            values["qr_label_copies"] = legacy_copies
        if "info_label_copies" not in raw and legacy_copies is not None:
            values["info_label_copies"] = legacy_copies
        settings = AppSettings(**values)

        # The polling cadence is deliberately fixed. Normalize legacy
        # configuration so upgrades cannot retain the old 10-20s range.
        settings.poll_jitter_min_seconds = DEFAULT_POLL_MIN_SECONDS
        settings.poll_jitter_max_seconds = DEFAULT_POLL_MAX_SECONDS
        settings.poll_seconds = (DEFAULT_POLL_MIN_SECONDS + DEFAULT_POLL_MAX_SECONDS + 1) // 2
        settings.qr_label_copies = self._bounded_int(settings.qr_label_copies, 1, 20, 2)
        settings.info_label_copies = self._bounded_int(settings.info_label_copies, 1, 20, 1)
        settings.paper_width_mm = self._bounded_float(
            settings.paper_width_mm,
            MIN_PAPER_WIDTH_MM,
            MAX_PAPER_WIDTH_MM,
            DEFAULT_PAPER_WIDTH_MM,
        )
        settings.paper_height_mm = self._bounded_float(
            settings.paper_height_mm,
            MIN_PAPER_HEIGHT_MM,
            MAX_PAPER_HEIGHT_MM,
            DEFAULT_PAPER_HEIGHT_MM,
        )
        settings.layout_template_name = str(settings.layout_template_name or "").strip() or "60×40 安全预设"
        settings.layout_preset_file = Path(str(settings.layout_preset_file or "")).name
        settings.floating_x = self._optional_int(settings.floating_x)
        settings.floating_y = self._optional_int(settings.floating_y)
        if restored_from_backup:
            self._write(settings, backup_existing=False)
        return settings

    def save(self, settings: AppSettings) -> None:
        self._write(settings, backup_existing=True)

    def _write(self, settings: AppSettings, *, backup_existing: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
        if backup_existing and self.path.exists():
            try:
                shutil.copy2(self.path, self.backup_path)
            except OSError:
                pass
        os.replace(temporary, self.path)

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.bak")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
        try:
            return max(minimum, min(maximum, int(value)))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _bounded_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
        try:
            return max(minimum, min(maximum, float(value)))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
