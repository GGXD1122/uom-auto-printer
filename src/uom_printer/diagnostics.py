from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from . import __version__
from .paths import app_data_dir, log_dir


LOGGER_NAME = "uom_printer"
LOG_FILENAME = "运行日志.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
LEGACY_LOG_BUDGET_BYTES = 5 * 1024 * 1024
_log_path: Path | None = None


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def current_log_path() -> Path | None:
    return _log_path


def _prune_legacy_logs(folder: Path) -> None:
    """Keep only the newest legacy session logs within a small migration budget."""
    candidates = sorted(
        (path for path in folder.glob("运行日志-*.log") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    retained_bytes = 0
    for path in candidates:
        try:
            size = path.stat().st_size
            if retained_bytes + size <= LEGACY_LOG_BUDGET_BYTES:
                retained_bytes += size
            else:
                path.unlink()
        except OSError:
            continue


def _create_log_handler(folder: Path) -> RotatingFileHandler:
    global _log_path
    _prune_legacy_logs(folder)
    _log_path = folder / LOG_FILENAME
    return RotatingFileHandler(
        _log_path,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8-sig",
    )


def initialize_logging() -> Path:
    global _log_path
    if _log_path is not None:
        return _log_path

    try:
        folder = log_dir()
        handler = _create_log_handler(folder)
    except OSError:
        folder = app_data_dir() / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        handler = _create_log_handler(folder)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d | %(levelname)s | %(threadName)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger = get_logger()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.info("应用启动 | version=%s", __version__)
    logger.info(
        "运行环境 | os=%s | release=%s | python=%s | frozen=%s | executable=%s",
        platform.platform(),
        platform.release(),
        platform.python_version(),
        bool(getattr(sys, "frozen", False)),
        sys.executable,
    )
    logger.info("进程信息 | pid=%s | cwd=%s", os.getpid(), Path.cwd())
    logger.info("本次日志文件 | %s", _log_path)
    logger.info(
        "日志轮转 | 单文件上限=%s MiB | 备份数量=%s | 轮转日志总上限约=%s MiB",
        LOG_FILE_MAX_BYTES // (1024 * 1024),
        LOG_BACKUP_COUNT,
        (LOG_FILE_MAX_BYTES * (LOG_BACKUP_COUNT + 1)) // (1024 * 1024),
    )
    return _log_path


def install_exception_hooks() -> None:
    logger = get_logger()

    def system_hook(exc_type: type[BaseException], exc_value: BaseException, traceback: TracebackType | None) -> None:
        logger.critical("未捕获的主线程异常", exc_info=(exc_type, exc_value, traceback))

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        logger.critical(
            "未捕获的线程异常 | thread=%s",
            args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = system_hook
    threading.excepthook = thread_hook
