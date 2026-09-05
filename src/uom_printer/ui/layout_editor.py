from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import qrcode
from PySide6.QtCore import QEvent, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QBrush,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..layout_template import (
    MAX_PAPER_HEIGHT_MM,
    MAX_PAPER_WIDTH_MM,
    MIN_ELEMENT_GAP_MM,
    MIN_PAPER_HEIGHT_MM,
    MIN_PAPER_WIDTH_MM,
    MIN_SAFE_QR_MM,
    MIN_TEXT_SIZE_MM,
    PAPER_PRESETS,
    LayoutElement,
    LayoutTemplate,
    default_layout_template,
    layout_issues,
    load_layout_template,
    rotate_layout,
    save_layout_template,
    scale_layout,
)
from ..label_renderer import render_custom_layout
from ..models import UomRecord
from ..paths import layout_template_path
from ..settings import AppSettings, SettingsStore
from .paper_selector import PaperPresetComboBox, PaperPresetDelegate
from .rounded_dialog import choose, confirm_danger, information, warning


class SmoothPresetListWidget(QListWidget):
    """Preset list with pixel scrolling and a short non-linear wheel glide."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_animation.setDuration(155)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        delta = event.angleDelta().y()
        if not delta:
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), bar.value() - int(delta * 0.72)))
        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()
        event.accept()


class RoundedNamePopup(QFrame):
    """Opaque rounded popup for the compact personal-preset selector."""

    row_pressed = Signal(int)

    def __init__(self) -> None:
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("NamedPresetPopupWindow")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        self.list_widget = SmoothPresetListWidget(self)
        self.list_widget.setObjectName("NamedPresetPopup")
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.itemPressed.connect(
            lambda item: self.row_pressed.emit(self.list_widget.row(item))
        )
        layout.addWidget(self.list_widget)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
        painter.setPen(QPen(QColor("#cfd8e3"), 1.2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 12, 12)
        super().paintEvent(event)

    def apply_rounded_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 13, 13)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


class RoundedNameComboBox(QComboBox):
    """Combo behavior without the platform-native square popup window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._popup = RoundedNamePopup()
        self._popup.row_pressed.connect(self._popup_row_pressed)

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        self._popup.list_widget.clear()
        for row in range(self.count()):
            item = QListWidgetItem(self.itemText(row))
            source_item = self.model().item(row)
            if source_item is not None and not source_item.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self._popup.list_widget.addItem(item)
        if self.count():
            self._popup.list_widget.setCurrentRow(self.currentIndex())
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        anchor = self.mapToGlobal(QPoint(0, self.height() + 4))
        width = max(220, self.width())
        height = min(280, max(54, self.count() * 38 + 10), max(54, available.bottom() - anchor.y() - 8))
        x = min(anchor.x(), available.right() - width)
        self._popup.setGeometry(max(available.left(), x), anchor.y(), width, height)
        self._popup.apply_rounded_mask()
        self._popup.show()
        self._popup.raise_()
        if self.count():
            self._popup.list_widget.scrollToItem(
                self._popup.list_widget.item(self.currentIndex()),
                QAbstractItemView.PositionAtCenter,
            )

    def hidePopup(self) -> None:  # noqa: N802 - Qt API
        self._popup.hide()

    def _popup_row_pressed(self, row: int) -> None:
        if not 0 <= row < self.count():
            return
        source_item = self.model().item(row)
        if source_item is not None and not source_item.isEnabled():
            return
        self._popup.hide()
        self.setCurrentIndex(row)
        self.activated.emit(row)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._popup.close()
        super().closeEvent(event)


class CommitSpinBox(QDoubleSpinBox):
    """Numeric field that commits typed text before an adjacent button runs."""

    def entered_value(self) -> float | None:
        """Read uncommitted editor text without QDoubleSpinBox silently clamping it."""
        text = self.lineEdit().text().strip()
        suffix = self.suffix().strip()
        if suffix and text.endswith(suffix):
            text = text[: -len(suffix)].strip()
        value, valid = self.locale().toDouble(text)
        if valid:
            return float(value)
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)


