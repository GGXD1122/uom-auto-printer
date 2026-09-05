from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


INSTALL_MUTEX_NAME = r"Global\GeGeXD-UOM-Auto-Printer"
ERROR_ALREADY_EXISTS = 183


class SingleInstanceGuard(QObject):
    """Prevent duplicate processes and ask the running process to show itself."""

    activate_requested = Signal()

    def __init__(self, data_directory: Path, parent=None) -> None:
        super().__init__(parent)
        identity = hashlib.sha256(str(data_directory.resolve()).casefold().encode("utf-8")).hexdigest()[:16]
        self.server_name = f"gegexd-uom-printer-{identity}"
        self.lock = QLockFile(str(data_directory / "uom-printer.lock"))
        self.lock.setStaleLockTime(10_000)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._activate_existing_window)
        self.notified_existing_instance = False
        self.install_mutex_handle = None
        self.install_mutex_already_exists = False
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            self.install_mutex_handle = kernel32.CreateMutexW(
                None,
                False,
                INSTALL_MUTEX_NAME,
            )
            self.install_mutex_already_exists = bool(
                self.install_mutex_handle and kernel32.GetLastError() == ERROR_ALREADY_EXISTS
            )

    def acquire(self) -> bool:
        if self.install_mutex_already_exists:
            self.notified_existing_instance = self._notify_existing_instance()
            return False
        if not self.lock.tryLock(100):
            self.notified_existing_instance = self._notify_existing_instance()
            return False
        if self.server.listen(self.server_name):
            return True
        QLocalServer.removeServer(self.server_name)
        if self.server.listen(self.server_name):
            return True
        self.lock.unlock()
        return False

    def _notify_existing_instance(self) -> bool:
        socket = QLocalSocket(self)
        socket.connectToServer(self.server_name)
        if not socket.waitForConnected(800):
            return False
        socket.write(b"activate")
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return True

    def _activate_existing_window(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is not None:
                socket.readAll()
                socket.disconnectFromServer()
                socket.deleteLater()
        self.activate_requested.emit()

    def close(self) -> None:
        self.server.close()
        self.lock.unlock()
        if self.install_mutex_handle:
            ctypes.windll.kernel32.CloseHandle(self.install_mutex_handle)
            self.install_mutex_handle = None
