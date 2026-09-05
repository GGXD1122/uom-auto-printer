from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QFrame, QListView, QStyle, QStyledItemDelegate, QVBoxLayout

from ..layout_template import (
    DEFAULT_PAPER_HEIGHT_MM,
    DEFAULT_PAPER_WIDTH_MM,
    PAPER_PRESETS,
    LayoutTemplate,
    load_layout_template,
)
from ..paths import layout_template_path


def paper_direction(width_mm: float, height_mm: float) -> str:
    if abs(width_mm - height_mm) < 0.01:
        return "正方形"
    return "横向" if width_mm > height_mm else "竖向"


class SmoothPresetListView(QListView):
    """Pixel-scrolling list with a short eased wheel animation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_animation.setDuration(150)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        bar = self.verticalScrollBar()
        delta = event.angleDelta().y()
        if not delta:
            super().wheelEvent(event)
            return
        target = max(bar.minimum(), min(bar.maximum(), bar.value() - int(delta * 0.72)))
        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()
        event.accept()


class PaperPresetDelegate(QStyledItemDelegate):
    """Compact, readable paper rows for the scrollable preset popup."""

    @staticmethod
    def display_texts(index) -> tuple[str, str]:
        data = index.data(Qt.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            return "", ""
        width_mm, height_mm = float(data[0]), float(data[1])
        preset_path = index.data(Qt.UserRole + 2)
        if preset_path:
            title = str(index.data(Qt.DisplayRole) or "我的预设").replace("  ▾", "").strip()
            return title, f"我的预设 · {width_mm:g} × {height_mm:g} mm"
        secondary = index.data(Qt.UserRole + 1) or paper_direction(width_mm, height_mm)
        return f"{width_mm:g} × {height_mm:g} mm", str(secondary)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt API
        return QSize(max(220, option.rect.width()), 58)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        selected = bool(option.state & QStyle.State_Selected)
        row = option.rect.adjusted(3, 2, -3, -2)
        painter.setPen(QPen(QColor("#a8bfff" if selected else "#e1e7ef"), 1.2))
        painter.setBrush(QColor("#edf3ff" if selected else "#ffffff"))
        painter.drawRoundedRect(row, 9, 9)

        data = index.data(Qt.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            painter.restore()
            return
        width_mm, height_mm = float(data[0]), float(data[1])

        icon_area = QRectF(row.left() + 10, row.top() + 8, 54, row.height() - 16)
        painter.setPen(QPen(QColor("#d4dde8"), 1))
        painter.setBrush(QColor("#f5f7fa"))
        painter.drawRoundedRect(icon_area, 8, 8)
        max_w, max_h = icon_area.width() - 14, icon_area.height() - 10
        ratio = width_mm / max(1.0, height_mm)
        paper_w = min(max_w, max_h * ratio)
        paper_h = paper_w / ratio
        if paper_h > max_h:
            paper_h = max_h
            paper_w = paper_h * ratio
        paper_rect = QRectF(
            icon_area.center().x() - paper_w / 2,
            icon_area.center().y() - paper_h / 2,
            paper_w,
            paper_h,
        )
        painter.setPen(QPen(QColor("#3563e9" if selected else "#7f8da1"), 1.5))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(paper_rect)

        title, secondary = self.display_texts(index)
        text_x = int(row.left() + 77)
        text_width = max(30, int(row.right() - text_x - 10))
        painter.setPen(QColor("#2555d9" if selected else "#17233a"))
        title_font = QFont(option.font)
        title_font.setPointSize(10)
        title_font.setBold(selected)
        painter.setFont(title_font)
        title = QFontMetrics(title_font).elidedText(title, Qt.ElideRight, text_width)
        painter.drawText(text_x, int(row.top() + 23), title)
        painter.setPen(QColor("#718096"))
        detail_font = QFont(option.font)
        detail_font.setPointSize(8)
        painter.setFont(detail_font)
        secondary = QFontMetrics(detail_font).elidedText(secondary, Qt.ElideRight, text_width)
        painter.drawText(text_x, int(row.top() + 43), secondary)
        painter.restore()


class RoundedPresetPopup(QFrame):
    """Frameless popup used instead of the platform's square combo window."""

    rowPressed = Signal(int)

    def __init__(self) -> None:
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("PaperPresetPopupWindow")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        self.list_view = SmoothPresetListView(self)
        self.list_view.setObjectName("PaperPresetPopup")
        self.list_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_view.pressed.connect(lambda index: self.rowPressed.emit(index.row()))
        layout.addWidget(self.list_view)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        # A translucent top-level popup does not reliably paint a stylesheet
        # background through Wine/Windows. Draw the opaque card ourselves so
        # the main window can never show through the gaps between rows.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
        painter.setPen(QPen(QColor("#cfd8e3"), 1.2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 13, 13)
        super().paintEvent(event)

    def apply_rounded_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 14, 14)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