class ElementItem(QGraphicsRectItem):
    # Keep the whole hit target inside the element.  The previous handle was
    # drawn half outside the QR rectangle, exactly on top of the UAS-code row,
    # so the adjacent text item won the mouse press and resizing appeared dead.
    RESIZE_HANDLE_MM = 3.2

    def __init__(
        self,
        element: LayoutElement,
        moved_callback,
        allowed_bounds: QRectF,
        geometry_validator=None,
        collision_probe=None,
        drop_resolver=None,
    ) -> None:
        super().__init__(0, 0, element.width_mm, element.height_mm)
        self.element = element
        self.moved_callback = moved_callback
        self.setPos(element.x_mm, element.y_mm)
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setCursor(Qt.OpenHandCursor)
        self.setAcceptHoverEvents(True)
        self._resizing = False
        self._resize_start = QPointF()
        self._resize_start_size = (element.width_mm, element.height_mm)
        self.allowed_bounds = QRectF(allowed_bounds)
        self.resize_enabled = True
        self.resize_bottom_reserve_mm = 0.0
        self.geometry_validator = geometry_validator
        self.collision_probe = collision_probe
        self.drop_resolver = drop_resolver
        self._syncing = False
        self._dragging = False
        self._drag_start_position = QPointF(self.pos())
        self._collision_active = False
        self.setOpacity(1.0 if element.visible else 0.0)

    def configure_interaction(self, *, movable: bool = True, resizable: bool = True, bottom_reserve_mm: float = 0.0) -> None:
        self.setFlag(QGraphicsItem.ItemIsMovable, movable)
        self.resize_enabled = resizable
        self.resize_bottom_reserve_mm = max(0.0, float(bottom_reserve_mm))

    def _on_resize_handle(self, point: QPointF) -> bool:
        handle = self.RESIZE_HANDLE_MM
        rect = self.rect()
        return self.resize_enabled and QRectF(rect.right() - handle, rect.bottom() - handle, handle, handle).contains(point)

    def hoverMoveEvent(self, event) -> None:
        self.setCursor(Qt.SizeFDiagCursor if self._on_resize_handle(event.pos()) else Qt.OpenHandCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._on_resize_handle(event.pos()):
            self.setSelected(True)
            self._resizing = True
            self._resize_start = event.scenePos()
            self._resize_start_size = (self.element.width_mm, self.element.height_mm)
            self.setCursor(Qt.SizeFDiagCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton and bool(self.flags() & QGraphicsItem.ItemIsMovable):
            self._dragging = True
            self._drag_start_position = QPointF(self.pos())
            self._collision_active = False
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._resizing:
            super().mouseMoveEvent(event)
            if self._dragging and self.collision_probe is not None:
                collision_active = bool(
                    self.collision_probe(
                        self,
                        self.pos().x(),
                        self.pos().y(),
                        self.rect().width(),
                        self.rect().height(),
                    )
                )
                if collision_active != self._collision_active:
                    self._collision_active = collision_active
                    self.update()
            return
        delta = event.scenePos() - self._resize_start
        minimum = MIN_SAFE_QR_MM if self.element.kind == "qr" else 1.0
        maximum_width = max(minimum, self.allowed_bounds.right() - self.pos().x())
        maximum_height = max(
            minimum,
            self.allowed_bounds.bottom() - self.pos().y() - self.resize_bottom_reserve_mm,
        )
        width = max(minimum, min(maximum_width, self._resize_start_size[0] + delta.x()))
        height = max(minimum, min(maximum_height, self._resize_start_size[1] + delta.y()))
        if self.element.lock_aspect:
            side = max(minimum, min(width, height, maximum_width, maximum_height))
            width = height = side
        if self.geometry_validator is not None and not self.geometry_validator(
            self,
            self.pos().x(),
            self.pos().y(),
            width,
            height,
        ):
            event.accept()
            return
        self.element.width_mm = round(width, 2)
        self.element.height_mm = round(height, 2)
        self.setRect(0, 0, self.element.width_mm, self.element.height_mm)
        self.moved_callback(self)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing:
            self._resizing = False
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        was_dragging = self._dragging
        desired_position = QPointF(self.pos())
        super().mouseReleaseEvent(event)
        if was_dragging:
            self._dragging = False
            resolved_position = desired_position
            if self.drop_resolver is not None:
                resolved_position = self.drop_resolver(
                    self,
                    desired_position,
                    self._drag_start_position,
                )
            if resolved_position != desired_position:
                self._syncing = True
                self.setPos(resolved_position)
                self._syncing = False
            self._collision_active = False
            self.setCursor(Qt.OpenHandCursor)
            self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            point = value if isinstance(value, QPointF) else QPointF(value)
            bounds = self.allowed_bounds
            x = max(bounds.left(), min(point.x(), bounds.right() - self.rect().width()))
            y = max(
                bounds.top(),
                min(point.y(), bounds.bottom() - self.rect().height() - self.resize_bottom_reserve_mm),
            )
            candidate = QPointF(x, y)
            if (
                not self._syncing
                and not self._dragging
                and self.geometry_validator is not None
                and not self.geometry_validator(
                    self,
                    candidate.x(),
                    candidate.y(),
                    self.rect().width(),
                    self.rect().height(),
                )
            ):
                return self.pos()
            return candidate
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.element.x_mm = round(self.pos().x(), 2)
            self.element.y_mm = round(self.pos().y(), 2)
            self.moved_callback(self)
        return super().itemChange(change, value)

    def sync_geometry(self) -> None:
        self._syncing = True
        self.prepareGeometryChange()
        self.setRect(0, 0, self.element.width_mm, self.element.height_mm)
        self.setPos(self.element.x_mm, self.element.y_mm)
        self._syncing = False
        self.setOpacity(1.0 if self.element.visible else (0.28 if self.isSelected() else 0.0))
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        selected = self.isSelected()
        color = QColor("#e5484d" if self._collision_active else ("#3563e9" if selected else "#8da6cf"))
        painter.setPen(QPen(color, 0, Qt.DashLine))
        painter.setBrush(
            QBrush(
                QColor(229, 72, 77, 32)
                if self._collision_active
                else (QColor(53, 99, 233, 18) if selected else QColor(141, 166, 207, 12))
            )
        )
        painter.drawRoundedRect(self.rect(), 0.7, 0.7)
        if selected and self.resize_enabled:
            painter.setBrush(QBrush(QColor("white")))
            painter.setPen(QPen(QColor("#e5484d" if self._collision_active else "#3563e9"), 0))
            size = 2.7
            inset = 0.22
            rect = self.rect()
            painter.drawRoundedRect(
                QRectF(rect.right() - size - inset, rect.bottom() - size - inset, size, size),
                0.55,
                0.55,
            )


class LayoutCanvas(QGraphicsView):
    selected = Signal(object)
    geometry_changed = Signal(object)
    collision_blocked = Signal(str)
    collision_resolved = Signal(str)

    DEMO_RECORD = UomRecord(
        "UAS-DEMO-2026-000001",
        "DJI Air 3S 畅飞套装（DJI RC 2）",
        "1581FDEMO00000000001",
        "演示用户",
        phone_number="13800000000",
        empty_weight="724 g",
        product_model="CZ3SCLV",
        manufacturer="深圳市大疆创新科技有限公司",
        status="正常",
        maximum_takeoff_weight="1420 g",
        registration_time="2026-07-25 09:30:00",
        owner_type="个人",
        qr_payload="https://example.invalid/uom-demo",
    )
    _demo_qr = None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.canvas_scene = QGraphicsScene(self)
        self.setScene(self.canvas_scene)
        self.setBackgroundBrush(QColor("#e9eef5"))
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("LayoutCanvas")
        self.items_by_id: dict[str, ElementItem] = {}
        self.grid_items: list[QGraphicsItem] = []
        self.grid_visible = False
        self.preview_item: QGraphicsPixmapItem | None = None
        self.loaded_template: LayoutTemplate | None = None
        self.loaded_kind = "info"
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(18)
        self._preview_timer.timeout.connect(self.refresh_demo_preview)
        self.canvas_scene.selectionChanged.connect(self._selection_changed)

    @classmethod
    def demo_qr(cls):
        if cls._demo_qr is None:
            code = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=8, border=4)
            code.add_data(cls.DEMO_RECORD.qr_payload)
            code.make(fit=True)
            cls._demo_qr = code.make_image(fill_color="black", back_color="white").convert("RGB")
        return cls._demo_qr

    def load(self, template: LayoutTemplate, template_kind: str) -> None:
        # Clearing a QGraphicsScene emits selectionChanged before the Python
        # lookup is rebuilt. Release Python wrappers before Qt deletes their
        # C++ objects; otherwise Shiboken can reuse a stale wrapper when a
        # preset is switched repeatedly on Windows.
        self._preview_timer.stop()
        self.canvas_scene.blockSignals(True)
        self.items_by_id.clear()
        self.grid_items.clear()
        self.preview_item = None
        self.canvas_scene.clear()
        self.loaded_template = template
        self.loaded_kind = template_kind
        width, height = template.paper_width_mm, template.paper_height_mm
        self.canvas_scene.setSceneRect(0, 0, width, height)
        # Construct graphics items explicitly instead of using QGraphicsScene's
        # addRect/addLine convenience wrappers.  PySide can occasionally reuse
        # a stale wrapper after rapid scene clears, which makes addRect return
        # an unrelated Qt item type and crashes repeated preset switching.
        paper = QGraphicsRectItem(QRectF(0, 0, width, height))
        paper.setPen(QPen(QColor("#8391a5"), 0.18))
        paper.setBrush(QBrush(QColor("white")))
        paper.setZValue(-20)
        self.canvas_scene.addItem(paper)
        self.preview_item = QGraphicsPixmapItem()
        self.preview_item.setZValue(-19)
        self.canvas_scene.addItem(self.preview_item)
        grid_pen = QPen(QColor("#edf1f5"), 0)
        for x in range(5, int(width), 5):
            line = QGraphicsLineItem(x, 0, x, height)
            line.setPen(grid_pen)
            line.setZValue(-15)
            line.setVisible(self.grid_visible)
            self.canvas_scene.addItem(line)
            self.grid_items.append(line)
        for y in range(5, int(height), 5):
            line = QGraphicsLineItem(0, y, width, y)
            line.setPen(grid_pen)
            line.setZValue(-15)
            line.setVisible(self.grid_visible)
            self.canvas_scene.addItem(line)
            self.grid_items.append(line)
        margin = template.safe_margin_mm
        safe_bounds = QRectF(margin, margin, width - margin * 2, height - margin * 2)
        safe = QGraphicsRectItem(safe_bounds)
        safe.setPen(QPen(QColor("#21b573"), 0, Qt.DashLine))
        safe.setZValue(-10)
        self.canvas_scene.addItem(safe)
        for element in template.elements(template_kind):
            item = ElementItem(
                element,
                self._item_moved,
                safe_bounds,
                self._can_place_item,
                self._candidate_has_collision,
                self._resolve_drop_position,
            )
            self.canvas_scene.addItem(item)
            self.items_by_id[element.id] = item
        self.canvas_scene.blockSignals(False)
        self.refresh_demo_preview()
        self.fit_canvas()

    def set_grid_visible(self, visible: bool) -> None:
        self.grid_visible = bool(visible)
        for item in self.grid_items:
            item.setVisible(self.grid_visible)

    def refresh_demo_preview(self) -> None:
        if self.loaded_template is None or self.preview_item is None:
            return
        rendered = render_custom_layout(
            self.demo_qr(),
            self.DEMO_RECORD,
            self.loaded_template,
            self.loaded_kind,
            dpi=203,
        ).convert("RGBA")
        raw = rendered.tobytes("raw", "RGBA")
        image = QImage(raw, rendered.width, rendered.height, QImage.Format_RGBA8888).copy()
        pixmap = QPixmap.fromImage(image)
        self.preview_item.setPixmap(pixmap)
        self.preview_item.setTransform(
            QTransform.fromScale(
                self.loaded_template.paper_width_mm / max(1, pixmap.width()),
                self.loaded_template.paper_height_mm / max(1, pixmap.height()),
            )
        )

    def schedule_demo_preview(self) -> None:
        self._preview_timer.start()

    def fit_canvas(self) -> None:
        self.fitInView(self.canvas_scene.sceneRect().adjusted(-0.35, -0.35, 0.35, 0.35), Qt.KeepAspectRatio)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_canvas()

    def select_element(self, element_id: str) -> None:
        self.select_elements((element_id,))

    def select_elements(self, element_ids: tuple[str, ...], *, emit: bool = True) -> None:
        items = [self.items_by_id[element_id] for element_id in element_ids if element_id in self.items_by_id]
        self.canvas_scene.blockSignals(True)
        self.canvas_scene.clearSelection()
        for existing in self.items_by_id.values():
            existing.setOpacity(1.0 if existing.element.visible else 0.0)
        for item in items:
            item.setSelected(True)
            if not item.element.visible:
                item.setOpacity(0.28)
        self.canvas_scene.blockSignals(False)
        if items:
            bounds = items[0].sceneBoundingRect()
            for item in items[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            self.centerOn(bounds.center())
        if emit:
            self.selected.emit(items[0] if items else None)

    def _selection_changed(self) -> None:
        selected = self.canvas_scene.selectedItems()
        selected_set = set(selected)
        for item in self.items_by_id.values():
            item.setOpacity(1.0 if item.element.visible else (0.28 if item in selected_set else 0.0))
        self.selected.emit(selected[0] if selected else None)

    def _item_moved(self, item: ElementItem) -> None:
        self.schedule_demo_preview()
        self.geometry_changed.emit(item)
        if item.isSelected():
            self.selected.emit(item)

    @staticmethod
    def element_group(element_id: str) -> tuple[str, ...]:
        if element_id in ("info_qr_2", "info_uas_2"):
            return ("info_qr_2", "info_uas_2")
        if element_id.startswith("qr_") or element_id.startswith("uas_"):
            suffix = element_id.rsplit("_", 1)[-1]
            return (f"qr_{suffix}", f"uas_{suffix}")
        if element_id in ("info_qr", "info_uas"):
            return ("info_qr", "info_uas")
        return (element_id,)

    @staticmethod
    def _rect_for(element: LayoutElement) -> QRectF:
        return QRectF(element.x_mm, element.y_mm, element.width_mm, element.height_mm)

    @staticmethod
    def _collision_area(first: QRectF, second: QRectF) -> float:
        expanded = first.adjusted(
            -MIN_ELEMENT_GAP_MM,
            -MIN_ELEMENT_GAP_MM,
            MIN_ELEMENT_GAP_MM,
            MIN_ELEMENT_GAP_MM,
        )
        overlap = expanded.intersected(second)
        return max(0.0, overlap.width()) * max(0.0, overlap.height())

    def _visible_elements(self) -> list[LayoutElement]:
        if self.loaded_template is None:
            return []
        return [element for element in self.loaded_template.elements(self.loaded_kind) if element.visible]

    def _group_candidate_rects(
        self,
        item: ElementItem,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> tuple[set[str], dict[str, QRectF]]:
        group_ids = set(self.element_group(item.element.id))
        lookup = {element.id: element for element in self._visible_elements()}
        candidates = {
            element_id: self._rect_for(lookup[element_id])
            for element_id in group_ids
            if element_id in lookup
        }
        candidates[item.element.id] = QRectF(x, y, width, height)
        if item.element.kind == "qr" and len(group_ids) > 1:
            code = next(
                (lookup[element_id] for element_id in group_ids if element_id in lookup and lookup[element_id].kind == "text"),
                None,
            )
            if code is not None:
                candidates[code.id] = QRectF(x, y + height, width, code.height_mm)
        return group_ids, candidates

    def _candidate_collision_score(self, item: ElementItem, x: float, y: float, width: float, height: float) -> float:
        if not item.element.visible:
            return 0.0
        group_ids, candidates = self._group_candidate_rects(item, x, y, width, height)
        others = [element for element in self._visible_elements() if element.id not in group_ids]
        return sum(
            self._collision_area(candidate, self._rect_for(other))
            for candidate in candidates.values()
            for other in others
        )

    def _candidate_has_collision(self, item: ElementItem, x: float, y: float, width: float, height: float) -> bool:
        return self._candidate_collision_score(item, x, y, width, height) > 0.0001

    def _can_place_item(self, item: ElementItem, x: float, y: float, width: float, height: float) -> bool:
        candidate_score = self._candidate_collision_score(item, x, y, width, height)
        group_ids = self.element_group(item.element.id)
        current_score = self.group_collision_score(tuple(group_ids))
        if candidate_score > 0.0001 and candidate_score >= current_score - 0.0001:
            self.collision_blocked.emit("已碰到其他元素，不能继续移动或放大。")
            return False
        return True

    def _resolve_drop_position(self, item: ElementItem, desired: QPointF, start: QPointF) -> QPointF:
        width = item.rect().width()
        height = item.rect().height()
        if not self._candidate_has_collision(item, desired.x(), desired.y(), width, height):
            return desired

        bounds = item.allowed_bounds
        max_x = bounds.right() - width
        max_y = bounds.bottom() - height - item.resize_bottom_reserve_mm
        candidates: dict[tuple[float, float], QPointF] = {}

        def add_candidate(x: float, y: float) -> None:
            x = round(max(bounds.left(), min(float(x), max_x)), 2)
            y = round(max(bounds.top(), min(float(y), max_y)), 2)
            candidates[(x, y)] = QPointF(x, y)

        add_candidate(desired.x(), desired.y())
        add_candidate(start.x(), start.y())
        group_ids = set(self.element_group(item.element.id))
        others = [element for element in self._visible_elements() if element.id not in group_ids]
        group_height = height + item.resize_bottom_reserve_mm
        gap = MIN_ELEMENT_GAP_MM
        for other in others:
            other_rect = self._rect_for(other)
            left_x = other_rect.left() - width - gap
            right_x = other_rect.right() + gap
            above_y = other_rect.top() - group_height - gap
            below_y = other_rect.bottom() + gap
            for x in (left_x, right_x):
                add_candidate(x, desired.y())
                add_candidate(x, above_y)
                add_candidate(x, below_y)
            for y in (above_y, below_y):
                add_candidate(desired.x(), y)

        step = 0.5
        max_radius = max(12.0, min(max(bounds.width(), bounds.height()), max(width, group_height) + 5.0))
        rings = max(1, int(max_radius / step))
        for ring in range(1, rings + 1):
            distance = ring * step
            for offset in range(-ring, ring + 1):
                delta = offset * step
                add_candidate(desired.x() + delta, desired.y() - distance)
                add_candidate(desired.x() + delta, desired.y() + distance)
                add_candidate(desired.x() - distance, desired.y() + delta)
                add_candidate(desired.x() + distance, desired.y() + delta)

        move_x = desired.x() - start.x()
        move_y = desired.y() - start.y()
        move_length_sq = move_x * move_x + move_y * move_y
        dominant_axis = "x" if abs(move_x) > abs(move_y) else "y"

        def rank(point: QPointF) -> tuple[float, float, float]:
            distance = (point.x() - desired.x()) ** 2 + (point.y() - desired.y()) ** 2
            progress = (point.x() - start.x()) * move_x + (point.y() - start.y()) * move_y
            if move_length_sq <= 0.0001:
                return 0.0, distance, 0.0
            axis_progress = (
                (point.x() - start.x()) * move_x
                if dominant_axis == "x"
                else (point.y() - start.y()) * move_y
            )
            direction_penalty = max(0.0, move_length_sq - progress)
            if axis_progress < 0.0:
                direction_penalty += move_length_sq
            return direction_penalty, distance, -progress

        ordered = sorted(candidates.values(), key=rank)
        for point in ordered:
            if not self._candidate_has_collision(item, point.x(), point.y(), width, height):
                self.collision_resolved.emit("已自动避开重叠，放到目标附近的空位。")
                return point

        start_score = self._candidate_collision_score(item, start.x(), start.y(), width, height)
        best = min(
            ordered,
            key=lambda point: (
                self._candidate_collision_score(item, point.x(), point.y(), width, height),
                *rank(point),
            ),
        )
        best_score = self._candidate_collision_score(item, best.x(), best.y(), width, height)
        if best_score + 0.0001 < start_score:
            self.collision_resolved.emit("已移动到重叠更少的位置，可继续拖动调整。")
            return best
        self.collision_blocked.emit("附近没有可用空位，已回到拖动前的位置。")
        return start

    def group_collision_score(self, element_ids: tuple[str, ...]) -> float:
        target_ids = set(element_ids)
        visible = self._visible_elements()
        targets = [element for element in visible if element.id in target_ids]
        others = [element for element in visible if element.id not in target_ids]
        return sum(
            self._collision_area(self._rect_for(target), self._rect_for(other))
            for target in targets
            for other in others
        )

    def group_has_collision(self, element_ids: tuple[str, ...]) -> bool:
        return self.group_collision_score(element_ids) > 0.0001


class LayoutEditorDialog(QDialog):
    settings_saved = Signal(object)
    preview_template_changed = Signal(object)

    def __init__(self, settings: AppSettings, store: SettingsStore, parent=None, *, template_path: Path | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.store = store
        self.template_path = template_path or layout_template_path()
        self.preset_dir = self.template_path.parent / "layout-presets"
        self.template = load_layout_template(self.template_path)
        self.current_kind = "info"
        self.current_item: ElementItem | None = None
        self.current_group_ids: tuple[str, ...] = ()
        self._updating = False
        self._paper_change_generation = 0
        self.setWindowTitle("调整标签")
        self.setObjectName("LayoutEditorDialog")
        self.resize(1320, 820)
        self.setMinimumSize(1080, 700)
        self._build_ui()
        self._load_template_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.addWidget(QLabel("自定义排版", objectName="SectionTitle"))
        note = QLabel("拖动元素即可排版；常用调整直接点按钮，精确毫米参数按需展开。二维码低于18mm时禁止保存。", objectName="Subtitle")
        note.setWordWrap(True)
        title_box.addWidget(note)
        header.addLayout(title_box, 1)
        self.enabled = QCheckBox("启用当前自定义模板")
        self.enabled.setChecked(self.settings.custom_layout_enabled)
        header.addWidget(self.enabled)
        root.addLayout(header)

        preset_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：维修台 50×40")
        preset_row.addWidget(QLabel("预设名称"))
        preset_row.addWidget(self.name_edit, 1)
        self.save_preset_button = QPushButton("保存为我的预设")
        self.save_preset_button.setObjectName("LayoutPresetButton")
        self.save_preset_button.clicked.connect(self._save_named_preset)
        preset_row.addWidget(self.save_preset_button)
        self.saved_preset_combo = QComboBox()
        self.saved_preset_combo.setMinimumWidth(170)
        self.saved_preset_combo.activated.connect(self._named_preset_changed)
        preset_row.addWidget(self.saved_preset_combo)
        root.addLayout(preset_row)

        toolbar = QHBoxLayout()
        self.paper_combo = QComboBox()
        for label, width, height in PAPER_PRESETS:
            self.paper_combo.addItem(label, (width, height))
        self.paper_combo.addItem("自定义尺寸", None)
        self.paper_combo.currentIndexChanged.connect(self._preset_changed)
        toolbar.addWidget(QLabel("纸张尺寸"))
        toolbar.addWidget(self.paper_combo)
        self.width_spin = self._spin(MIN_PAPER_WIDTH_MM, MAX_PAPER_WIDTH_MM, " mm")
        self.height_spin = self._spin(MIN_PAPER_HEIGHT_MM, MAX_PAPER_HEIGHT_MM, " mm")
        self.width_spin.editingFinished.connect(self._custom_paper_changed)
        self.height_spin.editingFinished.connect(self._custom_paper_changed)
        toolbar.addWidget(self.width_spin)
        toolbar.addWidget(QLabel("×"))
        toolbar.addWidget(self.height_spin)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("实名双码标签", "qr")
        self.kind_combo.addItem("设备信息标签", "info")
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        toolbar.addWidget(self.kind_combo)
        rotate_all = QPushButton("整版旋转90°")
        rotate_all.setObjectName("LayoutPresetButton")
        rotate_all.setToolTip("交换纸张宽高，并旋转全部元素和文字")
        rotate_all.clicked.connect(self._rotate_whole_layout)
        toolbar.addWidget(rotate_all)
        toolbar.addStretch()
        root.addLayout(toolbar)

        splitter = QSplitter()
        self.canvas = LayoutCanvas()
        self.canvas.selected.connect(self._canvas_selected)
        splitter.addWidget(self.canvas)
        panel = QWidget()
        panel.setObjectName("LayoutInspector")
        panel.setMinimumWidth(330)
        panel.setMaximumWidth(390)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 6, 4, 6)
        panel_layout.addWidget(QLabel("元素列表", objectName="SectionTitle"))
        self.element_list = QListWidget()
        self.element_list.setObjectName("LayoutElementList")
        self.element_list.currentItemChanged.connect(self._list_selected)
        panel_layout.addWidget(self.element_list, 1)
        self.selected_title = QLabel("选中元素", objectName="SectionTitle")
        panel_layout.addWidget(self.selected_title)

        quick_card = QFrame(objectName="LayoutQuickControls")
        quick_layout = QVBoxLayout(quick_card)
        quick_layout.setContentsMargins(10, 9, 10, 10)
        quick_layout.setSpacing(8)
        move_row = QHBoxLayout()
        move_row.addWidget(QLabel("位置"))
        move_row.addStretch()
        for text, dx, dy in (("←", -0.5, 0), ("↑", 0, -0.5), ("↓", 0, 0.5), ("→", 0.5, 0)):
            button = self._quick_button(text)
            button.setToolTip(f"移动 0.5 mm")
            button.clicked.connect(lambda _checked=False, x=dx, y=dy: self._nudge_selected(x, y))
            move_row.addWidget(button)
        quick_layout.addLayout(move_row)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("元素大小"))
        size_row.addStretch()
        smaller = self._quick_button("−  缩小", wide=True)
        larger = self._quick_button("＋  放大", wide=True)
        smaller.clicked.connect(lambda: self._resize_selected(-0.5))
        larger.clicked.connect(lambda: self._resize_selected(0.5))
        size_row.addWidget(smaller)
        size_row.addWidget(larger)
        rotate_selected = self._quick_button("↻  旋转", wide=True)
        rotate_selected.setToolTip("旋转选中元素90°")
        rotate_selected.clicked.connect(self._rotate_selected)
        size_row.addWidget(rotate_selected)
        quick_layout.addLayout(size_row)

        font_row = QHBoxLayout()
        self.font_quick_label = QLabel("文字大小")
        font_row.addWidget(self.font_quick_label)
        font_row.addStretch()
        self.font_smaller = self._quick_button("A−", wide=True)
        self.font_larger = self._quick_button("A＋", wide=True)
        self.font_smaller.clicked.connect(lambda: self._change_font(-0.2))
        self.font_larger.clicked.connect(lambda: self._change_font(0.2))
        font_row.addWidget(self.font_smaller)
        font_row.addWidget(self.font_larger)
        quick_layout.addLayout(font_row)
        panel_layout.addWidget(quick_card)

        self.advanced_toggle = QPushButton("精确调整  ▾")
        self.advanced_toggle.setObjectName("LayoutAdvancedToggle")
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        panel_layout.addWidget(self.advanced_toggle)
        self.advanced_panel = QFrame(objectName="LayoutAdvancedPanel")
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(9, 8, 9, 8)
        form = QFormLayout()
        self.x_spin = self._spin(0.0, 300.0, " mm")
        self.y_spin = self._spin(0.0, 300.0, " mm")
        self.w_spin = self._spin(1.0, 300.0, " mm")
        self.h_spin = self._spin(1.0, 300.0, " mm")
        self.font_spin = self._spin(MIN_TEXT_SIZE_MM, 20.0, " mm")
        self.align_combo = QComboBox()
        self.align_combo.addItem("左对齐", "left")
        self.align_combo.addItem("居中", "center")
        self.align_combo.addItem("右对齐", "right")
        self.visible_check = QCheckBox("显示这个元素")
        self.lock_check = QCheckBox("保持等比例")
        for spin in (self.x_spin, self.y_spin, self.w_spin, self.h_spin, self.font_spin):
            spin.valueChanged.connect(self._property_changed)
        self.align_combo.currentIndexChanged.connect(self._property_changed)
        self.visible_check.toggled.connect(self._property_changed)
        self.lock_check.toggled.connect(self._property_changed)
        form.addRow("X 坐标", self.x_spin)
        form.addRow("Y 坐标", self.y_spin)
        form.addRow("宽度", self.w_spin)
        form.addRow("高度", self.h_spin)
        form.addRow("文字大小", self.font_spin)
        form.addRow("文字对齐", self.align_combo)
        form.addRow("", self.visible_check)
        form.addRow("", self.lock_check)
        advanced_layout.addLayout(form)
        self.advanced_panel.setVisible(False)
        panel_layout.addWidget(self.advanced_panel)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 1)
        root.addWidget(splitter, 1)

        actions = QHBoxLayout()
        reset = QPushButton("恢复当前纸张安全预设")
        reset.clicked.connect(self._reset_preset)
        actions.addWidget(reset)
        actions.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存模板并应用")
        save.setObjectName("Accent")
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

    @staticmethod
    def _spin(minimum: float, maximum: float, suffix: str) -> QDoubleSpinBox:
        spin = CommitSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setAlignment(Qt.AlignCenter)
        return spin

    @staticmethod
    def _quick_button(text: str, *, wide: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("LayoutQuickButton")
        button.setFixedHeight(32)
        button.setMinimumWidth(76 if wide else 36)
        return button

    def _load_template_ui(self) -> None:
        self._updating = True
        self.name_edit.setText(self.template.name)
        self.width_spin.setValue(self.template.paper_width_mm)
        self.height_spin.setValue(self.template.paper_height_mm)
        matched = False
        for index in range(self.paper_combo.count() - 1):
            width, height = self.paper_combo.itemData(index)
            if abs(width - self.template.paper_width_mm) < 0.01 and abs(height - self.template.paper_height_mm) < 0.01:
                self.paper_combo.setCurrentIndex(index)
                matched = True
                break
        if not matched:
            self.paper_combo.setCurrentIndex(self.paper_combo.count() - 1)
        self._updating = False
        self._refresh_named_presets(self.template.name)
        self._reload_kind()

    def _reload_kind(self) -> None:
        self.current_kind = self.kind_combo.currentData() or "qr"
        self.canvas.load(self.template, self.current_kind)
        self.element_list.clear()
        for element in self.template.elements(self.current_kind):
            item = QListWidgetItem(element.label)
            item.setData(Qt.UserRole, element.id)
            self.element_list.addItem(item)
        if self.element_list.count():
            self.element_list.setCurrentRow(0)

    def _preset_changed(self, _index: int) -> None:
        if self._updating:
            return
        data = self.paper_combo.currentData()
        if data is None:
            return
        width, height = data
        self.template = default_layout_template(width, height)
        self.template.name = f"{int(width)}×{int(height)} 安全预设"
        self._load_template_ui()
        self.preview_template_changed.emit(deepcopy(self.template))

    def _custom_paper_changed(self) -> None:
        if self._updating:
            return
        width, height = self.width_spin.value(), self.height_spin.value()
        scale_layout(self.template, width, height)
        self.paper_combo.blockSignals(True)
        self.paper_combo.setCurrentIndex(self.paper_combo.count() - 1)
        self.paper_combo.blockSignals(False)
        self._reload_kind()
        self.preview_template_changed.emit(deepcopy(self.template))

    def _kind_changed(self, _index: int) -> None:
        if not self._updating:
            self._reload_kind()

    def _list_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if current is not None:
            self.canvas.select_element(str(current.data(Qt.UserRole)))

    def _canvas_selected(self, item) -> None:
        self.current_item = item if isinstance(item, ElementItem) else None
        if self.current_item is None:
            return
        element = self.current_item.element
        rotation_text = f" · {int(element.rotation_deg) % 360}°" if element.rotation_deg else ""
        self.selected_title.setText(f"已选择：{element.label}{rotation_text}")
        self._updating = True
        self.x_spin.setValue(element.x_mm)
        self.y_spin.setValue(element.y_mm)
        self.w_spin.setMinimum(MIN_SAFE_QR_MM if element.kind == "qr" else 1.0)
        self.h_spin.setMinimum(MIN_SAFE_QR_MM if element.kind == "qr" else 1.0)
        self.w_spin.setValue(element.width_mm)
        self.h_spin.setValue(element.height_mm)
        self.font_spin.setValue(max(MIN_TEXT_SIZE_MM, element.font_size_mm))
        align_index = self.align_combo.findData(element.align)
        self.align_combo.setCurrentIndex(max(0, align_index))
        self.visible_check.setChecked(element.visible)
        self.lock_check.setChecked(element.lock_aspect)
        self.font_spin.setEnabled(element.kind == "text")
        self.align_combo.setEnabled(element.kind == "text")
        self.lock_check.setEnabled(element.kind == "qr")
        self.font_smaller.setEnabled(element.kind == "text")
        self.font_larger.setEnabled(element.kind == "text")
        self.font_quick_label.setEnabled(element.kind == "text")
        self._updating = False
        matches = self.element_list.findItems(element.label, Qt.MatchExactly)
        if matches and self.element_list.currentItem() is not matches[0]:
            self.element_list.blockSignals(True)
            self.element_list.setCurrentItem(matches[0])
            self.element_list.blockSignals(False)

    def _property_changed(self, *_args) -> None:
        if self._updating or self.current_item is None:
            return
        element = self.current_item.element
        element.x_mm = self.x_spin.value()
        element.y_mm = self.y_spin.value()
        element.width_mm = self.w_spin.value()
        element.height_mm = self.h_spin.value()
        element.font_size_mm = self.font_spin.value()
        element.align = str(self.align_combo.currentData() or "center")
        element.visible = self.visible_check.isChecked()
        element.lock_aspect = self.lock_check.isChecked() if element.kind == "qr" else False
        if element.lock_aspect and abs(element.width_mm - element.height_mm) > 0.01:
            element.height_mm = element.width_mm
            self._updating = True
            self.h_spin.setValue(element.height_mm)
            self._updating = False
        margin = self.template.safe_margin_mm
        element.x_mm = max(margin, min(element.x_mm, self.template.paper_width_mm - margin - element.width_mm))
        element.y_mm = max(margin, min(element.y_mm, self.template.paper_height_mm - margin - element.height_mm))
        self.current_item.sync_geometry()
        self.canvas.schedule_demo_preview()

    def _sync_selected_item(self) -> None:
        if self.current_item is None:
            return
        self.current_item.sync_geometry()
        self.canvas.schedule_demo_preview()
        self._canvas_selected(self.current_item)

    def _nudge_selected(self, dx: float, dy: float) -> None:
        if self.current_item is None:
            return
        element = self.current_item.element
        margin = self.template.safe_margin_mm
        element.x_mm = max(margin, min(element.x_mm + dx, self.template.paper_width_mm - margin - element.width_mm))
        element.y_mm = max(margin, min(element.y_mm + dy, self.template.paper_height_mm - margin - element.height_mm))
        self._sync_selected_item()

    def _resize_selected(self, delta: float) -> None:
        if self.current_item is None:
            return
        element = self.current_item.element
        minimum = MIN_SAFE_QR_MM if element.kind == "qr" else 1.0
        margin = self.template.safe_margin_mm
        max_width = self.template.paper_width_mm - margin - element.x_mm
        max_height = self.template.paper_height_mm - margin - element.y_mm
        if element.lock_aspect or element.kind == "qr":
            side = max(minimum, min(element.width_mm + delta, max_width, max_height))
            element.width_mm = element.height_mm = side
        else:
            element.width_mm = max(minimum, min(element.width_mm + delta, max_width))
            element.height_mm = max(minimum, min(element.height_mm + delta, max_height))
        self._sync_selected_item()

    def _change_font(self, delta: float) -> None:
        if self.current_item is None or self.current_item.element.kind != "text":
            return
        element = self.current_item.element
        element.font_size_mm = max(MIN_TEXT_SIZE_MM, min(20.0, element.font_size_mm + delta))
        self._sync_selected_item()

    def _rotate_selected(self) -> None:
        if self.current_item is None:
            return
        element = self.current_item.element
        element.rotation_deg = (int(element.rotation_deg) + 90) % 360
        if element.kind == "text":
            element.width_mm, element.height_mm = element.height_mm, element.width_mm
            margin = self.template.safe_margin_mm
            element.x_mm = max(margin, min(element.x_mm, self.template.paper_width_mm - margin - element.width_mm))
            element.y_mm = max(margin, min(element.y_mm, self.template.paper_height_mm - margin - element.height_mm))
        self._sync_selected_item()

    def _rotate_whole_layout(self) -> None:
        new_width = self.template.paper_height_mm
        new_height = self.template.paper_width_mm
        if not MIN_PAPER_WIDTH_MM <= new_width <= MAX_PAPER_WIDTH_MM or not MIN_PAPER_HEIGHT_MM <= new_height <= MAX_PAPER_HEIGHT_MM:
            information(
                self,
                "当前尺寸不能整版旋转",
                "旋转后纸张宽度和高度都需在 10–200 mm。可以先调整纸张尺寸，再旋转排版。",
            )
            return
        rotate_layout(self.template, clockwise=True)
        self.template.name = f"{self.template.name} 旋转版"
        self._load_template_ui()

    def _toggle_advanced(self) -> None:
        visible = not self.advanced_panel.isVisible()
        self.advanced_panel.setVisible(visible)
        self.advanced_toggle.setText("收起精确设置  ▴" if visible else "精确位置与对齐  ▾")

    def _refresh_named_presets(self, selected_name: str | None = None) -> None:
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        paths = sorted(self.preset_dir.glob("*.json"))
        self.saved_preset_combo.blockSignals(True)
        self.saved_preset_combo.clear()
        self.saved_preset_combo.addItem(f"我的预设（{len(paths)}） ▾", None)
        selected_index = 0
        if not paths:
            self.saved_preset_combo.addItem("暂无预设，请先命名并保存", None)
            empty_item = self.saved_preset_combo.model().item(1)
            if empty_item is not None:
                empty_item.setEnabled(False)
        for path in paths:
            preset = load_layout_template(path)
            self.saved_preset_combo.addItem(preset.name, path)
            if selected_name and preset.name == selected_name:
                selected_index = self.saved_preset_combo.count() - 1
        self.saved_preset_combo.setCurrentIndex(selected_index)
        self.saved_preset_combo.blockSignals(False)

    def _save_named_preset(self) -> bool:
        entered_name = self.name_edit.text().strip()
        loaded_name = getattr(self, "_loaded_template_name", self.template.name)
        active_path = getattr(self, "_active_preset_path", None)
        default_name = f"{self.template.paper_width_mm:g}×{self.template.paper_height_mm:g}-我的预设"
        preferred_name = (
            entered_name
            if entered_name and (active_path is not None or entered_name != loaded_name or getattr(self, "_name_was_explicit", False))
            else default_name
        )
        name = (
            self._unique_preset_name(preferred_name, active_path=active_path)
            if hasattr(self, "_unique_preset_name")
            else preferred_name
        )
        self.name_edit.setText(name)
        self.template.name = name
        errors = self._validate()
        if errors:
            warning(self, "预设不能保存", "\n".join(errors[:8]))
            return False
        safe_name = self._safe_preset_name(name) if hasattr(self, "_safe_preset_name") else "".join(
            character if character.isalnum() or character in "-_ ×" else "_" for character in name
        ).strip() or "自定义预设"
        target_path = self.preset_dir / f"{safe_name}.json"
        save_layout_template(self.template, target_path)
        self._last_saved_preset_path = target_path
        self._refresh_named_presets(name)
        self.save_preset_button.setText("已保存 ✓")
        return True

    def _named_preset_changed(self, _index: int) -> None:
        path = self.saved_preset_combo.currentData()
        if not path:
            if hasattr(self, "_show_editor_feedback"):
                self._show_editor_feedback("还没有个人预设，填写名称后点“保存”即可创建。", "info")
            return
        self.template = load_layout_template(Path(path))
        self._load_template_ui()
        self.preview_template_changed.emit(deepcopy(self.template))
        if hasattr(self, "_show_editor_feedback"):
            self._show_editor_feedback(f"已载入个人预设：{self.template.name}", "success")

    def _reset_preset(self) -> None:
        self.template = default_layout_template(self.width_spin.value(), self.height_spin.value())
        if hasattr(self, "_active_preset_path"):
            self._active_preset_path = None
        self._load_template_ui()
        self.preview_template_changed.emit(deepcopy(self.template))

    def _validate(self) -> list[str]:
        return layout_issues(self.template)

    def _save(self) -> None:
        self.template.name = self.name_edit.text().strip() or "自定义标签"
        errors = self._validate()
        if errors:
            warning(self, "模板不能保存", "\n".join(errors[:8]))
            return
        save_layout_template(self.template, self.template_path)
        self.settings.custom_layout_enabled = self.enabled.isChecked()
        self.settings.layout_template_name = self.template.name
        self.settings.paper_width_mm = self.template.paper_width_mm
        self.settings.paper_height_mm = self.template.paper_height_mm
        self.store.save(self.settings)
        self.settings_saved.emit(self.settings)
        self.accept()


# V2 keeps the proven canvas and validation logic above, while replacing the
# crowded first-beta controls with a clearer three-column workflow.
_LegacyLayoutEditorDialog = LayoutEditorDialog


class LayoutEditorDialog(_LegacyLayoutEditorDialog):
    _COMMON_TEXT_ORDER = (
        "owner",
        "phone",
        "model",
        "weight",
        "serial",
        "manufacturer",
        "product_model",
        "max_takeoff_weight",
        "registration_time",
        "registration_status",
        "owner_type",
    )

    def __init__(self, *args, **kwargs) -> None:
        self._element_clipboard: list[LayoutElement] = []
        self._active_preset_path: Path | None = None
        self._initial_active_preset_path: Path | None = None
        self._editing_current_preset = False
        self._last_save_applied_to_current = False
        self._saved_signature = None
        self._shortcut_targets: list[QWidget] = []
        self._optional_fields_visible = False
        super().__init__(*args, **kwargs)
        active_template = load_layout_template(self.template_path)
        self._active_preset_path = self._resolve_open_preset_path(active_template)
        self._initial_active_preset_path = self._active_preset_path
        default_template = default_layout_template(
            active_template.paper_width_mm,
            active_template.paper_height_mm,
        )
        self._editing_current_preset = (
            self._active_preset_path is not None or active_template != default_template
        )
        resolved_file = self._active_preset_path.name if self._active_preset_path is not None else ""
        if self.settings.layout_preset_file != resolved_file:
            self.settings.layout_preset_file = resolved_file
            self.store.save(self.settings)
        if self._active_preset_path is not None:
            self._load_template_ui()
        self._install_editor_shortcuts()
        self._saved_signature = self._current_signature()

    def _resolve_open_preset_path(self, active_template: LayoutTemplate) -> Path | None:
        """Recover the selected preset identity from pre-file-identity settings."""
        requested = Path(str(self.settings.layout_preset_file or "")).name
        if requested:
            requested_path = self.preset_dir / requested
            if requested_path.is_file():
                return requested_path

        if not self.preset_dir.is_dir():
            return None
        default_template = default_layout_template(
            active_template.paper_width_mm,
            active_template.paper_height_mm,
        )
        named: list[tuple[Path, LayoutTemplate]] = []
        for path in sorted(self.preset_dir.glob("*.json")):
            candidate = load_layout_template(path)
            if (
                candidate.name == self.settings.layout_template_name
                and abs(candidate.paper_width_mm - active_template.paper_width_mm) < 0.01
                and abs(candidate.paper_height_mm - active_template.paper_height_mm) < 0.01
            ):
                named.append((path, candidate))
        exact = [path for path, candidate in named if candidate == active_template]
        if len(exact) == 1:
            return exact[0]
        if len(named) == 1 and active_template != default_template:
            return named[0][0]
        return None

    def _is_initial_active_preset(self, path: Path | None) -> bool:
        return bool(
            path is not None
            and self._initial_active_preset_path is not None
            and path.resolve() == self._initial_active_preset_path.resolve()
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        header_card = QFrame(objectName="LayoutHeader")
        header = QVBoxLayout(header_card)
        header.setContentsMargins(12, 9, 12, 9)
        header.setSpacing(6)
        top_row = QHBoxLayout()
        top_row.setSpacing(9)
        back = QPushButton("←  返回")
        back.setObjectName("LayoutBackButton")
        back.setToolTip("返回主界面，监听和打印服务不会停止")
        back.clicked.connect(self.reject)
        top_row.addWidget(back)
        top_row.addWidget(QLabel("调整标签", objectName="LayoutEditorTitle"))
        top_row.addStretch(1)

        reset = QPushButton("恢复安全预设")
        reset.setObjectName("LayoutPresetButton")
        reset.clicked.connect(self._reset_preset)
        top_row.addWidget(reset)
        save = QPushButton("保存")
        save.setObjectName("Primary")
        save.setToolTip("保存到我的预设；当前使用的标签不会自动切换")
        save.clicked.connect(self._save)
        top_row.addWidget(save)
        self.save_preset_button = save
        header.addLayout(top_row)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        note = QLabel("两个标签共用尺寸；文字自动适配元素框。", objectName="Subtitle")
        note.setWordWrap(False)
        preset_row.addWidget(note)
        preset_row.addStretch(1)
        preset_row.addWidget(QLabel("预设名称", objectName="LayoutFieldLabel"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：维修台 50×40")
        self.name_edit.setMinimumWidth(170)
        self.name_edit.setMaximumWidth(240)
        preset_row.addWidget(self.name_edit)

        self.saved_preset_combo = RoundedNameComboBox()
        self.saved_preset_combo.setMinimumWidth(130)
        self.saved_preset_combo.setMaximumWidth(180)
        self.saved_preset_combo.setToolTip("快速打开已经保存的自定义预设")
        self.saved_preset_combo.activated.connect(self._named_preset_changed)
        preset_row.addWidget(self.saved_preset_combo)
        self.preset_feedback = QLabel("", objectName="LayoutPresetFeedback")
        self.preset_feedback.setVisible(False)
        self.preset_feedback.setWordWrap(False)
        preset_row.addWidget(self.preset_feedback)
        header.addLayout(preset_row)
        root.addWidget(header_card)

        # Compatibility attributes used by existing tests and settings code.
        self.enabled = QCheckBox()
        self.enabled.setChecked(True)
        self.enabled.hide()
        self.paper_combo = QComboBox()
        for label, width, height in PAPER_PRESETS:
            self.paper_combo.addItem(label, (width, height))
        self.paper_combo.addItem("自定义尺寸", None)
        self.paper_combo.hide()

        columns = QSplitter(Qt.Horizontal)
        columns.setObjectName("LayoutColumns")
        columns.setChildrenCollapsible(False)

        paper_panel = QFrame(objectName="PaperPresetPanel")
        paper_panel.setMinimumWidth(214)
        paper_panel.setMaximumWidth(248)
        paper_layout = QVBoxLayout(paper_panel)
        paper_layout.setContentsMargins(12, 13, 12, 12)
        paper_layout.setSpacing(8)
        paper_layout.addWidget(QLabel("纸张预设", objectName="SectionTitle"))
        paper_layout.addWidget(QLabel("上下滚动选择，两种标签共用尺寸", objectName="Subtitle"))
        self.paper_list = SmoothPresetListWidget()
        self.paper_list.setObjectName("PaperPresetList")
        self.paper_list.setItemDelegate(PaperPresetDelegate(self.paper_list))
        self.paper_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.paper_list.currentItemChanged.connect(self._paper_list_changed)
        paper_layout.addWidget(self.paper_list, 1)

        custom_card = QFrame(objectName="LayoutCustomSize")
        custom_layout = QVBoxLayout(custom_card)
        custom_layout.setContentsMargins(9, 8, 9, 9)
        custom_layout.setSpacing(6)
        custom_layout.addWidget(QLabel("自定义尺寸", objectName="LayoutFieldLabel"))
        custom_row = QHBoxLayout()
        custom_row.setSpacing(5)
        self.width_spin = self._spin(MIN_PAPER_WIDTH_MM, MAX_PAPER_WIDTH_MM, " mm")
        self.height_spin = self._spin(MIN_PAPER_HEIGHT_MM, MAX_PAPER_HEIGHT_MM, " mm")
        self.width_spin.setToolTip("纸张宽度，可用范围 10–200 mm")
        self.height_spin.setToolTip("纸张高度，可用范围 10–200 mm")
        custom_row.addWidget(self.width_spin)
        custom_row.addWidget(QLabel("×"))
        custom_row.addWidget(self.height_spin)
        custom_layout.addLayout(custom_row)
        self.apply_custom_button = QPushButton("应用这个尺寸")
        self.apply_custom_button.setObjectName("LayoutPresetButton")
        self.apply_custom_button.clicked.connect(self._custom_paper_changed)
        custom_layout.addWidget(self.apply_custom_button)
        self.custom_size_feedback = QLabel("可用范围：宽、高均为 10–200 mm", objectName="LayoutInlineFeedback")
        self.custom_size_feedback.setAlignment(Qt.AlignCenter)
        custom_layout.addWidget(self.custom_size_feedback)
        paper_layout.addWidget(custom_card)
        columns.addWidget(paper_panel)

        canvas_panel = QFrame(objectName="LayoutCanvasPanel")
        canvas_layout = QVBoxLayout(canvas_panel)
        canvas_layout.setContentsMargins(8, 10, 8, 8)
        canvas_layout.setSpacing(8)
        canvas_header = QHBoxLayout()
        canvas_header.addWidget(QLabel("打印效果", objectName="SectionTitle"))
        self.canvas_size_label = QLabel("", objectName="Subtitle")
        canvas_header.addWidget(self.canvas_size_label)
        canvas_header.addStretch()
        self.grid_button = QPushButton("网格")
        self.grid_button.setObjectName("LayoutGridButton")
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(False)
        self.grid_button.setToolTip("显示或隐藏辅助网格；绿色安全区始终保留")
        self.grid_button.toggled.connect(self.canvas_grid_toggled)
        canvas_header.addWidget(self.grid_button)
        canvas_layout.addLayout(canvas_header)
        self.canvas = LayoutCanvas()
        self.canvas.selected.connect(self._canvas_selected)
        self.canvas.geometry_changed.connect(self._canvas_geometry_changed)
        self.canvas.collision_blocked.connect(lambda message: self._show_editor_feedback(message, "error"))
        canvas_layout.addWidget(self.canvas, 1)
        columns.addWidget(canvas_panel)

        panel = QFrame(objectName="LayoutInspector")
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(370)
        panel_outer = QVBoxLayout(panel)
        panel_outer.setContentsMargins(0, 0, 0, 0)
        panel_scroll = QScrollArea()
        panel_scroll.setObjectName("LayoutInspectorScroll")
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_content = QWidget()
        panel_layout = QVBoxLayout(panel_content)
        panel_layout.setContentsMargins(13, 13, 13, 13)
        panel_layout.setSpacing(9)
        panel_layout.addWidget(QLabel("编辑内容", objectName="SectionTitle"))

        kind_switch = QFrame(objectName="LayoutKindSwitch")
        kind_layout = QHBoxLayout(kind_switch)
        kind_layout.setContentsMargins(4, 4, 4, 4)
        kind_layout.setSpacing(4)
        self.kind_buttons = QButtonGroup(self)
        self.kind_buttons.setExclusive(True)
        self.info_kind_button = QPushButton("标签 1")
        self.qr_kind_button = QPushButton("标签 2")
        for button, kind in ((self.info_kind_button, "info"), (self.qr_kind_button, "qr")):
            button.setCheckable(True)
            button.setObjectName("LayoutKindButton")
            button.clicked.connect(lambda _checked=False, value=kind: self._kind_button_clicked(value))
            self.kind_buttons.addButton(button)
            kind_layout.addWidget(button)
        self.info_kind_button.setChecked(True)
        panel_layout.addWidget(kind_switch)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("标签 1", "info")
        self.kind_combo.addItem("标签 2", "qr")
        self.kind_combo.hide()

        panel_layout.addWidget(QLabel("元素", objectName="LayoutFieldLabel"))
        self.element_list = QListWidget()
        self.element_list.setObjectName("LayoutElementList")
        self.element_list.setMinimumHeight(205)
        self.element_list.setMaximumHeight(260)
        self.element_list.currentItemChanged.connect(self._list_selected)
        self.element_list.itemChanged.connect(self._element_visibility_changed)
        panel_layout.addWidget(self.element_list)

        selection_card = QFrame(objectName="LayoutSelectionCard")
        selection_layout = QVBoxLayout(selection_card)
        selection_layout.setContentsMargins(10, 9, 10, 10)
        selection_layout.setSpacing(7)
        self.selected_title = QLabel("请选择一个元素", objectName="LayoutSelectedTitle")
        self.selected_title.setWordWrap(True)
        selection_layout.addWidget(self.selected_title)
        self.selected_hint = QLabel("在画布或上方列表中选择后即可调整。", objectName="Subtitle")
        self.selected_hint.setWordWrap(True)
        selection_layout.addWidget(self.selected_hint)

        move_title = QHBoxLayout()
        move_title.addWidget(QLabel("移动位置", objectName="LayoutFieldLabel"))
        move_title.addStretch()
        move_title.addWidget(QLabel("每次 0.5 mm", objectName="Subtitle"))
        selection_layout.addLayout(move_title)
        move_grid = QGridLayout()
        move_grid.setHorizontalSpacing(7)
        move_grid.setVerticalSpacing(6)
        for text, dx, dy, row, column in (
            ("↑", 0, -0.5, 0, 1),
            ("←", -0.5, 0, 1, 0),
            ("↓", 0, 0.5, 1, 1),
            ("→", 0.5, 0, 1, 2),
        ):
            button = self._quick_button(text)
            button.setToolTip("移动 0.5 mm")
            button.clicked.connect(lambda _checked=False, x=dx, y=dy: self._nudge_selected(x, y))
            move_grid.addWidget(button, row, column)
        selection_layout.addLayout(move_grid)

        selection_layout.addWidget(QLabel("元素大小", objectName="LayoutFieldLabel"))
        size_row = QHBoxLayout()
        size_row.setSpacing(7)
        self.smaller_element_button = self._quick_button("−  缩小", wide=True)
        self.larger_element_button = self._quick_button("＋  放大", wide=True)
        self.rotate_selected_button = self._quick_button("↻  旋转90°", wide=True)
        self.smaller_element_button.clicked.connect(lambda: self._resize_selected(-0.5))
        self.larger_element_button.clicked.connect(lambda: self._resize_selected(0.5))
        self.rotate_selected_button.clicked.connect(self._rotate_selected)
        size_row.addWidget(self.smaller_element_button)
        size_row.addWidget(self.larger_element_button)
        size_row.addWidget(self.rotate_selected_button)
        selection_layout.addLayout(size_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(7)
        self.copy_element_button = self._quick_button("复制", wide=True)
        self.paste_element_button = self._quick_button("粘贴", wide=True)
        self.remove_element_button = self._quick_button("移除", wide=True)
        self.copy_element_button.setToolTip("复制选中元素（Ctrl+C）")
        self.paste_element_button.setToolTip("粘贴复制的元素（Ctrl+V）")
        self.remove_element_button.setToolTip("从当前标签隐藏选中元素（Backspace / Delete）")
        self.copy_element_button.clicked.connect(self._copy_selected)
        self.paste_element_button.clicked.connect(self._paste_elements)
        self.remove_element_button.clicked.connect(self._hide_selected_elements)
        action_row.addWidget(self.copy_element_button)
        action_row.addWidget(self.paste_element_button)
        action_row.addWidget(self.remove_element_button)
        selection_layout.addLayout(action_row)

        # Visibility is controlled only by the checkboxes in the element list.
        # Keep this hidden compatibility control because the proven property
        # update logic synchronizes an element's visibility through it.
        self.visible_check = QCheckBox(panel_content)
        self.visible_check.hide()
        self.visible_check.toggled.connect(self._property_changed)

        # Kept as hidden compatibility attributes. Text size is intentionally
        # no longer user-adjustable because rendering fits text to its box.
        self.font_quick_label = QLabel()
        self.font_smaller = QPushButton()
        self.font_larger = QPushButton()
        panel_layout.addWidget(selection_card)

        self.advanced_toggle = QPushButton("精确调整  ▾")
        self.advanced_toggle.setObjectName("LayoutAdvancedToggle")
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        panel_layout.addWidget(self.advanced_toggle)
        self.advanced_panel = QFrame(objectName="LayoutAdvancedPanel")
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(9, 8, 9, 8)
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(7)
        self.x_spin = self._spin(0.0, 300.0, " mm")
        self.y_spin = self._spin(0.0, 300.0, " mm")
        self.w_spin = self._spin(1.0, 300.0, " mm")
        self.h_spin = self._spin(1.0, 300.0, " mm")
        self.font_spin = self._spin(MIN_TEXT_SIZE_MM, 20.0, " mm")
        self.font_spin.hide()
        self.align_combo = QComboBox()
        self.align_combo.addItem("左对齐", "left")
        self.align_combo.addItem("居中", "center")
        self.align_combo.addItem("右对齐", "right")
        self.lock_check = QCheckBox("保持等比例")
        for spin in (self.x_spin, self.y_spin, self.w_spin, self.h_spin, self.font_spin):
            spin.valueChanged.connect(self._property_changed)
        self.align_combo.currentIndexChanged.connect(self._property_changed)
        self.lock_check.toggled.connect(self._property_changed)
        form.addRow("X 坐标", self.x_spin)
        form.addRow("Y 坐标", self.y_spin)
        form.addRow("宽度", self.w_spin)
        form.addRow("高度", self.h_spin)
        form.addRow("文字对齐", self.align_combo)
        form.addRow("", self.lock_check)
        advanced_layout.addLayout(form)
        self.advanced_panel.setVisible(False)
        panel_layout.addWidget(self.advanced_panel)
        panel_layout.addStretch()
        panel_scroll.setWidget(panel_content)
        panel_outer.addWidget(panel_scroll)
        columns.addWidget(panel)
        columns.setStretchFactor(0, 0)
        columns.setStretchFactor(1, 1)
        columns.setStretchFactor(2, 0)
        columns.setSizes([224, 760, 338])
        root.addWidget(columns, 1)

    def _build_ui(self) -> None:
        """Build a compact editor that keeps advanced controls out of the default path."""
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        header_card = QFrame(objectName="LayoutHeader")
        header = QVBoxLayout(header_card)
        header.setContentsMargins(11, 9, 11, 9)
        header.setSpacing(7)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        back = QPushButton("←  返回", objectName="LayoutBackButton")
        back.setToolTip("返回主界面，监听和打印服务不会停止")
        back.clicked.connect(self.reject)
        toolbar.addWidget(back)
        toolbar.addWidget(QLabel("调整标签", objectName="LayoutEditorTitle"))

        self.preset_feedback = QLabel("", objectName="LayoutPresetFeedback")
        self.preset_feedback.setVisible(False)
        self.preset_feedback.setWordWrap(False)
        toolbar.addWidget(self.preset_feedback)
        toolbar.addStretch(1)
        toolbar.addWidget(QLabel("纸张", objectName="LayoutFieldLabel"))
        self.paper_picker = PaperPresetComboBox(template_path_override=self.template_path)
        self.paper_picker.setMinimumWidth(176)
        self.paper_picker.setMaximumWidth(224)
        self.paper_picker.setToolTip("选择纸张尺寸或打开已经保存的个人预设")
        self.paper_picker.currentIndexChanged.connect(self._paper_picker_changed)
        toolbar.addWidget(self.paper_picker)

        self.preset_settings_button = QPushButton("编辑尺寸", objectName="LayoutPresetButton")
        self.preset_settings_button.setCheckable(True)
        self.preset_settings_button.setToolTip("修改预设名称和纸张尺寸，或管理我的预设")
        self.preset_settings_button.toggled.connect(self._toggle_preset_settings)
        toolbar.addWidget(self.preset_settings_button)
        reset = QPushButton("恢复默认", objectName="LayoutPresetButton")
        reset.setToolTip("恢复当前纸张的安全排版")
        reset.clicked.connect(self._reset_preset)
        toolbar.addWidget(reset)
        save = QPushButton("保存", objectName="Primary")
        save.setToolTip("保存到我的预设；需要使用时再从主界面的标签大小中选择")
        save.clicked.connect(self._save)
        toolbar.addWidget(save)
        self.save_preset_button = save
        header.addLayout(toolbar)

        self.preset_settings_panel = QFrame(objectName="LayoutCustomSizeBar")
        settings_panel_layout = QVBoxLayout(self.preset_settings_panel)
        settings_panel_layout.setContentsMargins(10, 7, 10, 7)
        settings_panel_layout.setSpacing(6)
        settings_row = QHBoxLayout()
        settings_row.setSpacing(7)
        settings_row.addWidget(QLabel("名称", objectName="LayoutFieldLabel"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：仓库 60×40")
        self.name_edit.setMinimumWidth(170)
        self.name_edit.setMaximumWidth(230)
        self.name_edit.setToolTip("保存个人预设时使用的名称")
        settings_row.addWidget(self.name_edit)
        settings_row.addWidget(QLabel("尺寸", objectName="LayoutFieldLabel"))
        self.width_spin = self._spin(MIN_PAPER_WIDTH_MM, MAX_PAPER_WIDTH_MM, " mm")
        self.width_spin.setFixedWidth(100)
        settings_row.addWidget(self.width_spin)
        settings_row.addWidget(QLabel("×", objectName="LayoutFieldLabel"))
        self.height_spin = self._spin(MIN_PAPER_HEIGHT_MM, MAX_PAPER_HEIGHT_MM, " mm")
        self.height_spin.setFixedWidth(100)
        settings_row.addWidget(self.height_spin)
        self.apply_custom_button = QPushButton("应用尺寸", objectName="LayoutPresetButton")
        self.apply_custom_button.clicked.connect(self._custom_paper_changed)
        settings_row.addWidget(self.apply_custom_button)
        self.custom_size_feedback = QLabel("宽、高均为 10–200 mm", objectName="LayoutInlineFeedback")
        self.custom_size_feedback.setMinimumWidth(165)
        settings_row.addWidget(self.custom_size_feedback, 1)
        settings_panel_layout.addLayout(settings_row)

        preset_manage_row = QHBoxLayout()
        preset_manage_row.setSpacing(7)
        preset_manage_row.addWidget(QLabel("我的预设", objectName="LayoutFieldLabel"))
        self.saved_preset_combo = RoundedNameComboBox()
        self.saved_preset_combo.setMinimumWidth(210)
        self.saved_preset_combo.setMaximumWidth(360)
        self.saved_preset_combo.setToolTip("选择已保存的自定义预设")
        self.saved_preset_combo.activated.connect(self._named_preset_changed)
        self.saved_preset_combo.currentIndexChanged.connect(self._sync_delete_preset_button)
        preset_manage_row.addWidget(self.saved_preset_combo)
        self.delete_preset_button = QPushButton("删除预设", objectName="LayoutDangerButton")
        self.delete_preset_button.setToolTip("删除选中的个人预设；内置纸张不会被删除")
        self.delete_preset_button.clicked.connect(self._delete_selected_preset)
        preset_manage_row.addWidget(self.delete_preset_button)
        preset_manage_row.addStretch(1)
        settings_panel_layout.addLayout(preset_manage_row)
        self.preset_settings_panel.hide()
        header.addWidget(self.preset_settings_panel)
        # Compatibility aliases for the shared template logic and older tests.
        self.custom_size_button = self.preset_settings_button
        self.custom_size_panel = self.preset_settings_panel
        self.name_panel = self.preset_settings_panel
        root.addWidget(header_card)

        # Compatibility models stay available for the proven template logic,
        # but the default interface uses the compact picker above.
        self.enabled = QCheckBox()
        self.enabled.setChecked(True)
        self.enabled.hide()
        self.paper_combo = QComboBox()
        for label, width, height in PAPER_PRESETS:
            self.paper_combo.addItem(label, (width, height))
        self.paper_combo.addItem("自定义尺寸", None)
        self.paper_combo.hide()
        self.paper_list = SmoothPresetListWidget()
        self.paper_list.currentItemChanged.connect(self._paper_list_changed)
        self.paper_list.hide()
        columns = QSplitter(Qt.Horizontal)
        columns.setObjectName("LayoutColumns")
        columns.setChildrenCollapsible(False)

        canvas_panel = QFrame(objectName="LayoutCanvasPanel")
        canvas_layout = QVBoxLayout(canvas_panel)
        canvas_layout.setContentsMargins(9, 9, 9, 9)
        canvas_layout.setSpacing(8)
        canvas_header = QHBoxLayout()
        canvas_header.setSpacing(8)

        kind_switch = QFrame(objectName="LayoutKindSwitch")
        kind_layout = QHBoxLayout(kind_switch)
        kind_layout.setContentsMargins(4, 4, 4, 4)
        kind_layout.setSpacing(4)
        self.kind_buttons = QButtonGroup(self)
        self.kind_buttons.setExclusive(True)
        self.info_kind_button = QPushButton("标签 1")
        self.qr_kind_button = QPushButton("标签 2")
        for button, kind in ((self.info_kind_button, "info"), (self.qr_kind_button, "qr")):
            button.setCheckable(True)
            button.setObjectName("LayoutKindButton")
            button.clicked.connect(lambda _checked=False, value=kind: self._kind_button_clicked(value))
            self.kind_buttons.addButton(button)
            kind_layout.addWidget(button)
        self.info_kind_button.setChecked(True)
        canvas_header.addWidget(kind_switch)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("标签 1", "info")
        self.kind_combo.addItem("标签 2", "qr")
        self.kind_combo.hide()
        self.canvas_size_label = QLabel("", objectName="Subtitle")
        canvas_header.addWidget(self.canvas_size_label)
        canvas_header.addStretch(1)
        self.grid_button = QPushButton("网格", objectName="LayoutGridButton")
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(False)
        self.grid_button.setToolTip("辅助网格默认关闭，绿色安全区始终保留")
        self.grid_button.toggled.connect(self.canvas_grid_toggled)
        canvas_header.addWidget(self.grid_button)
        canvas_layout.addLayout(canvas_header)

        self.canvas = LayoutCanvas()
        self.canvas.selected.connect(self._canvas_selected)
        self.canvas.geometry_changed.connect(self._canvas_geometry_changed)
        self.canvas.collision_blocked.connect(lambda message: self._show_editor_feedback(message, "error"))
        self.canvas.collision_resolved.connect(lambda message: self._show_editor_feedback(message, "success"))
        canvas_layout.addWidget(self.canvas, 1)
        columns.addWidget(canvas_panel)

        panel = QFrame(objectName="LayoutInspector")
        panel.setMinimumWidth(286)
        panel.setMaximumWidth(326)
        panel_outer = QVBoxLayout(panel)
        panel_outer.setContentsMargins(0, 0, 0, 0)
        panel_scroll = QScrollArea(objectName="LayoutInspectorScroll")
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_content = QWidget()
        panel_layout = QVBoxLayout(panel_content)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(8)
        panel_layout.addWidget(QLabel("标签内容", objectName="SectionTitle"))

        self.element_list = QListWidget(objectName="LayoutElementList")
        self.element_list.setMinimumHeight(222)
        self.element_list.setMaximumHeight(232)
        self.element_list.currentItemChanged.connect(self._list_selected)
        self.element_list.itemChanged.connect(self._element_visibility_changed)
        panel_layout.addWidget(self.element_list)
        self.show_optional_button = QPushButton("更多 UOM 字段  ▾", objectName="LayoutAdvancedToggle")
        self.show_optional_button.clicked.connect(self._toggle_optional_fields)
        panel_layout.addWidget(self.show_optional_button)

        selection_card = QFrame(objectName="LayoutSelectionCard")
        selection_layout = QVBoxLayout(selection_card)
        selection_layout.setContentsMargins(10, 9, 10, 10)
        selection_layout.setSpacing(7)
        self.selected_title = QLabel("请选择一个元素", objectName="LayoutSelectedTitle")
        self.selected_title.setWordWrap(True)
        selection_layout.addWidget(self.selected_title)
        self.selected_hint = QLabel("拖动改变位置，拖右下角改变大小。", objectName="Subtitle")
        self.selected_hint.setWordWrap(False)
        selection_layout.addWidget(self.selected_hint)

        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self.smaller_element_button = self._quick_button("−", wide=True)
        self.smaller_element_button.setToolTip("缩小 1 mm")
        self.larger_element_button = self._quick_button("＋", wide=True)
        self.larger_element_button.setToolTip("放大 1 mm")
        self.rotate_selected_button = self._quick_button("旋转", wide=True)
        self.smaller_element_button.clicked.connect(lambda: self._resize_selected(-1.0))
        self.larger_element_button.clicked.connect(lambda: self._resize_selected(1.0))
        self.rotate_selected_button.clicked.connect(self._rotate_selected)
        size_row.addWidget(self.smaller_element_button)
        size_row.addWidget(self.larger_element_button)
        size_row.addWidget(self.rotate_selected_button)
        selection_layout.addLayout(size_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.copy_element_button = self._quick_button("创建副本", wide=True)
        self.copy_element_button.setToolTip("在安全区空位创建当前元素的副本（Ctrl+D）")
        self.copy_element_button.clicked.connect(self._duplicate_selected)
        self.remove_element_button = self._quick_button("移除", wide=True)
        self.remove_element_button.setToolTip("从当前标签隐藏选中元素（Backspace / Delete）")
        self.remove_element_button.clicked.connect(self._hide_selected_elements)
        action_row.addWidget(self.copy_element_button)
        action_row.addWidget(self.remove_element_button)
        selection_layout.addLayout(action_row)
        self.action_feedback = QLabel("", objectName="LayoutActionFeedback")
        self.action_feedback.setWordWrap(True)
        self.action_feedback.hide()
        selection_layout.addWidget(self.action_feedback)
        self.paste_element_button = QPushButton()
        self.paste_element_button.clicked.connect(self._paste_elements)
        self.paste_element_button.hide()

        self.visible_check = QCheckBox(panel_content)
        self.visible_check.hide()
        self.visible_check.toggled.connect(self._property_changed)
        self.font_quick_label = QLabel()
        self.font_quick_label.hide()
        self.font_smaller = QPushButton()
        self.font_smaller.hide()
        self.font_larger = QPushButton()
        self.font_larger.hide()
        panel_layout.addWidget(selection_card)

        self.advanced_toggle = QPushButton("精确位置与对齐  ▾", objectName="LayoutAdvancedToggle")
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        panel_layout.addWidget(self.advanced_toggle)
        self.advanced_panel = QFrame(objectName="LayoutAdvancedPanel")
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(9, 8, 9, 8)
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(7)
        self.x_spin = self._spin(0.0, 300.0, " mm")
        self.y_spin = self._spin(0.0, 300.0, " mm")
        self.w_spin = self._spin(1.0, 300.0, " mm")
        self.h_spin = self._spin(1.0, 300.0, " mm")
        self.font_spin = self._spin(MIN_TEXT_SIZE_MM, 20.0, " mm")
        self.font_spin.hide()
        self.align_combo = QComboBox()
        self.align_combo.addItem("左对齐", "left")
        self.align_combo.addItem("居中", "center")
        self.align_combo.addItem("右对齐", "right")
        self.lock_check = QCheckBox("保持等比例")
        for spin in (self.x_spin, self.y_spin, self.w_spin, self.h_spin, self.font_spin):
            spin.valueChanged.connect(self._property_changed)
        self.align_combo.currentIndexChanged.connect(self._property_changed)
        self.lock_check.toggled.connect(self._property_changed)
        form.addRow("X 坐标", self.x_spin)
        form.addRow("Y 坐标", self.y_spin)
        form.addRow("宽度", self.w_spin)
        form.addRow("高度", self.h_spin)
        form.addRow("文字对齐", self.align_combo)
        form.addRow("", self.lock_check)
        advanced_layout.addLayout(form)
        self.advanced_panel.hide()
        panel_layout.addWidget(self.advanced_panel)

        panel_layout.addStretch(1)
        panel_scroll.setWidget(panel_content)
        panel_outer.addWidget(panel_scroll)
        columns.addWidget(panel)
        columns.setStretchFactor(0, 1)
        columns.setStretchFactor(1, 0)
        columns.setSizes([820, 304])
        root.addWidget(columns, 1)

    def _install_editor_shortcuts(self) -> None:
        self._shortcut_targets = [self, *self.findChildren(QWidget)]
        for widget in self._shortcut_targets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.KeyPress or not self.isVisible():
            return super().eventFilter(watched, event)
        if not self._keyboard_action_allowed():
            return super().eventFilter(watched, event)

        modifiers = event.modifiers() & (
            Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier | Qt.ShiftModifier
        )
        command_only = modifiers in (Qt.ControlModifier, Qt.MetaModifier)
        callback = None
        if modifiers == Qt.NoModifier and event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            callback = self._hide_selected_elements
        elif command_only and event.key() == Qt.Key_C:
            callback = self._copy_selected
        elif command_only and event.key() == Qt.Key_V:
            callback = self._paste_elements
        elif command_only and event.key() == Qt.Key_D:
            callback = self._duplicate_selected

        if callback is None:
            return super().eventFilter(watched, event)
        if not event.isAutoRepeat():
            self._run_keyboard_action(callback)
        event.accept()
        return True

    @staticmethod
    def _keyboard_action_allowed() -> bool:
        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, (QLineEdit, QAbstractSpinBox, QComboBox)):
                return False
            widget = widget.parentWidget()
        return True

    def _run_keyboard_action(self, callback) -> None:
        if self._keyboard_action_allowed():
            callback()

    def canvas_grid_toggled(self, visible: bool) -> None:
        self.canvas.set_grid_visible(visible)
        self.grid_button.setText("隐藏网格" if visible else "网格")

    def _show_editor_feedback(self, text: str, state: str = "success") -> None:
        if not hasattr(self, "preset_feedback"):
            return
        self.preset_feedback.setText(text)
        self.preset_feedback.setProperty("state", state)
        self.preset_feedback.style().unpolish(self.preset_feedback)
        self.preset_feedback.style().polish(self.preset_feedback)
        self.preset_feedback.setVisible(True)
        if hasattr(self, "action_feedback"):
            self.action_feedback.setText(text)
            self.action_feedback.setProperty("state", state)
            self.action_feedback.style().unpolish(self.action_feedback)
            self.action_feedback.style().polish(self.action_feedback)
            self.action_feedback.setVisible(True)

    def _ensure_common_elements(self) -> None:
        """Expose the same optional element set on 标签1 and 标签2."""
        safe = default_layout_template(self.template.paper_width_mm, self.template.paper_height_mm)
        info_ids = {element.id for element in self.template.info_elements}
        qr_ids = {element.id for element in self.template.qr_elements}

        if "info_qr_2" not in info_ids:
            second_qr = next((element for element in safe.qr_elements if element.id == "qr_2"), None)
            second_uas = next((element for element in safe.qr_elements if element.id == "uas_2"), None)
            if second_qr and second_uas:
                qr_copy = deepcopy(second_qr)
                qr_copy.id = "info_qr_2"
                qr_copy.label = "二维码 2"
                qr_copy.visible = False
                uas_copy = deepcopy(second_uas)
                uas_copy.id = "info_uas_2"
                uas_copy.label = "实名登记标识 2"
                uas_copy.visible = False
                self.template.info_elements.extend((qr_copy, uas_copy))

        info_source = {element.id: element for element in safe.info_elements}
        for element_id in ("owner", "phone", "model", "weight", "serial"):
            if element_id in qr_ids or element_id not in info_source:
                continue
            element = deepcopy(info_source[element_id])
            element.visible = False
            self.template.qr_elements.append(element)

        optional_fields = (
            ("manufacturer", "制造商", "manufacturer_label"),
            ("product_model", "产品型号", "product_model_label"),
            ("max_takeoff_weight", "最大起飞重量", "maximum_takeoff_weight_label"),
            ("registration_time", "登记时间", "registration_time_label"),
            ("registration_status", "登记状态", "status_label"),
            ("owner_type", "主体类型", "owner_type_label"),
        )
        margin = self.template.safe_margin_mm
        field_width = max(8.0, self.template.paper_width_mm - margin * 2)
        for target in (self.template.info_elements, self.template.qr_elements):
            existing = {element.id for element in target}
            for index, (element_id, label, source) in enumerate(optional_fields):
                if element_id in existing:
                    continue
                height = 3.4
                y = min(
                    max(margin, self.template.paper_height_mm - margin - height),
                    margin + index * (height + 0.4),
                )
                target.append(
                    LayoutElement(
                        element_id,
                        label,
                        "text",
                        source,
                        margin,
                        y,
                        field_width,
                        height,
                        2.6,
                        "left",
                        visible=False,
                    )
                )

    def _base_groups(self) -> list[tuple[tuple[str, ...], str]]:
        if self.current_kind == "info":
            qr_groups = (
                (("info_qr", "info_uas"), "▦  二维码 + 登记标识 1"),
                (("info_qr_2", "info_uas_2"), "▦  二维码 + 登记标识 2"),
            )
        else:
            qr_groups = (
                (("qr_1", "uas_1"), "▦  二维码 + 登记标识 1"),
                (("qr_2", "uas_2"), "▦  二维码 + 登记标识 2"),
            )
        lookup = {element.id: element for element in self.template.elements(self.current_kind)}
        groups = [(ids, label) for ids, label in qr_groups if all(element_id in lookup for element_id in ids)]
        groups.extend(
            ((element_id,), f"T  {lookup[element_id].label}")
            for element_id in self._COMMON_TEXT_ORDER
            if element_id in lookup
        )
        return groups

    def _load_template_ui(self, *, refresh_paper_list: bool = True, refresh_named_presets: bool = True) -> None:
        self._ensure_common_elements()
        self._updating = True
        self.name_edit.setText(self.template.name)
        self._loaded_template_name = self.template.name
        self._name_was_explicit = False
        self.width_spin.setValue(self.template.paper_width_mm)
        self.height_spin.setValue(self.template.paper_height_mm)
        matched = False
        for index in range(self.paper_combo.count() - 1):
            width, height = self.paper_combo.itemData(index)
            if abs(width - self.template.paper_width_mm) < 0.01 and abs(height - self.template.paper_height_mm) < 0.01:
                self.paper_combo.setCurrentIndex(index)
                matched = True
                break
        if not matched:
            self.paper_combo.setCurrentIndex(self.paper_combo.count() - 1)
        if hasattr(self, "paper_picker"):
            preset_file = self._active_preset_path.name if self._active_preset_path is not None else None
            self.paper_picker.refresh_presets(self.template.name, preset_file)
            self.paper_picker.set_current_paper(
                self.template.paper_width_mm,
                self.template.paper_height_mm,
                self.template.name,
                preset_file,
            )
        self._updating = False
        if refresh_named_presets:
            self._refresh_named_presets(self.template.name)
        if refresh_paper_list:
            self._refresh_paper_list(self.template.name)
        self._reload_kind()

    def _refresh_paper_list(self, selected_name: str | None = None) -> None:
        self.paper_list.blockSignals(True)
        self.paper_list.clear()
        selected_row = -1
        for label, width, height in PAPER_PRESETS:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, (float(width), float(height)))
            item.setData(Qt.UserRole + 1, "正方形" if width == height else ("横向" if width > height else "竖向"))
            self.paper_list.addItem(item)
            if abs(width - self.template.paper_width_mm) < 0.01 and abs(height - self.template.paper_height_mm) < 0.01:
                selected_row = self.paper_list.count() - 1
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.preset_dir.glob("*.json")):
            preset = load_layout_template(path)
            item = QListWidgetItem(preset.name)
            item.setData(Qt.UserRole, (preset.paper_width_mm, preset.paper_height_mm))
            item.setData(Qt.UserRole + 1, f"我的预设 · {preset.name}")
            item.setData(Qt.UserRole + 2, path)
            self.paper_list.addItem(item)
            if selected_name and preset.name == selected_name:
                selected_row = self.paper_list.count() - 1
        if selected_row >= 0:
            self.paper_list.setCurrentRow(selected_row)
            self.paper_list.scrollToItem(self.paper_list.item(selected_row), QAbstractItemView.PositionAtTop)
        self.paper_list.blockSignals(False)

    def _paper_list_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if self._updating or current is None:
            return
        path = current.data(Qt.UserRole + 2)
        paper_size = current.data(Qt.UserRole)
        label = current.text()
        self._paper_change_generation += 1
        generation = self._paper_change_generation
        self._show_editor_feedback(f"正在切换到 {label}…", "working")
        QTimer.singleShot(
            0,
            lambda: self._apply_paper_list_change(generation, Path(path) if path else None, paper_size, label),
        )

    def _apply_paper_list_change(self, generation: int, path: Path | None, paper_size, label: str) -> None:
        if generation != self._paper_change_generation:
            return
        if path is not None:
            self.template = load_layout_template(path)
            self._active_preset_path = path
        else:
            width, height = paper_size
            self.template = default_layout_template(float(width), float(height))
            self._active_preset_path = None
        self._load_template_ui(refresh_paper_list=False)
        self.preview_template_changed.emit(deepcopy(self.template))
        self._show_editor_feedback(f"已切换：{label}", "success")

    def _custom_paper_changed(self) -> None:
        if self._updating:
            return
        width = self.width_spin.entered_value()
        height = self.height_spin.entered_value()
        width_valid = width is not None and MIN_PAPER_WIDTH_MM <= width <= MAX_PAPER_WIDTH_MM
        height_valid = height is not None and MIN_PAPER_HEIGHT_MM <= height <= MAX_PAPER_HEIGHT_MM
        for spin, valid in ((self.width_spin, width_valid), (self.height_spin, height_valid)):
            spin.setProperty("invalid", not valid)
            spin.style().unpolish(spin)
            spin.style().polish(spin)
        if not width_valid or not height_valid:
            message = "尺寸未应用：宽度和高度都需为 10–200 mm。"
            self.custom_size_feedback.setText(message)
            self.custom_size_feedback.setProperty("state", "error")
            self.custom_size_feedback.style().unpolish(self.custom_size_feedback)
            self.custom_size_feedback.style().polish(self.custom_size_feedback)
            self._show_editor_feedback(message, "error")
            return
        assert width is not None and height is not None
        entered_name = self.name_edit.text().strip()
        loaded_name = getattr(self, "_loaded_template_name", self.template.name)
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)
        self.template = default_layout_template(width, height)
        name_was_explicit = bool(entered_name and entered_name != loaded_name)
        self.template.name = entered_name if name_was_explicit else f"{width:g}×{height:g}-我的预设"
        self._active_preset_path = None
        self._load_template_ui()
        self._name_was_explicit = name_was_explicit
        self.preview_template_changed.emit(deepcopy(self.template))
        short_side_warning = min(width, height) < MIN_SAFE_QR_MM + 2.0
        if short_side_warning:
            self.custom_size_feedback.setText(f"已应用 {width:g} × {height:g} mm；短边较小，保存前请确认二维码仍在安全区")
            self.custom_size_feedback.setProperty("state", "warning")
        else:
            self.custom_size_feedback.setText(f"✓ 已应用 {width:g} × {height:g} mm")
            self.custom_size_feedback.setProperty("state", "success")
        self.custom_size_feedback.style().unpolish(self.custom_size_feedback)
        self.custom_size_feedback.style().polish(self.custom_size_feedback)
        self._show_editor_feedback(
            "尺寸已应用；该尺寸无法容纳18 mm二维码，请调整或隐藏超出元素。"
            if short_side_warning
            else "尺寸已应用，可继续调整排版或保存。",
            "info" if short_side_warning else "success",
        )

    def _paper_picker_changed(self, _index: int) -> None:
        if self._updating or not hasattr(self, "paper_picker"):
            return
        path = self.paper_picker.current_preset_path()
        self._editing_current_preset = self._is_initial_active_preset(path)
        if path is not None and path.is_file():
            self.template = load_layout_template(path)
            self._active_preset_path = path
        else:
            width, height = self.paper_picker.current_paper()
            self.template = default_layout_template(width, height)
            self._active_preset_path = None
        self._load_template_ui()
        self.preview_template_changed.emit(deepcopy(self.template))
        self._show_editor_feedback(f"已切换：{self.template.name}", "success")

    def _toggle_preset_settings(self, checked: bool) -> None:
        self.preset_settings_panel.setVisible(bool(checked))
        self.preset_settings_button.setText("收起" if checked else "编辑尺寸")
        if checked:
            self.name_edit.setFocus()
            self.name_edit.selectAll()

    def _sync_delete_preset_button(self, _index: int = 0) -> None:
        if hasattr(self, "delete_preset_button"):
            self.delete_preset_button.setEnabled(bool(self.saved_preset_combo.currentData()))

    @staticmethod
    def _safe_preset_name(name: str) -> str:
        return "".join(character if character.isalnum() or character in "-_ ×" else "_" for character in name).strip() or "自定义预设"

    def _unique_preset_name(self, preferred: str, *, active_path: Path | None = None) -> str:
        base = preferred.strip() or f"{self.template.paper_width_mm:g}×{self.template.paper_height_mm:g}-我的预设"
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()
        used_files: set[str] = set()
        for path in self.preset_dir.glob("*.json"):
            if active_path is not None and path.resolve() == active_path.resolve():
                continue
            used_files.add(path.name.casefold())
            used_names.add(load_layout_template(path).name.casefold())
        candidate = base
        suffix = 1
        while candidate.casefold() in used_names or f"{self._safe_preset_name(candidate)}.json".casefold() in used_files:
            candidate = f"{base}{suffix}"
            suffix += 1
        return candidate

    def _delete_selected_preset(self) -> None:
        value = self.saved_preset_combo.currentData()
        if not value:
            self._show_editor_feedback("请先选择要删除的个人预设。", "info")
            return
        path = Path(value)
        preset = load_layout_template(path)
        confirmed = confirm_danger(
            self,
            "删除个人预设",
            f"确定删除“{preset.name}”吗？",
            detail="只会删除这个个人预设，内置纸张和其他预设不受影响。",
            confirm_text="删除预设",
            cancel_text="保留",
        )
        if not confirmed:
            return

        deleting_active = self._active_preset_path is not None and path.resolve() == self._active_preset_path.resolve()
        deleting_selected = self.settings.layout_preset_file == path.name
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            self._show_editor_feedback(f"删除失败：{exc}", "error")
            return

        if deleting_selected:
            fallback = default_layout_template(preset.paper_width_mm, preset.paper_height_mm)
            save_layout_template(fallback, self.template_path)
            self.settings.layout_template_name = fallback.name
            self.settings.layout_preset_file = ""
            self.settings.paper_width_mm = fallback.paper_width_mm
            self.settings.paper_height_mm = fallback.paper_height_mm
            self.settings.custom_layout_enabled = True
            self.store.save(self.settings)
        if deleting_active:
            self.template = default_layout_template(preset.paper_width_mm, preset.paper_height_mm)
            self._active_preset_path = None
            self._load_template_ui()
            self.preview_template_changed.emit(deepcopy(self.template))
        else:
            self._refresh_named_presets()
            self.paper_picker.refresh_presets(self.template.name)
        self._sync_delete_preset_button()
        self._show_editor_feedback(f"已删除个人预设：{preset.name}", "success")

    def _toggle_custom_size(self, checked: bool) -> None:
        self.preset_settings_button.setChecked(bool(checked))

    def _toggle_name_panel(self, checked: bool) -> None:
        self.preset_settings_button.setChecked(bool(checked))

    def _toggle_optional_fields(self) -> None:
        self._optional_fields_visible = not self._optional_fields_visible
        self._apply_optional_field_visibility()

    def _apply_optional_field_visibility(self) -> None:
        optional_ids = {
            "manufacturer",
            "product_model",
            "max_takeoff_weight",
            "registration_time",
            "registration_status",
            "owner_type",
        }
        for row in range(self.element_list.count()):
            item = self.element_list.item(row)
            group = item.data(Qt.UserRole)
            element_ids = tuple(group) if isinstance(group, tuple) else (str(group),)
            is_optional = bool(element_ids) and all(element_id in optional_ids for element_id in element_ids)
            item.setHidden(is_optional and not self._optional_fields_visible)
        self.show_optional_button.setText(
            "收起 UOM 字段  ▴" if self._optional_fields_visible else "更多 UOM 字段  ▾"
        )

    def _kind_button_clicked(self, kind: str) -> None:
        if self._updating or kind == self.current_kind:
            return
        self.current_kind = kind
        self._reload_kind()

    def _element_group(self, element_id: str) -> tuple[str, ...]:
        if element_id.startswith("copy_") and element_id.endswith(("_qr", "_uas")):
            prefix = element_id.rsplit("_", 1)[0]
            return (f"{prefix}_qr", f"{prefix}_uas")
        if element_id in ("info_qr_2", "info_uas_2"):
            return ("info_qr_2", "info_uas_2")
        if element_id.startswith("qr_") or element_id.startswith("uas_"):
            suffix = element_id.rsplit("_", 1)[-1]
            return (f"qr_{suffix}", f"uas_{suffix}")
        if element_id in ("info_qr", "info_uas"):
            return ("info_qr", "info_uas")
        return (element_id,)

    def _reload_kind(self) -> None:
        self.current_kind = self.current_kind if self.current_kind in ("info", "qr") else "info"
        self._updating = True
        self.info_kind_button.setChecked(self.current_kind == "info")
        self.qr_kind_button.setChecked(self.current_kind == "qr")
        self.kind_combo.setCurrentIndex(0 if self.current_kind == "info" else 1)
        self._updating = False
        self.canvas.load(self.template, self.current_kind)
        self.canvas_size_label.setText(
            f"{self.template.paper_width_mm:g} × {self.template.paper_height_mm:g} mm · 安全区 {self.template.safe_margin_mm:g} mm"
        )
        self.element_list.blockSignals(True)
        self.element_list.clear()
        lookup = {entry.id: entry for entry in self.template.elements(self.current_kind)}
        ordered_groups = self._base_groups()
        seen = {group for group, _label in ordered_groups}
        for element in self.template.elements(self.current_kind):
            group = self._element_group(element.id)
            if group in seen:
                continue
            seen.add(group)
            if len(group) > 1:
                label = "▦  二维码 + 登记标识（副本）"
            else:
                label = f"T  {element.label}"
            ordered_groups.append((group, label))
        for group, label in ordered_groups:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, group)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            visible = all(lookup[element_id].visible for element_id in group if element_id in lookup)
            item.setCheckState(Qt.Checked if visible else Qt.Unchecked)
            item.setToolTip("组合元素会一起移动和缩放" if len(group) > 1 else f"调整{label}的位置和大小")
            self.element_list.addItem(item)
        self.element_list.blockSignals(False)
        if hasattr(self, "show_optional_button"):
            self._apply_optional_field_visibility()
        if self.element_list.count():
            self.element_list.setCurrentRow(0)
        self._update_element_actions()

    def _element_visibility_changed(self, item: QListWidgetItem) -> None:
        if self._updating:
            return
        group = item.data(Qt.UserRole)
        element_ids = tuple(group) if isinstance(group, tuple) else (str(group),)
        visible = item.checkState() == Qt.Checked
        lookup = {element.id: element for element in self.template.elements(self.current_kind)}
        states = self._capture_element_states(element_ids)
        for element_id in element_ids:
            element = lookup.get(element_id)
            if element is not None:
                element.visible = visible
        if visible and not self._place_group_without_collision(element_ids):
            self._restore_element_states(states)
            self.element_list.blockSignals(True)
            item.setCheckState(Qt.Unchecked)
            self.element_list.blockSignals(False)
            self._sync_element_ids(element_ids)
            self._show_editor_feedback("安全区空间不足，请先移动、缩小或移除其他元素。", "error")
            return
        self._sync_element_ids(element_ids)
        if element_ids == self.current_group_ids:
            self._updating = True
            self.visible_check.setChecked(visible)
            self._updating = False
        self._show_editor_feedback("元素已添加并自动放到空位。" if visible else "元素已从当前标签隐藏。", "success")

    def _list_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        group = current.data(Qt.UserRole)
        self.current_group_ids = tuple(group) if isinstance(group, tuple) else (str(group),)
        self.canvas.select_elements(self.current_group_ids)

    def _canvas_selected(self, item) -> None:
        self.current_item = item if isinstance(item, ElementItem) else None
        if self.current_item is None:
            self.current_group_ids = ()
            self.selected_title.setText("请选择一个元素")
            self.selected_hint.setText("在画布或上方列表中选择后即可调整。")
            self._update_element_actions()
            return
        element = self.current_item.element
        self.current_group_ids = self._element_group(element.id)
        grouped = len(self.current_group_ids) > 1
        for canvas_item in self.canvas.items_by_id.values():
            canvas_item.configure_interaction()
            canvas_item.setZValue(0)
        if grouped:
            selected_ids = {
                selected.element.id
                for selected in self.canvas.canvas_scene.selectedItems()
                if isinstance(selected, ElementItem)
            }
            if selected_ids != set(self.current_group_ids):
                self.canvas.select_elements(self.current_group_ids, emit=False)
            elements = self._group_elements()
            qr = next((entry for entry in elements if entry.kind == "qr"), None)
            code = next((entry for entry in elements if entry.kind == "text"), None)
            if qr is not None and code is not None:
                qr_item = self.canvas.items_by_id.get(qr.id)
                code_item = self.canvas.items_by_id.get(code.id)
                if qr_item is not None:
                    qr_item.configure_interaction(bottom_reserve_mm=code.height_mm)
                    # The resize handle lives at the QR's lower-right corner,
                    # directly beside the UAS-code row.  Keep the QR above the
                    # paired text item so the handle always receives the drag.
                    qr_item.setZValue(3)
                if code_item is not None:
                    code_item.configure_interaction(movable=False, resizable=False)
                    code_item.setZValue(1)
        else:
            self.current_item.setZValue(2)
        title = "二维码 + 登记标识" if grouped else element.label
        rotation_text = f" · {int(element.rotation_deg) % 360}°" if element.rotation_deg else ""
        self.selected_title.setText(f"已选择：{title}{rotation_text}")
        self.selected_hint.setText("这两个内容会作为一个整体移动和缩放。" if grouped else "可用下面按钮快速调整，也可以展开精确参数。")
        self._updating = True
        self.x_spin.setValue(element.x_mm)
        self.y_spin.setValue(element.y_mm)
        self.w_spin.setMinimum(MIN_SAFE_QR_MM if element.kind == "qr" else 1.0)
        self.h_spin.setMinimum(MIN_SAFE_QR_MM if element.kind == "qr" else 1.0)
        self.w_spin.setValue(element.width_mm)
        self.h_spin.setValue(element.height_mm)
        self.font_spin.setValue(max(MIN_TEXT_SIZE_MM, element.font_size_mm))
        align_index = self.align_combo.findData(element.align)
        self.align_combo.setCurrentIndex(max(0, align_index))
        self.visible_check.setChecked(element.visible)
        self.lock_check.setChecked(element.lock_aspect)
        text_enabled = element.kind == "text" and not grouped
        self.font_spin.setEnabled(text_enabled)
        self.align_combo.setEnabled(text_enabled)
        self.lock_check.setEnabled(element.kind == "qr" and not grouped)
        self.font_smaller.setEnabled(text_enabled)
        self.font_larger.setEnabled(text_enabled)
        self.font_quick_label.setEnabled(text_enabled)
        self.advanced_toggle.setEnabled(not grouped)
        # QR + UAS code is a bound pair.  Rotating only one half would corrupt
        # the layout, so do not leave a grey, apparently broken control visible.
        self.rotate_selected_button.setVisible(not grouped)
        if grouped and self.advanced_panel.isVisible():
            self.advanced_panel.hide()
            self.advanced_toggle.setText("精确位置与对齐  ▾")
        self._updating = False
        self._update_element_actions()
        for row in range(self.element_list.count()):
            list_item = self.element_list.item(row)
            if tuple(list_item.data(Qt.UserRole)) == self.current_group_ids:
                if self.element_list.currentItem() is not list_item:
                    self.element_list.blockSignals(True)
                    self.element_list.setCurrentItem(list_item)
                    self.element_list.blockSignals(False)
                break

    def _update_element_actions(self) -> None:
        has_selection = bool(self._group_elements())
        if hasattr(self, "copy_element_button"):
            self.copy_element_button.setEnabled(has_selection)
            self.remove_element_button.setEnabled(has_selection)
            self.paste_element_button.setEnabled(bool(self._element_clipboard))

    def _place_group_without_collision(self, element_ids: tuple[str, ...]) -> bool:
        lookup = {element.id: element for element in self.template.elements(self.current_kind)}
        elements = [lookup[element_id] for element_id in element_ids if element_id in lookup]
        if not elements:
            return False
        left = min(element.x_mm for element in elements)
        top = min(element.y_mm for element in elements)
        right = max(element.x_mm + element.width_mm for element in elements)
        bottom = max(element.y_mm + element.height_mm for element in elements)
        width, height = right - left, bottom - top
        margin = self.template.safe_margin_mm
        max_left = self.template.paper_width_mm - margin - width
        max_top = self.template.paper_height_mm - margin - height
        if max_left < margin - 0.01 or max_top < margin - 0.01:
            return False
        others = [
            element
            for element in self.template.elements(self.current_kind)
            if element.visible and element.id not in set(element_ids)
        ]

        def fits(candidate_left: float, candidate_top: float) -> bool:
            dx, dy = candidate_left - left, candidate_top - top
            candidates = [
                QRectF(
                    element.x_mm + dx,
                    element.y_mm + dy,
                    element.width_mm,
                    element.height_mm,
                )
                for element in elements
            ]
            return not any(
                LayoutCanvas._collision_area(candidate, LayoutCanvas._rect_for(other)) > 0.0001
                for candidate in candidates
                for other in others
            )

        candidates = [(max(margin, min(left, max_left)), max(margin, min(top, max_top)))]
        step = 0.5
        y = margin
        while y <= max_top + 0.01:
            x = margin
            while x <= max_left + 0.01:
                candidates.append((round(x, 2), round(y, 2)))
                x += step
            y += step
        for candidate_left, candidate_top in candidates:
            if not fits(candidate_left, candidate_top):
                continue
            dx, dy = candidate_left - left, candidate_top - top
            for element in elements:
                element.x_mm = round(element.x_mm + dx, 2)
                element.y_mm = round(element.y_mm + dy, 2)
            return True
        return False

    def _copy_selected(self) -> None:
        elements = self._group_elements()
        if not elements:
            self._show_editor_feedback("请先选择要复制的元素。", "info")
            return
        self._element_clipboard = deepcopy(elements)
        self._update_element_actions()
        self._show_editor_feedback("已复制，点“粘贴”或按 Ctrl+V 即可添加副本。", "success")

    def _next_copy_token(self) -> int:
        existing = {element.id for element in self.template.elements(self.current_kind)}
        token = 1
        while any(element_id.startswith(f"copy_{token}_") for element_id in existing):
            token += 1
        return token

    def _paste_elements(self) -> None:
        if not self._element_clipboard:
            self._show_editor_feedback("还没有复制元素。", "info")
            return
        token = self._next_copy_token()
        copies = deepcopy(self._element_clipboard)
        is_qr_group = len(copies) == 2 and any(element.kind == "qr" for element in copies)
        for index, element in enumerate(copies):
            if is_qr_group:
                element.id = f"copy_{token}_{'qr' if element.kind == 'qr' else 'uas'}"
            else:
                element.id = f"copy_{token}_{index}_{element.id}"
                element.label = f"{element.label} 副本"
            element.visible = True
            element.x_mm += 1.0
            element.y_mm += 1.0
        target = self.template.elements(self.current_kind)
        target.extend(copies)
        new_ids = tuple(element.id for element in copies)
        if not self._place_group_without_collision(new_ids):
            del target[-len(copies) :]
            self._show_editor_feedback("没有足够空位粘贴，请先移动、缩小或移除其他元素。", "error")
            return
        self._reload_kind()
        self._select_group_in_list(new_ids)
        self._show_editor_feedback("副本已添加到安全区空位。", "success")

    def _duplicate_selected(self) -> None:
        if not self._group_elements():
            self._show_editor_feedback("请先选择要复制的元素。", "info")
            return
        self._copy_selected()
        self._paste_elements()

    def _hide_selected_elements(self) -> None:
        elements = self._group_elements()
        if not elements:
            self._show_editor_feedback("请先选择要移除的元素。", "info")
            return
        if not any(element.visible for element in elements):
            self._show_editor_feedback("这个元素已经隐藏了，可在列表里重新勾选。", "info")
            return
        for element in elements:
            element.visible = False
        self._sync_group_items()
        for row in range(self.element_list.count()):
            item = self.element_list.item(row)
            if tuple(item.data(Qt.UserRole)) == self.current_group_ids:
                self.element_list.blockSignals(True)
                item.setCheckState(Qt.Unchecked)
                self.element_list.blockSignals(False)
                break
        self._show_editor_feedback("已从当前标签隐藏，勾选列表即可恢复。", "success")

    def _select_group_in_list(self, element_ids: tuple[str, ...]) -> None:
        for row in range(self.element_list.count()):
            item = self.element_list.item(row)
            if tuple(item.data(Qt.UserRole)) == element_ids:
                self.element_list.setCurrentItem(item)
                return

    def _canvas_geometry_changed(self, item) -> None:
        if not isinstance(item, ElementItem):
            return
        group_ids = self._element_group(item.element.id)
        if len(group_ids) != 2 or item.element.kind != "qr":
            return
        lookup = {element.id: element for element in self.template.elements(self.current_kind)}
        qr = item.element
        code = next((lookup.get(element_id) for element_id in group_ids if lookup.get(element_id) and lookup[element_id].kind == "text"), None)
        if code is None:
            return
        code.x_mm = qr.x_mm
        code.y_mm = qr.y_mm + qr.height_mm
        code.width_mm = qr.width_mm
        code_item = self.canvas.items_by_id.get(code.id)
        if code_item is not None:
            code_item.sync_geometry()
        self.canvas.schedule_demo_preview()

    def _group_elements(self) -> list[LayoutElement]:
        lookup = {element.id: element for element in self.template.elements(self.current_kind)}
        return [lookup[element_id] for element_id in self.current_group_ids if element_id in lookup]

    def _property_changed(self, *_args) -> None:
        if self._updating or self.current_item is None:
            return
        elements = self._group_elements()
        states = self._capture_element_states(self.current_group_ids)
        collision_score = self.canvas.group_collision_score(self.current_group_ids)
        if len(elements) > 1:
            visible = self.visible_check.isChecked()
            for element in elements:
                element.visible = visible
        else:
            element = self.current_item.element
            element.x_mm = self.x_spin.value()
            element.y_mm = self.y_spin.value()
            element.width_mm = self.w_spin.value()
            element.height_mm = self.h_spin.value()
            element.font_size_mm = self.font_spin.value()
            element.align = str(self.align_combo.currentData() or "center")
            element.visible = self.visible_check.isChecked()
            element.lock_aspect = self.lock_check.isChecked() if element.kind == "qr" else False
            if element.lock_aspect and abs(element.width_mm - element.height_mm) > 0.01:
                element.height_mm = element.width_mm
            margin = self.template.safe_margin_mm
            element.x_mm = max(margin, min(element.x_mm, self.template.paper_width_mm - margin - element.width_mm))
            element.y_mm = max(margin, min(element.y_mm, self.template.paper_height_mm - margin - element.height_mm))
        if self._collision_worsened(self.current_group_ids, collision_score):
            self._restore_element_states(states)
            self._sync_group_items()
            self._show_editor_feedback("已碰到其他元素，本次调整没有应用。", "error")
            return
        self._sync_group_items()
        for row in range(self.element_list.count()):
            item = self.element_list.item(row)
            group = item.data(Qt.UserRole)
            ids = tuple(group) if isinstance(group, tuple) else (str(group),)
            if ids == self.current_group_ids:
                self.element_list.blockSignals(True)
                item.setCheckState(Qt.Checked if self.visible_check.isChecked() else Qt.Unchecked)
                self.element_list.blockSignals(False)
                break

    def _sync_group_items(self) -> None:
        for element_id in self.current_group_ids:
            item = self.canvas.items_by_id.get(element_id)
            if item is not None:
                item.sync_geometry()
        self.canvas.schedule_demo_preview()
        if self.current_item is not None:
            self._canvas_selected(self.current_item)

    @staticmethod
    def _element_state(element: LayoutElement) -> dict[str, object]:
        return {
            field: getattr(element, field)
            for field in (
                "x_mm",
                "y_mm",
                "width_mm",
                "height_mm",
                "font_size_mm",
                "align",
                "visible",
                "lock_aspect",
                "rotation_deg",
            )
        }

    def _capture_element_states(self, element_ids: tuple[str, ...]) -> dict[str, dict[str, object]]:
        lookup = {element.id: element for element in self.template.elements(self.current_kind)}
        return {
            element_id: self._element_state(lookup[element_id])
            for element_id in element_ids
            if element_id in lookup
        }

    def _restore_element_states(self, states: dict[str, dict[str, object]]) -> None:
        lookup = {element.id: element for element in self.template.elements(self.current_kind)}
        for element_id, state in states.items():
            element = lookup.get(element_id)
            if element is None:
                continue
            for field, value in state.items():
                setattr(element, field, value)

    def _sync_element_ids(self, element_ids: tuple[str, ...]) -> None:
        for element_id in element_ids:
            canvas_item = self.canvas.items_by_id.get(element_id)
            if canvas_item is not None:
                canvas_item.sync_geometry()
        self.canvas.schedule_demo_preview()

    def _collision_worsened(self, element_ids: tuple[str, ...], previous_score: float) -> bool:
        current_score = self.canvas.group_collision_score(element_ids)
        return current_score > 0.0001 and current_score >= previous_score - 0.0001

    def _nudge_selected(self, dx: float, dy: float) -> None:
        elements = self._group_elements()
        if not elements:
            return
        left = min(element.x_mm for element in elements)
        top = min(element.y_mm for element in elements)
        right = max(element.x_mm + element.width_mm for element in elements)
        bottom = max(element.y_mm + element.height_mm for element in elements)
        margin = self.template.safe_margin_mm
        actual_dx = max(margin - left, min(dx, self.template.paper_width_mm - margin - right))
        actual_dy = max(margin - top, min(dy, self.template.paper_height_mm - margin - bottom))
        states = self._capture_element_states(self.current_group_ids)
        collision_score = self.canvas.group_collision_score(self.current_group_ids)
        for element in elements:
            element.x_mm += actual_dx
            element.y_mm += actual_dy
        if self._collision_worsened(self.current_group_ids, collision_score):
            self._restore_element_states(states)
            self._show_editor_feedback("已碰到其他元素，不能继续移动。", "error")
        elif abs(actual_dx) < 0.001 and abs(actual_dy) < 0.001:
            self._show_editor_feedback("已经到达安全区边缘。", "info")
        else:
            self._show_editor_feedback("位置已调整。", "success")
        self._sync_group_items()

    def _resize_selected(self, delta: float) -> None:
        elements = self._group_elements()
        if not elements:
            self._show_editor_feedback("请先选择要调整的元素。", "info")
            return
        states = self._capture_element_states(self.current_group_ids)
        old_sizes = tuple((element.width_mm, element.height_mm) for element in elements)
        collision_score = self.canvas.group_collision_score(self.current_group_ids)
        if len(elements) == 2 and any(element.kind == "qr" for element in elements):
            qr = next(element for element in elements if element.kind == "qr")
            code = next(element for element in elements if element.kind == "text")
            maximum = min(
                self.template.paper_width_mm - self.template.safe_margin_mm - qr.x_mm,
                self.template.paper_height_mm - self.template.safe_margin_mm - qr.y_mm - code.height_mm,
            )
            side = max(MIN_SAFE_QR_MM, min(qr.width_mm + delta, maximum))
            qr.width_mm = qr.height_mm = side
            code.x_mm = qr.x_mm
            code.y_mm = qr.y_mm + side
            code.width_mm = side
            if self._collision_worsened(self.current_group_ids, collision_score):
                self._restore_element_states(states)
                self._show_editor_feedback("已碰到其他元素，不能继续放大。", "error")
            elif old_sizes == tuple((element.width_mm, element.height_mm) for element in elements):
                self._show_editor_feedback("已经达到二维码安全尺寸或纸张边界。", "info")
            else:
                self._show_editor_feedback("元素已缩放。", "success")
            self._sync_group_items()
            return
        element = elements[0]
        minimum = MIN_SAFE_QR_MM if element.kind == "qr" else 1.0
        margin = self.template.safe_margin_mm
        max_width = self.template.paper_width_mm - margin - element.x_mm
        max_height = self.template.paper_height_mm - margin - element.y_mm
        if element.lock_aspect or element.kind == "qr":
            side = max(minimum, min(element.width_mm + delta, max_width, max_height))
            element.width_mm = element.height_mm = side
        else:
            element.width_mm = max(minimum, min(element.width_mm + delta, max_width))
            element.height_mm = max(minimum, min(element.height_mm + delta, max_height))
        if self._collision_worsened(self.current_group_ids, collision_score):
            self._restore_element_states(states)
            self._show_editor_feedback("已碰到其他元素，不能继续放大。", "error")
        elif old_sizes == tuple((entry.width_mm, entry.height_mm) for entry in elements):
            self._show_editor_feedback("已经达到安全尺寸或纸张边界。", "info")
        else:
            self._show_editor_feedback("元素已缩放。", "success")
        self._sync_group_items()

    def _rotate_selected(self) -> None:
        if self.current_item is None or len(self.current_group_ids) > 1:
            return
        states = self._capture_element_states(self.current_group_ids)
        collision_score = self.canvas.group_collision_score(self.current_group_ids)
        element = self.current_item.element
        element.rotation_deg = (int(element.rotation_deg) + 90) % 360
        if element.kind == "text":
            element.width_mm, element.height_mm = element.height_mm, element.width_mm
            margin = self.template.safe_margin_mm
            element.x_mm = max(margin, min(element.x_mm, self.template.paper_width_mm - margin - element.width_mm))
            element.y_mm = max(margin, min(element.y_mm, self.template.paper_height_mm - margin - element.height_mm))
        if self._collision_worsened(self.current_group_ids, collision_score):
            self._restore_element_states(states)
            self._show_editor_feedback("旋转后会碰到其他元素，本次操作没有应用。", "error")
        self._sync_group_items()

    def _refresh_named_presets(self, selected_name: str | None = None) -> None:
        super()._refresh_named_presets(selected_name)
        self._sync_delete_preset_button()

    def _named_preset_changed(self, _index: int) -> None:
        value = self.saved_preset_combo.currentData()
        path = Path(value) if value else None
        self._active_preset_path = path
        self._editing_current_preset = self._is_initial_active_preset(path)
        super()._named_preset_changed(_index)

    def _save_named_preset(self) -> bool:
        if not super()._save_named_preset():
            return False
        self._active_preset_path = self._last_saved_preset_path
        if hasattr(self, "paper_list"):
            self._refresh_paper_list(self.template.name)
        if hasattr(self, "paper_picker"):
            self.paper_picker.refresh_presets(self.template.name, self._active_preset_path.name)
            self.paper_picker.set_current_paper(
                self.template.paper_width_mm,
                self.template.paper_height_mm,
                self.template.name,
                self._active_preset_path.name,
            )
        self._show_editor_feedback(f"已保存到个人预设：{self.template.name}", "success")
        return True

    def _save(self) -> None:
        entered_name = self.name_edit.text().strip()
        loaded_name = getattr(self, "_loaded_template_name", self.template.name)
        default_name = f"{self.template.paper_width_mm:g}×{self.template.paper_height_mm:g}-我的预设"
        preferred_name = (
            entered_name
            if entered_name
            and (
                self._active_preset_path is not None
                or entered_name != loaded_name
                or getattr(self, "_name_was_explicit", False)
            )
            else default_name
        )
        name = self._unique_preset_name(preferred_name, active_path=self._active_preset_path)
        self.name_edit.setText(name)
        self.template.name = name
        errors = self._validate()
        if errors:
            warning(self, "模板不能保存", "\n".join(errors[:8]))
            return
        safe_name = self._safe_preset_name(name)
        target_path = self.preset_dir / f"{safe_name}.json"
        previous_path = self._active_preset_path
        apply_to_current = self._editing_current_preset
        save_layout_template(self.template, target_path)
        if previous_path is not None and previous_path != target_path and previous_path.is_file():
            previous_path.unlink()
        self._active_preset_path = target_path
        if apply_to_current:
            save_layout_template(self.template, self.template_path)
            self.settings.custom_layout_enabled = True
            self.settings.layout_template_name = self.template.name
            self.settings.layout_preset_file = target_path.name
            self.settings.paper_width_mm = self.template.paper_width_mm
            self.settings.paper_height_mm = self.template.paper_height_mm
            self.store.save(self.settings)
            self._initial_active_preset_path = target_path
            self._editing_current_preset = True
        self._last_save_applied_to_current = apply_to_current
        self.saved_preset_name = name
        self.accept()

    def _current_signature(self):
        def element_signature(element: LayoutElement):
            return tuple(
                getattr(element, field)
                for field in (
                    "id",
                    "label",
                    "kind",
                    "source",
                    "x_mm",
                    "y_mm",
                    "width_mm",
                    "height_mm",
                    "font_size_mm",
                    "align",
                    "visible",
                    "lock_aspect",
                    "rotation_deg",
                )
            )

        return (
            self.name_edit.text().strip(),
            self.template.paper_width_mm,
            self.template.paper_height_mm,
            self.template.safe_margin_mm,
            tuple(element_signature(element) for element in self.template.qr_elements),
            tuple(element_signature(element) for element in self.template.info_elements),
        )

    def has_unsaved_changes(self) -> bool:
        return self._saved_signature is not None and self._current_signature() != self._saved_signature

    def _prompt_unsaved_changes(self) -> str:
        return choose(
            self,
            "保存这次排版吗？",
            "标签位置或尺寸已经调整，返回前还没有保存。",
            detail="保存后会加入“我的预设”；不保存会恢复进入编辑页前的排版。",
            kind="warning",
            actions=(
                ("cancel", "继续编辑", "secondary"),
                ("discard", "不保存", "danger-secondary"),
                ("save", "保存并返回", "primary"),
            ),
            default_action="save",
        )

    def _confirm_close(self) -> bool:
        if not self.has_unsaved_changes():
            return True
        decision = self._prompt_unsaved_changes()
        if decision == "save":
            self._save()
            return False
        return decision == "discard"

    def accept(self) -> None:
        self._saved_signature = self._current_signature()
        super().accept()

    def reject(self) -> None:
        if self._confirm_close():
            super().reject()


class LayoutEditorPage(LayoutEditorDialog):
    """The editor hosted inside the main window instead of a modal dialog."""

    close_requested = Signal()

    def __init__(self, settings: AppSettings, store: SettingsStore, parent=None, *, template_path: Path | None = None) -> None:
        super().__init__(settings, store, parent, template_path=template_path)
        self.preset_saved = False
        self.preset_applied = False
        self.saved_preset_name = ""
        self.setWindowFlags(Qt.Widget)
        self.setObjectName("LayoutEditorPage")
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def accept(self) -> None:
        self._saved_signature = self._current_signature()
        self.preset_saved = True
        self.preset_applied = bool(self._last_save_applied_to_current)
        self.close_requested.emit()

    def reject(self) -> None:
        if self._confirm_close():
            self.close_requested.emit()
