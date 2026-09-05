from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .diagnostics import get_logger


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str, str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as exc:
            trace = traceback.format_exc()
            get_logger().error("后台任务失败 | function=%r\n%s", self.function, trace)
            self.signals.error.emit(str(exc), trace)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()