class PaperPresetComboBox(QComboBox):
    """Shared paper selector with a constrained popup and custom presets."""

    paperChanged = Signal(float, float)

    def __init__(self, parent=None, *, template_path_override: Path | None = None) -> None:
        super().__init__(parent)
        self._template_path_override = template_path_override
        self.setObjectName("PaperPresetCombo")
        self.setMinimumWidth(174)
        self.setMaxVisibleItems(7)
        self._popup = RoundedPresetPopup()
        self._popup.list_view.setItemDelegate(PaperPresetDelegate(self._popup.list_view))
        self._popup.rowPressed.connect(self._popup_row_pressed)
        self.refresh_presets()
        self.currentIndexChanged.connect(self._emit_current_paper)

    def refresh_presets(self, selected_name: str | None = None, selected_file: str | None = None) -> None:
        current_size = self.current_paper() if self.count() else (DEFAULT_PAPER_WIDTH_MM, DEFAULT_PAPER_HEIGHT_MM)
        current_name = selected_name or self.currentText().replace("  ▾", "").strip()
        self.blockSignals(True)
        self.clear()
        for label, width, height in PAPER_PRESETS:
            self.addItem(f"{label}  ▾", (float(width), float(height)))
            index = self.count() - 1
            self.setItemData(index, paper_direction(width, height), Qt.UserRole + 1)
            self.setItemData(index, None, Qt.UserRole + 2)

        template_file = self._template_path_override or layout_template_path()
        preset_dir = template_file.parent / "layout-presets"
        if preset_dir.is_dir():
            for path in sorted(preset_dir.glob("*.json")):
                preset = load_layout_template(path)
                self.addItem(f"{preset.name}  ▾", (preset.paper_width_mm, preset.paper_height_mm))
                index = self.count() - 1
                self.setItemData(index, f"我的预设 · {preset.paper_width_mm:g} × {preset.paper_height_mm:g} mm", Qt.UserRole + 1)
                self.setItemData(index, str(path), Qt.UserRole + 2)

        selected_index = -1
        selected_basename = Path(selected_file).name if selected_file else ""
        if selected_basename:
            for index in range(self.count()):
                preset_path = self.itemData(index, Qt.UserRole + 2)
                if preset_path and Path(str(preset_path)).name == selected_basename:
                    selected_index = index
                    break
        if selected_index < 0:
            for index in range(self.count()):
                label = self.itemText(index).replace("  ▾", "").strip()
                if current_name and label == current_name:
                    selected_index = index
                    break
        if selected_index < 0:
            for index in range(self.count()):
                data = self.itemData(index)
                if isinstance(data, tuple) and abs(float(data[0]) - current_size[0]) < 0.01 and abs(float(data[1]) - current_size[1]) < 0.01:
                    selected_index = index
                    break
        self.setCurrentIndex(max(0, selected_index))
        self.blockSignals(False)

    def current_paper(self) -> tuple[float, float]:
        data = self.currentData()
        if isinstance(data, tuple) and len(data) == 2:
            return float(data[0]), float(data[1])
        return DEFAULT_PAPER_WIDTH_MM, DEFAULT_PAPER_HEIGHT_MM

    def current_preset_path(self) -> Path | None:
        value = self.currentData(Qt.UserRole + 2)
        return Path(value) if value else None

    def current_template(self) -> LayoutTemplate | None:
        path = self.current_preset_path()
        return load_layout_template(path) if path and path.is_file() else None

    def set_current_paper(
        self,
        width_mm: float,
        height_mm: float,
        preset_name: str | None = None,
        preset_file: str | None = None,
    ) -> None:
        if preset_name or preset_file:
            self.refresh_presets(preset_name, preset_file)
            current_path = self.current_preset_path()
            if preset_file and current_path is not None and current_path.name == Path(preset_file).name:
                return
            if preset_name and self.currentText().replace("  ▾", "").strip() == preset_name:
                return
        for index in range(self.count()):
            data = self.itemData(index)
            if not isinstance(data, tuple) or len(data) != 2:
                continue
            width, height = data
            if abs(float(width) - width_mm) < 0.01 and abs(float(height) - height_mm) < 0.01:
                self.blockSignals(True)
                self.setCurrentIndex(index)
                self.blockSignals(False)
                return

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        self._popup.list_view.setModel(self.model())
        self._popup.list_view.setCurrentIndex(self.model().index(self.currentIndex(), 0))
        self._place_popup_below()
        self._popup.apply_rounded_mask()
        self._popup.show()
        self._popup.raise_()
        self._popup.list_view.setFocus(Qt.PopupFocusReason)
        QTimer.singleShot(0, self._finish_popup_layout)

    def hidePopup(self) -> None:  # noqa: N802 - Qt API
        try:
            self._popup.hide()
        except RuntimeError:
            pass

    def _finish_popup_layout(self) -> None:
        if not self._popup.isVisible():
            return
        self._popup.list_view.scrollTo(
            self.model().index(self.currentIndex(), 0),
            QAbstractItemView.PositionAtCenter,
        )

    def _place_popup_below(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        anchor = self.mapToGlobal(QPoint(0, self.height() + 4))
        available_below = max(72, available.bottom() - anchor.y() - 8)
        content_height = self.count() * 58 + 12
        height = min(420, content_height, available_below)
        width = max(self.width(), 286)
        x = min(anchor.x(), available.right() - width)
        self._popup.setGeometry(max(available.left(), x), anchor.y(), width, height)

    def _popup_row_pressed(self, row: int) -> None:
        if not 0 <= row < self.count():
            return
        self._popup.hide()
        self.setCurrentIndex(row)

    def _emit_current_paper(self, _index: int) -> None:
        width, height = self.current_paper()
        self.paperChanged.emit(width, height)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        event.ignore()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        try:
            self._popup.close()
        except RuntimeError:
            pass
        super().closeEvent(event)
