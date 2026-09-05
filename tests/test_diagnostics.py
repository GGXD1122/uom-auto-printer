import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from uom_printer import diagnostics
from uom_printer.paths import log_dir, output_dir


def test_log_directory_defaults_to_app_data(tmp_path: Path, monkeypatch) -> None:
    app_data = tmp_path / "app-data"
    monkeypatch.setenv("UOM_PRINTER_APP_DATA", str(app_data))
    assert log_dir() == app_data / "logs"
    assert log_dir().is_dir()


def test_session_log_is_created_and_writable(tmp_path: Path, monkeypatch) -> None:
    app_data = tmp_path / "app-data"
    monkeypatch.setenv("UOM_PRINTER_APP_DATA", str(app_data))
    diagnostics._log_path = None
    logger = diagnostics.get_logger()
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

    path = diagnostics.initialize_logging()
    logger.info("诊断日志测试")
    for handler in logger.handlers:
        handler.flush()

    content = path.read_text(encoding="utf-8-sig")
    assert path.parent == app_data / "logs"
    assert path.name == diagnostics.LOG_FILENAME
    assert "应用启动" in content
    assert "诊断日志测试" in content
    handler = logger.handlers[0]
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == diagnostics.LOG_FILE_MAX_BYTES
    assert handler.backupCount == diagnostics.LOG_BACKUP_COUNT

    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    diagnostics._log_path = None


def test_legacy_logs_are_pruned_to_migration_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "LEGACY_LOG_BUDGET_BYTES", 10)
    oldest = tmp_path / "运行日志-2026-01-01_00-00-00.log"
    newest = tmp_path / "运行日志-2026-01-02_00-00-00.log"
    oldest.write_bytes(b"123456")
    newest.write_bytes(b"123456")
    os.utime(oldest, (1, 1))
    os.utime(newest, (2, 2))

    diagnostics._prune_legacy_logs(tmp_path)

    assert newest.exists()
    assert not oldest.exists()


def test_default_output_directory_is_on_desktop(tmp_path: Path, monkeypatch) -> None:
    desktop = tmp_path / "Desktop"
    monkeypatch.setenv("UOM_PRINTER_DESKTOP", str(desktop))
    assert output_dir() == desktop / "UOM实名登记标识"
    assert output_dir().is_dir()
