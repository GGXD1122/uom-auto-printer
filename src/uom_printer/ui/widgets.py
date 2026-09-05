from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QEnterEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class ToggleSwitch(QCheckBox):
    """An obvious, theme-independent on/off switch with a short animation."""

    TRACK_WIDTH = 46
    TRACK_HEIGHT = 24
    KNOB_SIZE = 18
    TEXT_GAP = 9

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(28)
        self._position = 1.0 if self.isChecked() else 0.0
        self._hovered = False
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._animation_value_changed)
        self.toggled.connect(self._animate_to_state)

    def _animation_value_changed(self, value) -> None:
        self._position = float(value)
        self.update()

    def _animate_to_state(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if not self.isVisible():
            self._position = target
            self.update()
            return
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(target)
        self._animation.start()

    def sizeHint(self) -> QSize:
        width = self.TRACK_WIDTH + self.TEXT_GAP + self.fontMetrics().horizontalAdvance(self.text()) + 4
        return QSize(width, max(28, self.fontMetrics().height() + 8))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        track_y = (self.height() - self.TRACK_HEIGHT) / 2
        track = QRectF(0.5, track_y + 0.5, self.TRACK_WIDTH - 1, self.TRACK_HEIGHT - 1)

        enabled = self.isEnabled()
        checked = self.isChecked()
        if not enabled:
            track_fill, track_border = "#e4e7ec", "#d0d5dd"
        elif checked:
            track_fill = "#12a66f" if self._hovered else "#17b26a"
            track_border = "#0e8f5f"
        else:
            track_fill = "#cfd6df" if self._hovered else "#d9dee5"
            track_border = "#b8c2cf"
        painter.setPen(QPen(QColor(track_border), 1))
        painter.setBrush(QColor(track_fill))
        painter.drawRoundedRect(track, self.TRACK_HEIGHT / 2, self.TRACK_HEIGHT / 2)

        knob_travel = self.TRACK_WIDTH - self.KNOB_SIZE - 4
        knob_x = 2 + knob_travel * self._position
        knob_y = track_y + (self.TRACK_HEIGHT - self.KNOB_SIZE) / 2
        painter.setPen(QPen(QColor(15, 23, 42, 28), 1))
        painter.setBrush(QColor("#ffffff" if enabled else "#f8fafc"))
        painter.drawEllipse(QRectF(knob_x, knob_y, self.KNOB_SIZE, self.KNOB_SIZE))

        state_font = painter.font()
        state_font.setPointSizeF(max(7.0, state_font.pointSizeF() - 2.0))
        state_font.setBold(True)
        painter.setFont(state_font)
        painter.setPen(QColor("#ffffff" if checked and enabled else "#667085"))
        if checked:
            state_rect = QRectF(3, track_y, 21, self.TRACK_HEIGHT)
            state_text = "开"
        else:
            state_rect = QRectF(23, track_y, 20, self.TRACK_HEIGHT)
            state_text = "关"
        painter.drawText(state_rect, Qt.AlignCenter, state_text)

        label_font = self.font()
        painter.setFont(label_font)
        painter.setPen(QColor("#344054" if enabled else "#98a2b3"))
        label_rect = QRectF(
            self.TRACK_WIDTH + self.TEXT_GAP,
            0,
            max(0, self.width() - self.TRACK_WIDTH - self.TEXT_GAP),
            self.height(),
        )
        painter.drawText(label_rect, Qt.AlignLeft | Qt.AlignVCenter, self.text())

class WheelSafeComboBox(QComboBox):
    """A combo box that changes only through an intentional click/keyboard action."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class CurrentPageStackedWidget(QStackedWidget):
    """Size a stacked sidebar from the visible page instead of the tallest page."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()


class PhotoDropTile(QFrame):
    """Square click/drop target for one registration photo."""

    clicked = Signal()
    fileDropped = Signal(str)
    SUPPORTED_SUFFIXES = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}

    def __init__(self, title: str, hint: str, parent=None) -> None:
        super().__init__(parent, objectName="PhotoDropTile")
        self._empty_hint = str(hint or "拖入或点击选择")
        self._file_path: Path | None = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(160, 160)
        self.setProperty("dropActive", False)
        self.setProperty("selected", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        self.icon_label = QLabel("＋", objectName="PhotoDropPreview")
        self.icon_label.setFixedSize(138, 82)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setProperty("hasPreview", False)
        self.title_label = QLabel(title, objectName="PhotoDropTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(False)
        self.title_label.setFixedHeight(24)
        self.detail_label = QLabel(self._empty_hint, objectName="PhotoDropDetail")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(False)
        self.detail_label.setFixedHeight(18)
        layout.addWidget(self.icon_label, 0, Qt.AlignHCenter)
        layout.addWidget(self.title_label)
        layout.addWidget(self.detail_label)

    @classmethod
    def accepts_path(cls, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in cls.SUPPORTED_SUFFIXES

    def set_file(self, path: Path | None) -> None:
        selected = path is not None
        self._file_path = path
        self.setProperty("selected", selected)
        if selected:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.clear_preview("…")
            else:
                self.set_preview_pixmap(pixmap)
            self.detail_label.setText("点击可更换")
            self.setToolTip(str(path))
        else:
            self.clear_preview("＋")
            self.detail_label.setText(self._empty_hint)
            self.setToolTip("")
        self._repolish()

    def has_preview(self) -> bool:
        pixmap = self.icon_label.pixmap()
        return bool(self.icon_label.property("hasPreview")) and pixmap is not None and not pixmap.isNull()

    def set_preview_data(self, data: bytes) -> bool:
        pixmap = QPixmap()
        if not pixmap.loadFromData(bytes(data or b"")):
            return False
        self.set_preview_pixmap(pixmap)
        return True

    def set_preview_pixmap(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        target_size = self.icon_label.size()
        scaled = pixmap.scaled(
            target_size,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        x = max(0, (scaled.width() - target_size.width()) // 2)
        y = max(0, (scaled.height() - target_size.height()) // 2)
        cropped = scaled.copy(x, y, target_size.width(), target_size.height())
        rounded = QPixmap(target_size)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, target_size.width(), target_size.height()), 9, 9)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        self.icon_label.setText("")
        self.icon_label.setPixmap(rounded)
        self.icon_label.setProperty("hasPreview", True)
        self._repolish()

    def clear_preview(self, placeholder: str = "＋") -> None:
        self.icon_label.clear()
        self.icon_label.setText(placeholder)
        self.icon_label.setProperty("hasPreview", False)
        self._repolish()

    def _restore_detail(self) -> None:
        self.detail_label.setText("点击可更换" if self._file_path is not None else self._empty_hint)

    def _set_drop_active(self, active: bool) -> None:
        if bool(self.property("dropActive")) == bool(active):
            return
        self.setProperty("dropActive", bool(active))
        self._repolish()

    def _repolish(self) -> None:
        for widget in (self, self.icon_label, self.title_label, self.detail_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    @staticmethod
    def _event_path(event) -> Path | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        urls = mime.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        return Path(urls[0].toLocalFile())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        path = self._event_path(event)
        if path is not None and self.accepts_path(path):
            self._set_drop_active(True)
            self.detail_label.setText("松手即可使用")
            event.acceptProposedAction()
            return
        self._set_drop_active(False)
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_active(False)
        self._restore_detail()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        path = self._event_path(event)
        self._set_drop_active(False)
        if path is None or not self.accepts_path(path):
            self._restore_detail()
            event.ignore()
            return
        event.acceptProposedAction()
        self.fileDropped.emit(str(path))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled() and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class RoundedAvatarLabel(QLabel):
    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self._source = QPixmap(str(path))
        self.setFixedSize(44, 44)
        self.setToolTip("鸽鸽XD：我在这儿盯着打印机")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 10, 10)
        painter.setClipPath(clip)
        if not self._source.isNull():
            # Render at the screen's physical pixel density, then map back to
            # logical pixels. This keeps the 1080px source sharp on Windows DPI scaling.
            ratio = max(1.0, painter.device().devicePixelRatioF())
            target = QSize(round(self.width() * ratio), round(self.height() * ratio))
            scaled = self._source.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            logical_size = scaled.deviceIndependentSize()
            x = round((self.width() - logical_size.width()) / 2)
            y = round((self.height() - logical_size.height()) / 2)
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(rect, QColor("#edf3ff"))
        painter.setClipping(False)
        painter.setPen(QPen(QColor("#82a2ff"), 1))
        painter.drawRoundedRect(rect, 10, 10)


class SpeechBubble(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str,
        parent=None,
        *,
        compact: bool = False,
        pointer_position: str = "left",
    ) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._compact = compact
        self._pointer_position = pointer_position if pointer_position in {"left", "top-left"} else "left"
        self._minimum_bubble_width = 84 if compact else 178
        self._maximum_bubble_width = 250 if compact else 680
        self._minimum_bubble_height = 64 if self._pointer_position == "top-left" else (50 if compact else 54)
        self.setMinimumHeight(self._minimum_bubble_height)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        if self._pointer_position == "top-left":
            layout.setContentsMargins(16, 17, 16, 7)
        else:
            layout.setContentsMargins(19 if compact else 23, 5 if compact else 7, 10 if compact else 16, 5 if compact else 7)
        layout.setSpacing(0 if compact else 1)
        self.title_label = QLabel(title, objectName="FloatBubbleTitle" if compact else "BubbleTitle")
        self.subtitle_label = QLabel(subtitle, objectName="FloatBubbleSubtitle" if compact else "BubbleSubtitle")
        self.title_label.setTextFormat(Qt.PlainText)
        self.subtitle_label.setTextFormat(Qt.PlainText)
        self.title_label.setWordWrap(not compact)
        self.subtitle_label.setWordWrap(not compact)
        self.title_label.setMinimumWidth(0)
        self.subtitle_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.subtitle_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

    def sizeHint(self) -> QSize:
        layout = self.layout()
        margins = layout.contentsMargins()
        horizontal_padding = margins.left() + margins.right()
        vertical_padding = margins.top() + margins.bottom() + layout.spacing()
        max_content_width = self._maximum_bubble_width - horizontal_padding

        def line_width(label: QLabel) -> int:
            lines = label.text().splitlines() or [""]
            return max(label.fontMetrics().horizontalAdvance(line) for line in lines)

        # Leave a few pixels beyond the measured glyph box. Qt/Windows font
        # rounding can otherwise wrap the last Chinese character by one pixel.
        natural_content_width = max(line_width(self.title_label), line_width(self.subtitle_label)) + (8 if self._compact else 6)
        content_width = min(max_content_width, natural_content_width)
        width = max(self._minimum_bubble_width, content_width + horizontal_padding)
        wrapped_width = max(1, width - horizontal_padding)

        def wrapped_height(label: QLabel) -> int:
            bounds = label.fontMetrics().boundingRect(
                QRect(0, 0, wrapped_width, 1000),
                Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
                label.text(),
            )
            return max(label.fontMetrics().height(), bounds.height())

        content_height = wrapped_height(self.title_label) + wrapped_height(self.subtitle_label)
        height = max(self._minimum_bubble_height, content_height + vertical_padding)
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._minimum_bubble_width, self._minimum_bubble_height)

    def pointer_tip(self) -> QPoint:
        if self._pointer_position == "top-left":
            return QPoint(25, 1)
        return QPoint(1, round(self.height() / 2))

    def set_message(self, title: str, subtitle: str, state: str = "idle") -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self._state = state
        for label in (self.title_label, self.subtitle_label):
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)
        self.updateGeometry()
        if self.layout() is not None:
            self.layout().invalidate()
        self.update()

    def paintEvent(self, event) -> None:
        colors = {
            "idle": ("#f8faff", "#dce6f8"),
            "working": ("#eff4ff", "#b2ccff"),
            "success": ("#effcf5", "#abefc6"),
            "warning": ("#fffaeb", "#fedf89"),
            "error": ("#fff1f0", "#fda29b"),
        }
        fill, border = colors.get(self._state, colors["idle"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pointer_width = 8 if self._compact else 10
        pointer_height = 10 if self._pointer_position == "top-left" else 0
        if self._pointer_position == "top-left":
            body = QRectF(0.5, pointer_height + 0.5, self.width() - 1, self.height() - pointer_height - 1)
        else:
            body = QRectF(pointer_width + 0.5, 0.5, self.width() - pointer_width - 1, self.height() - 1)
        shape = QPainterPath()
        shape.addRoundedRect(body, 10 if self._compact else 12, 10 if self._compact else 12)
        pointer = QPainterPath()
        if self._pointer_position == "top-left":
            tip = self.pointer_tip()
            pointer.moveTo(14, pointer_height + 1)
            pointer.lineTo(tip.x(), tip.y())
            pointer.lineTo(37, pointer_height + 1)
        else:
            middle = self.height() / 2
            pointer.moveTo(pointer_width + 1, middle - 7)
            pointer.lineTo(1, middle)
            pointer.lineTo(pointer_width + 1, middle + 6)
        pointer.closeSubpath()
        shape = shape.united(pointer)
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(fill))
        painter.drawPath(shape)


class FeedbackButton(QPushButton):
    """A lightweight desktop button with visible hover, press and result feedback."""

    def __init__(self, text: str = "", parent=None, *, elevated: bool = True, **kwargs) -> None:
        super().__init__(text, parent, **kwargs)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoDefault(False)
        self._elevated = elevated
        self._shadow: QGraphicsDropShadowEffect | None = None
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._clear_feedback)
        self.clicked.connect(self._show_click_feedback)
        if elevated:
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setColor(QColor(15, 23, 42, 42))
            self.setGraphicsEffect(self._shadow)
            self._set_shadow("rest")

    def _set_shadow(self, state: str) -> None:
        shadow = getattr(self, "_shadow", None)
        if shadow is None:
            return
        if not self.isEnabled():
            shadow.setBlurRadius(3)
            shadow.setOffset(QPoint(0, 1))
            shadow.setColor(QColor(15, 23, 42, 12))
        elif state == "pressed":
            shadow.setBlurRadius(5)
            shadow.setOffset(QPoint(0, 1))
            shadow.setColor(QColor(15, 23, 42, 28))
        elif state == "hover":
            shadow.setBlurRadius(16)
            shadow.setOffset(QPoint(0, 4))
            shadow.setColor(QColor(15, 23, 42, 52))
        else:
            shadow.setBlurRadius(11)
            shadow.setOffset(QPoint(0, 3))
            shadow.setColor(QColor(15, 23, 42, 38))

    def _show_click_feedback(self) -> None:
        self.setProperty("feedback", "clicked")
        self._repolish()
        self._feedback_timer.start(180)

    def flash_success(self, duration_ms: int = 900) -> None:
        self.setProperty("feedback", "success")
        self._repolish()
        self._feedback_timer.start(duration_ms)

    def flash_error(self, duration_ms: int = 1200) -> None:
        self.setProperty("feedback", "error")
        self._repolish()
        self._feedback_timer.start(duration_ms)

    def _clear_feedback(self) -> None:
        self.setProperty("feedback", "")
        self._repolish()

    def _repolish(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._set_shadow("hover")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_shadow("rest")
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self._set_shadow("pressed")
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._set_shadow("hover" if self.rect().contains(event.position().toPoint()) else "rest")
        super().mouseReleaseEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        self._set_shadow("rest")


class CopyCountSelector(QWidget):
    """Compact minus/value/plus selector used by each label preview card."""

    valueChanged = Signal(int)

    def __init__(self, value: int = 1, parent=None, *, minimum: int = 1, maximum: int = 20) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._value = minimum
        self.setObjectName("CopyCountSelector")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(102, 32)
        self.setToolTip("使用 − / + 调整这套标签的打印张数")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        self.minus_button = QPushButton("−", objectName="CopyStepButton")
        self.minus_button.setProperty("side", "left")
        self.minus_button.setToolTip("减少一张")
        self.minus_button.clicked.connect(lambda: self.setValue(self._value - 1))
        self.value_label = QLabel(objectName="CopyCountValue")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.plus_button = QPushButton("+", objectName="CopyStepButton")
        self.plus_button.setProperty("side", "right")
        self.plus_button.setToolTip("增加一张")
        self.plus_button.clicked.connect(lambda: self.setValue(self._value + 1))
        layout.addWidget(self.minus_button)
        layout.addWidget(self.value_label, 1)
        layout.addWidget(self.plus_button)
        self._set_step_buttons_quiet(True)
        self.setValue(value)

    def _set_step_buttons_quiet(self, quiet: bool) -> None:
        for button in (self.minus_button, self.plus_button):
            if bool(button.property("quiet")) == quiet:
                continue
            button.setProperty("quiet", quiet)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._set_step_buttons_quiet(False)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_step_buttons_quiet(True)
        super().leaveEvent(event)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        normalized = max(self._minimum, min(self._maximum, int(value)))
        changed = normalized != self._value
        self._value = normalized
        self.value_label.setText(f"{normalized} 张")
        self.minus_button.setEnabled(normalized > self._minimum)
        self.plus_button.setEnabled(normalized < self._maximum)
        if changed:
            self.valueChanged.emit(normalized)

    def wheelEvent(self, event) -> None:
        # Copy counts are intentionally click-only.  A selector lives inside
        # the scrolling sidebar, so consuming the wheel here both changes the
        # quantity by accident and prevents the user from scrolling the page.
        event.ignore()


class AspectRatioPreview(QLabel):
    """A 3:2 preview surface that always letterboxes the complete 60 x 40 label."""

    def __init__(self, text: str = "", parent=None, *, aspect_ratio: float = 1.5) -> None:
        super().__init__(text, parent)
        self._aspect_ratio = aspect_ratio
        self._source = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(280)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(186, round(max(1, width) / self._aspect_ratio))

    def sizeHint(self) -> QSize:
        return QSize(356, self.heightForWidth(356))

    def minimumSizeHint(self) -> QSize:
        return QSize(280, self.heightForWidth(280))

    def set_source_pixmap(self, pixmap: QPixmap) -> None:
        self._source = QPixmap(pixmap)
        self.setText("")
        self._sync_height()
        self._render_source()

    def clear_source(self) -> None:
        self._source = QPixmap()
        self.setPixmap(QPixmap())

    def _sync_height(self) -> None:
        desired = self.heightForWidth(self.contentsRect().width() or self.width())
        if self.height() != desired:
            self.setFixedHeight(desired)

    def _render_source(self) -> None:
        if self._source.isNull():
            return
        target = self.contentsRect().size()
        if target.width() <= 0 or target.height() <= 0:
            return
        rendered = self._source.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(rendered)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_height()
        self._render_source()
