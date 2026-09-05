from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QCoreApplication, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .diagnostics import get_logger, initialize_logging, install_exception_hooks
from .paths import app_data_dir, resource_path
from .single_instance import SingleInstanceGuard
from .ui.main_window import MainWindow
from .ui.rounded_dialog import information
from .ui.styles import APP_STYLE


def main() -> int:
    log_path = initialize_logging()
    install_exception_hooks()
    logger = get_logger()

    def qt_message_handler(message_type, context, message) -> None:
        levels = {
            QtMsgType.QtDebugMsg: 10,
            QtMsgType.QtInfoMsg: 20,
            QtMsgType.QtWarningMsg: 30,
            QtMsgType.QtCriticalMsg: 40,
            QtMsgType.QtFatalMsg: 50,
        }
        location = f"{context.file}:{context.line}" if context and context.file else "Qt"
        logger.log(levels.get(message_type, 20), "Qt消息 | %s | %s", location, message)

    qInstallMessageHandler(qt_message_handler)
    if os.environ.get("UOM_SOFTWARE_RENDERING") == "1":
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
        logger.info("已启用Qt软件渲染兼容模式")
    application = QApplication(sys.argv)
    application.setApplicationName("UOM自动打印")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("鸽鸽XD x Codex开发")
    application.setQuitOnLastWindowClosed(False)
    icon_path = resource_path("assets/app-icon.png")
    if icon_path.exists():
        application.setWindowIcon(QIcon(str(icon_path)))
    application.setStyle("Fusion")
    application.setStyleSheet(APP_STYLE)
    instance_guard = SingleInstanceGuard(app_data_dir(), application)
    if not instance_guard.acquire():
        detail = (
            "UOM自动打印已经在运行。\n\n"
            "我已经尝试把原来的窗口叫到前台，请查看任务栏或右下角托盘图标。\n"
            "不用再开一个啦，不然打印机都要以为自己有两份工作。"
        )
        if not instance_guard.notified_existing_instance:
            detail += "\n\n如果仍看不到，请在任务管理器结束旧进程后再打开。"
        information(None, "程序已在运行", detail)
        logger.warning("检测到重复启动，已阻止第二个程序实例")
        logging.shutdown()
        return 0
    window = MainWindow(log_path=log_path)
    instance_guard.activate_requested.connect(window.restore_from_floating)
    window.show()
    exit_code = application.exec()
    instance_guard.close()
    logger.info("应用正常退出 | exit_code=%s", exit_code)
    logging.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
