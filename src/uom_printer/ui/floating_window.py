from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QHBoxLayout, QVBoxLayout, QWidget

from ..paths import resource_path
from .widgets import RoundedAvatarLabel, SpeechBubble


SUPPORTED_DROP_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _supported_path_from_mime(mime_data) -> Path | None:
    for url in mime_data.urls():
        path = Path(url.toLocalFile())
        if path.is_file() and path.suffix.lower() in SUPPORTED_DROP_EXTENSIONS:
            return path
    return None


class FloatingStatusWindow(QWidget):
    expand_requested = Signal()
    file_dropped = Signal(str)
    position_changed = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drag_origin: QPoint | None = None
        self._press_position: QPoint | None = None
        self._dragged = False
        self._drop_active = False
        self.setWindowTitle("UOM自动打印状态")
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setFixedHeight(92)
        self._state = "idle"
        self._pulse_on = True
        self._base_title = "待命"
        self._base_detail = "拖个实名码给我"
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(650)
        self._pulse_timer.timeout.connect(self._pulse_status)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(3)
        self.avatar_block = QWidget()
        self.avatar_block.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        avatar_layout = QVBoxLayout(self.avatar_block)
        avatar_layout.setContentsMargins(0, 1, 0, 0)
        avatar_layout.setSpacing(0)
        avatar = RoundedAvatarLabel(resource_path("assets/gegexd-avatar.jpg"))
        avatar.setFixedSize(52, 52)
        avatar_name = QLabel("鸽鸽XD", objectName="FloatAvatarName")
        avatar_name.setAlignment(Qt.AlignCenter)
        avatar_layout.addWidget(avatar, 0, Qt.AlignHCenter)
        avatar_layout.addWidget(avatar_name)
        outer.addWidget(self.avatar_block)
        self.bubble = SpeechBubble("● 待命", "拖个实名码给我", compact=True)
        self.bubble.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.bubble.setToolTip("点击打开主界面；拖入文件后按自动打印开关处理")
        outer.addWidget(self.bubble)
        self._resize_to_content()

    def sizeHint(self) -> QSize:
        layout = self.layout()
        margins = layout.contentsMargins()
        content_width = (
            self.avatar_block.sizeHint().width()
            + self.bubble.sizeHint().width()
            + layout.spacing()
        )
        return QSize(margins.left() + margins.right() + content_width, 92)

    def _resize_to_content(self) -> None:
        old_bottom_right = self.frameGeometry().bottomRight()
        was_visible = self.isVisible()
        self.setFixedWidth(self.sizeHint().width())
        if was_visible:
            proposed = QPoint(
                old_bottom_right.x() - self.width() + 1,
                old_bottom_right.y() - self.height() + 1,
            )
            self.move(self._clamped_position(proposed))

    def _clamped_position(self, proposed: QPoint, screen=None) -> QPoint:
        target_screen = screen or QApplication.screenAt(
            proposed + QPoint(self.width() // 2, self.height() // 2)
        ) or QApplication.primaryScreen()
        if target_screen is None:
            return proposed
        area = target_screen.availableGeometry()
        margin = 6
        max_x = max(area.left() + margin, area.right() - self.width() - margin + 1)
        max_y = max(area.top() + margin, area.bottom() - self.height() - margin + 1)
        return QPoint(
            min(max(proposed.x(), area.left() + margin), max_x),
            min(max(proposed.y(), area.top() + margin), max_y),
        )

    def set_status(self, title: str, detail: str, state: str = "idle") -> None:
        self._state = state
        self._base_title = title
        short_detail = {
            "等待任务": "等你开工",
            "监听中": "等新登记",
            "发现新登记": "马上生成标签",
            "正在读取": "拉取最新数据",
            "正在读取UOM": "拉取最新数据",
            "信息已识别": "字段都齐了",
            "正在排版": "二维码排版中",
            "正在生成": "二维码排版中",
            "二维码已生成": "正在套用模板",
            "标签已生成": "预览已更新",
            "正在打印": "送往打印机",
            "打印完成": "码出来啦",
            "打印任务已提交": "码出来啦",
            "处理完成": "这波很顺",
            "监听已停止": "后台待命中",
            "已最小化": "后台运行中",
            "需要注意": "点我查看详情",
            "处理失败": "点我查看错误",
        }.get(title, detail)
        if len(short_detail) > 16:
            short_detail = short_detail[:15] + "…"
        self._base_detail = short_detail
        if not self._drop_active:
            self.bubble.set_message(f"● {title}", short_detail, state)
        self._resize_to_content()
        self._pulse_on = True
        if state in ("working", "success"):
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()

    def _pulse_status(self) -> None:
        if self._drop_active:
            return
        self._pulse_on = not self._pulse_on
        self.bubble.title_label.setText(f"{'●' if self._pulse_on else '•'} {self._base_title}")

    def show_near_corner(self, saved_position: tuple[int, int] | None = None) -> None:
        screen = QApplication.primaryScreen()
        if saved_position is not None:
            proposed = QPoint(int(saved_position[0]), int(saved_position[1]))
            screen = QApplication.screenAt(proposed) or screen
            self.move(self._clamped_position(proposed, screen))
        elif screen:
            area = screen.availableGeometry()
            self.move(
                self._clamped_position(
                    QPoint(area.right() - self.width() - 18, area.bottom() - self.height() - 18),
                    screen,
                )
            )
        self.show()
        self.raise_()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_position = event.globalPosition().toPoint()
            self._dragged = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton:
            if self._press_position is not None and (event.globalPosition().toPoint() - self._press_position).manhattanLength() > 4:
                self._dragged = True
            pointer = event.globalPosition().toPoint()
            self.move(
                self._clamped_position(
                    pointer - self._drag_origin,
                    QApplication.screenAt(pointer),
                )
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        should_open = event.button() == Qt.LeftButton and not self._dragged
        was_dragged = self._dragged
        self._drag_origin = None
        self._press_position = None
        super().mouseReleaseEvent(event)
        if was_dragged:
            self.position_changed.emit(self.x(), self.y())
        elif should_open:
            self.expand_requested.emit()

    @staticmethod
    def _supported_drop_path(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> Path | None:
        return _supported_path_from_mime(event.mimeData())

    def _set_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self._drop_active == active:
            return
        self._drop_active = active
        if active:
            self.bubble.set_message("● 松手即可导入", "按自动打印开关处理", "success")
        else:
            self.bubble.set_message(f"● {self._base_title}", self._base_detail, self._state)
        self._resize_to_content()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._supported_drop_path(event) is not None:
            self._set_drop_active(True)
            event.acceptProposedAction()
            return
        self._set_drop_active(False)
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._supported_drop_path(event) is not None:
            self._set_drop_active(True)
            event.acceptProposedAction()
            return
        self._set_drop_active(False)
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        path = self._supported_drop_path(event)
        self._set_drop_active(False)
        if path is None:
            super().dropEvent(event)
            return
        self.set_status("收到文件", "正在识别并生成标签", "working")
        event.acceptProposedAction()
        self.file_dropped.emit(str(path))
