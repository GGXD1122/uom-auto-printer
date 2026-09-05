from __future__ import annotations

from pathlib import Path

import fitz
import pytest
import zxingcpp
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton

from uom_printer.label_renderer import mm_to_px, render_info_label, render_qr_label, save_pdf
from uom_printer.layout_template import (
    DEFAULT_PRESET_PROFILES,
    MIN_SAFE_QR_MM,
    MIN_TEXT_SIZE_MM,
    PAPER_PRESETS,
    LayoutElement,
    default_layout_template,
    element_text,
    load_layout_template,
    layout_issues,
    rotate_layout,
    save_layout_template,
)
from uom_printer.models import UomRecord
from uom_printer.settings import AppSettings, SettingsStore
from uom_printer.ui.layout_editor import LayoutCanvas, LayoutEditorDialog, LayoutEditorPage, RoundedNameComboBox
from uom_printer.ui.rounded_dialog import RoundedMessageDialog
from uom_printer.ui.styles import APP_STYLE
from uom_printer.uom_service import qr_image_from_payload


PAYLOAD = "https://uom.caac.gov.cn/#/uav-regist-show/00000000-0000-4000-8000-000000000001"


def sample_record() -> UomRecord:
    return UomRecord(
        "UOM-DEMO-2026",
        "DJI Air 3S 畅飞套装（DJI RC 2）",
        "1581FDEMO00000000001",
        "演示用户",
        phone_number="13800000000",
        empty_weight="724 g",
        qr_payload=PAYLOAD,
    )


def test_optional_uom_fields_render_with_readable_labels() -> None:
    record = sample_record()
    record.manufacturer = "大疆创新"
    record.maximum_takeoff_weight = "1.4 kg"
    assert element_text(LayoutElement("m", "制造商", "text", "manufacturer_label", 0, 0, 20, 4), record) == "制造商 大疆创新"
    assert element_text(LayoutElement("w", "最大起飞重量", "text", "maximum_takeoff_weight_label", 0, 0, 20, 4), record) == "最大起飞重量 1.4 kg"


def test_all_safe_presets_keep_every_visible_element_inside_paper() -> None:
    assert len(PAPER_PRESETS) == 19
    assert set(DEFAULT_PRESET_PROFILES) == {(width, height) for _label, width, height in PAPER_PRESETS}
    for _label, width, height in PAPER_PRESETS:
        template = default_layout_template(width, height)
        assert layout_issues(template) == []
        for element in template.qr_elements + template.info_elements:
            assert element.x_mm >= 0
            assert element.y_mm >= 0
            assert element.x_mm + element.width_mm <= width + 0.01
            assert element.y_mm + element.height_mm <= height + 0.01
            if element.kind == "qr":
                assert min(element.width_mm, element.height_mm) >= MIN_SAFE_QR_MM
            else:
                assert element.font_size_mm >= MIN_TEXT_SIZE_MM


def test_portrait_preset_stacks_the_two_qr_codes() -> None:
    template = default_layout_template(40, 60)
    first, second = (next(item for item in template.qr_elements if item.id == item_id) for item_id in ("qr_1", "qr_2"))
    assert first.x_mm == pytest.approx(second.x_mm)
    assert second.y_mm > first.y_mm + first.height_mm


def test_rotate_layout_swaps_paper_and_rotates_every_element() -> None:
    template = default_layout_template(60, 40)
    rotate_layout(template)
    assert (template.paper_width_mm, template.paper_height_mm) == (40, 60)
    for element in template.qr_elements + template.info_elements:
        assert element.rotation_deg == 90
        assert element.x_mm >= 0 and element.y_mm >= 0
        assert element.x_mm + element.width_mm <= 40.01
        assert element.y_mm + element.height_mm <= 60.01


def test_rotated_layout_keeps_qr_codes_decodable_at_203_dpi() -> None:
    template = default_layout_template(60, 40)
    rotate_layout(template)
    rendered = render_qr_label(qr_image_from_payload(PAYLOAD), sample_record(), 600, layout=template)
    low_dpi = rendered.resize((mm_to_px(40, 203), mm_to_px(60, 203)), Image.Resampling.LANCZOS)
    for element in (item for item in template.qr_elements if item.kind == "qr"):
        crop = low_dpi.crop(
            (
                mm_to_px(element.x_mm, 203),
                mm_to_px(element.y_mm, 203),
                mm_to_px(element.x_mm + element.width_mm, 203),
                mm_to_px(element.y_mm + element.height_mm, 203),
            )
        )
        decoded = zxingcpp.read_barcode(crop, formats=zxingcpp.BarcodeFormat.QRCode)
        assert decoded is not None
        assert decoded.text == PAYLOAD


def test_small_40x30_info_layout_reserves_full_width_model_and_serial_rows() -> None:
    template = default_layout_template(40, 30)
    model = next(item for item in template.info_elements if item.id == "model")
    serial = next(item for item in template.info_elements if item.id == "serial")
    assert model.width_mm == pytest.approx(40 - template.safe_margin_mm * 2)
    assert serial.width_mm == pytest.approx(model.width_mm)
    assert serial.y_mm > model.y_mm


def test_template_json_round_trip_and_invalid_size_clamping(tmp_path: Path) -> None:
    path = tmp_path / "layout.json"
    template = default_layout_template(70, 50)
    template.name = "维修台模板"
    template.info_elements[0].x_mm = 3.5
    template.info_elements[0].rotation_deg = 90
    save_layout_template(template, path)
    restored = load_layout_template(path)
    assert restored.name == "维修台模板"
    assert restored.paper_width_mm == 70
    assert restored.info_elements[0].x_mm == 3.5
    assert restored.info_elements[0].rotation_deg == 90

    path.write_text('{"paper_width_mm": 5, "paper_height_mm": 6}', encoding="utf-8")
    clamped = load_layout_template(path)
    assert (clamped.paper_width_mm, clamped.paper_height_mm) == (10, 10)
    path.write_text('{"paper_width_mm": 250, "paper_height_mm": 240}', encoding="utf-8")
    clamped = load_layout_template(path)
    assert (clamped.paper_width_mm, clamped.paper_height_mm) == (200, 200)


def test_custom_render_and_pdf_use_selected_physical_size(tmp_path: Path) -> None:
    dpi = 300
    template = default_layout_template(50, 40)
    qr = qr_image_from_payload(PAYLOAD)
    qr_label = render_qr_label(qr, sample_record(), dpi, layout=template)
    info_label = render_info_label(qr, sample_record(), dpi, layout=template)
    expected = (mm_to_px(50, dpi), mm_to_px(40, dpi))
    assert qr_label.size == info_label.size == expected
    assert qr_label.info["dpi"] == (dpi, dpi)

    pdf_path = tmp_path / "custom.pdf"
    save_pdf(info_label, pdf_path)
    with fitz.open(pdf_path) as document:
        page = document[0]
        assert page.rect.width == pytest.approx(50 / 25.4 * 72, abs=0.2)
        assert page.rect.height == pytest.approx(40 / 25.4 * 72, abs=0.2)


@pytest.mark.parametrize("paper_size", [(width, height) for _label, width, height in PAPER_PRESETS])
def test_smallest_safe_presets_still_decode_at_203_dpi(paper_size: tuple[int, int]) -> None:
    width, height = paper_size
    template = default_layout_template(width, height)
    rendered = render_qr_label(qr_image_from_payload(PAYLOAD), sample_record(), 600, layout=template)
    low_dpi = rendered.resize((mm_to_px(width, 203), mm_to_px(height, 203)), Image.Resampling.LANCZOS)
    for element in (item for item in template.qr_elements if item.kind == "qr"):
        crop = low_dpi.crop(
            (
                max(0, mm_to_px(element.x_mm, 203) - 2),
                max(0, mm_to_px(element.y_mm, 203) - 2),
                min(low_dpi.width, mm_to_px(element.x_mm + element.width_mm, 203) + 2),
                min(low_dpi.height, mm_to_px(element.y_mm + element.height_mm, 203) + 2),
            )
        )
        decoded = zxingcpp.read_barcode(crop, formats=zxingcpp.BarcodeFormat.QRCode)
        assert decoded is not None
        assert decoded.text == PAYLOAD


@pytest.mark.parametrize("paper_size", [(40, 30), (50, 30), (57, 30), (60, 30)])
def test_30mm_high_presets_keep_phone_and_hide_secondary_weight_row(paper_size: tuple[int, int]) -> None:
    template = default_layout_template(*paper_size)
    visible = {element.id for element in template.info_elements if element.visible}
    assert {"info_qr", "info_uas", "owner", "phone", "model", "serial"} <= visible
    assert "weight" not in visible


def test_layout_editor_starts_with_native_scene_and_all_presets(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    store = SettingsStore(tmp_path / "settings.json")
    dialog = LayoutEditorDialog(AppSettings(), store, template_path=tmp_path / "layout.json")
    try:
        assert dialog.paper_combo.count() == len(PAPER_PRESETS) + 1
        assert dialog.paper_list.count() == len(PAPER_PRESETS)
        assert dialog.canvas.canvas_scene.sceneRect().width() == 60
        assert dialog.current_kind == "info"
        assert dialog.element_list.count() == 13
        optional_rows = {
            dialog.element_list.item(row).text(): dialog.element_list.item(row).checkState()
            for row in range(dialog.element_list.count())
        }
        assert optional_rows["T  制造商"] == Qt.Unchecked
        assert optional_rows["T  产品型号"] == Qt.Unchecked
        assert optional_rows["T  最大起飞重量"] == Qt.Unchecked
        assert optional_rows["T  登记时间"] == Qt.Unchecked
        assert optional_rows["T  登记状态"] == Qt.Unchecked
        assert optional_rows["T  主体类型"] == Qt.Unchecked
        assert dialog.element_list.item(0).text() == "▦  二维码 + 登记标识 1"
        info_element_labels = [dialog.element_list.item(row).text() for row in range(dialog.element_list.count())]
        assert not any(button.text() == "↻  整张旋转 90°" for button in dialog.findChildren(QPushButton))
        assert not any(check.text() == "在标签中显示这个元素" for check in dialog.findChildren(QCheckBox))
        assert dialog.visible_check.isHidden()
        assert {item.element.id for item in dialog.canvas.canvas_scene.selectedItems()} == {"info_qr", "info_uas"}
        portrait = next(
            dialog.paper_list.item(row)
            for row in range(dialog.paper_list.count())
            if dialog.paper_list.item(row).data(Qt.UserRole) == (40.0, 60.0)
        )
        dialog.paper_list.setCurrentItem(portrait)
        dialog.qr_kind_button.click()
        app.processEvents()
        assert dialog.current_kind == "qr"
        assert dialog.canvas.preview_item is not None
        assert not dialog.canvas.preview_item.pixmap().isNull()
        assert dialog.element_list.count() == 13
        assert [dialog.element_list.item(row).text() for row in range(dialog.element_list.count())] == info_element_labels
        assert dialog.canvas.canvas_scene.sceneRect().size().toSize().width() == 40
        assert {item.element.id for item in dialog.canvas.canvas_scene.selectedItems()} == {"qr_1", "uas_1"}
        assert not dialog.advanced_panel.isVisible()
        dialog.name_edit.setText("演示维修台")
        dialog._save_named_preset()
        saved_paths = list((tmp_path / "layout-presets").glob("*.json"))
        assert len(saved_paths) == 1
        assert layout_issues(load_layout_template(saved_paths[0])) == []
        assert dialog.saved_preset_combo.currentText() == "演示维修台"
    finally:
        dialog.close()
        app.processEvents()


def test_editor_grid_is_optional_but_safe_area_remains(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        assert dialog.grid_button.isChecked() is False
        assert dialog.canvas.grid_items
        assert all(not item.isVisible() for item in dialog.canvas.grid_items)
        green_safe_items = [
            item for item in dialog.canvas.canvas_scene.items()
            if hasattr(item, "pen") and item.pen().color().name().lower() == "#21b573"
        ]
        assert green_safe_items and all(item.isVisible() for item in green_safe_items)
        dialog.grid_button.click()
        assert all(item.isVisible() for item in dialog.canvas.grid_items)
    finally:
        dialog.close()
        app.processEvents()


def test_custom_size_commits_typed_text_and_shows_feedback(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        dialog.width_spin.lineEdit().setText("55.5")
        dialog.height_spin.lineEdit().setText("35.5")
        dialog._custom_paper_changed()
        assert dialog.template.paper_width_mm == pytest.approx(55.5)
        assert dialog.template.paper_height_mm == pytest.approx(35.5)
        assert "55.5" in dialog.custom_size_feedback.text()
        assert not dialog.preset_feedback.isHidden()
    finally:
        dialog.close()
        app.processEvents()


def test_preset_settings_combines_name_size_and_real_rename(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    dialog.show()
    app.processEvents()
    try:
        assert dialog.preset_settings_button.text() == "编辑尺寸"
        assert dialog.preset_settings_panel.isHidden()
        button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
        assert "自定义尺寸" not in button_texts
        assert "预设命名" not in button_texts

        QTest.mouseClick(dialog.preset_settings_button, Qt.LeftButton)
        assert dialog.preset_settings_panel.isVisible()
        assert dialog.preset_settings_button.text() == "收起"
        assert dialog.saved_preset_combo.isVisible()
        assert dialog.saved_preset_combo.width() <= 360
        assert dialog.delete_preset_button.isEnabled() is False

        dialog.name_edit.setText("维修台旧版")
        dialog.width_spin.lineEdit().setText("70")
        dialog.height_spin.lineEdit().setText("40")
        QTest.mouseClick(dialog.apply_custom_button, Qt.LeftButton)
        assert dialog.name_edit.text() == "维修台旧版"
        assert dialog.preset_settings_panel.isVisible()
        dialog._save_named_preset()
        old_path = tmp_path / "layout-presets" / "维修台旧版.json"
        assert old_path.is_file()

        dialog.name_edit.setText("维修台新版")
        dialog._save()
        new_path = tmp_path / "layout-presets" / "维修台新版.json"
        assert new_path.is_file()
        assert not old_path.exists()
    finally:
        dialog.close()
        app.processEvents()


def test_custom_size_accepts_200_square_and_rejects_out_of_range_text(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        dialog.width_spin.lineEdit().setText("200")
        dialog.height_spin.lineEdit().setText("200")
        dialog._custom_paper_changed()
        assert (dialog.template.paper_width_mm, dialog.template.paper_height_mm) == (200.0, 200.0)
        dialog.width_spin.lineEdit().setText("201")
        dialog._custom_paper_changed()
        assert (dialog.template.paper_width_mm, dialog.template.paper_height_mm) == (200.0, 200.0)
        assert dialog.width_spin.property("invalid") is True
        assert dialog.custom_size_feedback.property("state") == "error"
        assert "10–200" in dialog.custom_size_feedback.text()
    finally:
        dialog.close()
        app.processEvents()


def test_editor_blocks_mouse_button_and_precise_input_collisions(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        dialog.canvas.select_element("owner")
        app.processEvents()
        owner = next(element for element in dialog.template.info_elements if element.id == "owner")
        phone = next(element for element in dialog.template.info_elements if element.id == "phone")
        owner_item = dialog.canvas.items_by_id["owner"]
        start = (owner.x_mm, owner.y_mm, owner.width_mm, owner.height_mm)

        owner_item.setPos(phone.x_mm, phone.y_mm)
        assert (owner.x_mm, owner.y_mm, owner.width_mm, owner.height_mm) == start

        dialog._nudge_selected(phone.x_mm - owner.x_mm, phone.y_mm - owner.y_mm)
        assert (owner.x_mm, owner.y_mm, owner.width_mm, owner.height_mm) == start

        dialog.x_spin.setValue(phone.x_mm)
        dialog.y_spin.setValue(phone.y_mm)
        assert not dialog.canvas.group_has_collision(("owner",))

        dialog._resize_selected(100.0)
        assert not dialog.canvas.group_has_collision(("owner",))
        assert dialog.preset_feedback.property("state") == "error"
    finally:
        dialog.close()
        app.processEvents()


def test_mouse_drag_follows_through_collision_and_auto_places_on_release(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    dialog.resize(1180, 740)
    dialog.show()
    app.processEvents()
    try:
        for element in dialog.template.info_elements:
            element.visible = element.id in {"owner", "phone"}
        dialog._reload_kind()
        dialog.canvas.select_element("owner")
        app.processEvents()

        owner = next(element for element in dialog.template.info_elements if element.id == "owner")
        phone = next(element for element in dialog.template.info_elements if element.id == "phone")
        owner_item = dialog.canvas.items_by_id["owner"]
        press_scene = owner_item.mapToScene(owner_item.rect().center())
        overlap_scene = QPointF(phone.x_mm + owner.width_mm / 2, phone.y_mm + owner.height_mm / 2)
        press_point = dialog.canvas.mapFromScene(press_scene)
        overlap_point = dialog.canvas.mapFromScene(overlap_scene)

        QTest.mousePress(dialog.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, press_point)
        QTest.mouseMove(dialog.canvas.viewport(), overlap_point, 40)
        app.processEvents()
        assert owner_item._dragging
        assert owner_item._collision_active
        assert owner.y_mm == pytest.approx(phone.y_mm, abs=0.35)

        QTest.mouseRelease(dialog.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, overlap_point)
        app.processEvents()
        assert not owner_item._dragging
        assert not owner_item._collision_active
        assert not dialog.canvas.group_has_collision(("owner",))
        assert owner.y_mm >= phone.y_mm + phone.height_mm + 0.4
        assert "自动避开" in dialog.preset_feedback.text()
    finally:
        dialog._saved_signature = dialog._current_signature()
        dialog.close()
        app.processEvents()


def test_legacy_overlapping_preset_can_only_move_toward_separation(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        owner = next(element for element in dialog.template.info_elements if element.id == "owner")
        phone = next(element for element in dialog.template.info_elements if element.id == "phone")
        owner.y_mm = phone.y_mm
        owner.x_mm = phone.x_mm
        owner_item = dialog.canvas.items_by_id["owner"]
        owner_item.sync_geometry()
        initial_score = dialog.canvas.group_collision_score(("owner",))
        assert initial_score > 0

        owner_item.setPos(owner.x_mm, owner.y_mm - 0.5)
        reduced_score = dialog.canvas.group_collision_score(("owner",))
        assert 0 < reduced_score < initial_score
        accepted_y = owner.y_mm

        owner_item.setPos(phone.x_mm, phone.y_mm)
        assert owner.y_mm == accepted_y
        assert dialog.canvas.group_collision_score(("owner",)) == pytest.approx(reduced_score)
    finally:
        dialog.close()
        app.processEvents()


def test_editor_demo_uses_real_air_3s_model_and_weight() -> None:
    assert LayoutCanvas.DEMO_RECORD.model_name == "DJI Air 3S 畅飞套装（DJI RC 2）"
    assert LayoutCanvas.DEMO_RECORD.empty_weight == "724 g"
    assert "长续航" not in LayoutCanvas.DEMO_RECORD.model_name


def test_editor_can_hide_required_elements_and_save_layout(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        for element_id in ("model", "serial"):
            element = next(entry for entry in dialog.template.info_elements if entry.id == element_id)
            element.visible = False
        assert layout_issues(dialog.template) == []
        dialog.name_edit.setText("精简标签")
        dialog._save()
        assert not (tmp_path / "layout.json").is_file()
        saved = tmp_path / "layout-presets" / "精简标签.json"
        assert saved.is_file()
        assert load_layout_template(saved).name == "精简标签"
        assert not (tmp_path / "settings.json").is_file()
        restored = load_layout_template(saved)
        assert not next(entry for entry in restored.info_elements if entry.id == "model").visible
        assert not next(entry for entry in restored.info_elements if entry.id == "serial").visible
    finally:
        dialog.close()
        app.processEvents()


def test_hidden_element_is_automatically_placed_in_a_free_area(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        serial = next(entry for entry in dialog.template.info_elements if entry.id == "serial")
        serial.visible = False
        manufacturer = next(entry for entry in dialog.template.info_elements if entry.id == "manufacturer")
        owner = next(entry for entry in dialog.template.info_elements if entry.id == "owner")
        manufacturer.x_mm, manufacturer.y_mm = owner.x_mm, owner.y_mm
        old_position = (manufacturer.x_mm, manufacturer.y_mm)
        dialog._reload_kind()
        manufacturer_row = next(
            dialog.element_list.item(row)
            for row in range(dialog.element_list.count())
            if tuple(dialog.element_list.item(row).data(Qt.UserRole)) == ("manufacturer",)
        )
        manufacturer_row.setCheckState(Qt.Checked)
        app.processEvents()
        assert manufacturer.visible
        assert (manufacturer.x_mm, manufacturer.y_mm) != old_position
        assert not dialog.canvas.group_has_collision(("manufacturer",))
    finally:
        dialog.close()
        app.processEvents()


def test_delete_copy_paste_and_resize_interactions(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    dialog.resize(1180, 740)
    dialog.show()
    app.processEvents()
    try:
        dialog.canvas.select_element("serial")
        app.processEvents()
        dialog.element_list.setFocus()
        QTest.keyClick(dialog.element_list, Qt.Key_Delete)
        app.processEvents()
        serial = next(entry for entry in dialog.template.info_elements if entry.id == "serial")
        assert not serial.visible

        dialog.canvas.select_element("owner")
        app.processEvents()
        owner = next(entry for entry in dialog.template.info_elements if entry.id == "owner")
        old_size = (owner.width_mm, owner.height_mm)
        QTest.mouseClick(dialog.smaller_element_button, Qt.LeftButton)
        assert (owner.width_mm, owner.height_mm) != old_size

        owner_item = dialog.canvas.items_by_id["owner"]
        drag_before = (owner.width_mm, owner.height_mm)
        scene_start = owner_item.mapToScene(owner_item.rect().bottomRight() - QPointF(0.5, 0.5))
        scene_end = scene_start - QPointF(0.6, 0.6)
        start_point = dialog.canvas.mapFromScene(scene_start)
        end_point = dialog.canvas.mapFromScene(scene_end)
        QTest.mousePress(dialog.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, start_point)
        QTest.mouseMove(dialog.canvas.viewport(), end_point, 30)
        QTest.mouseRelease(dialog.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, end_point)
        app.processEvents()
        assert (owner.width_mm, owner.height_mm) != drag_before

        QTest.mouseClick(dialog.copy_element_button, Qt.LeftButton)
        assert dialog._element_clipboard
        before_ids = {entry.id for entry in dialog.template.info_elements}
        dialog.element_list.setFocus()
        QTest.keyClick(dialog.element_list, Qt.Key_V, Qt.ControlModifier)
        app.processEvents()
        after_ids = {entry.id for entry in dialog.template.info_elements}
        new_ids = after_ids - before_ids
        assert new_ids
        assert all(next(entry for entry in dialog.template.info_elements if entry.id == element_id).visible for element_id in new_ids)
        assert not dialog.canvas.group_has_collision(tuple(new_ids))

        dialog.current_kind = "qr"
        dialog._reload_kind()
        dialog.canvas.select_elements(("qr_1", "uas_1"))
        qr = next(entry for entry in dialog.template.qr_elements if entry.id == "qr_1")
        old_qr_size = qr.width_mm
        QTest.mouseClick(dialog.smaller_element_button, Qt.LeftButton)
        assert qr.width_mm == pytest.approx(old_qr_size - 1.0)
        assert next(entry for entry in dialog.template.qr_elements if entry.id == "uas_1").width_mm == pytest.approx(qr.width_mm)
    finally:
        dialog._saved_signature = dialog._current_signature()
        dialog.close()
        app.processEvents()


def test_canvas_keyboard_copy_paste_and_backspace_are_reliable(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    dialog.resize(1180, 740)
    dialog.show()
    app.processEvents()
    try:
        for element in dialog.template.info_elements:
            element.visible = element.id == "owner"
        dialog._reload_kind()
        dialog.canvas.select_element("owner")
        dialog.canvas.viewport().setFocus()
        app.processEvents()

        QTest.keyClick(dialog.canvas.viewport(), Qt.Key_C, Qt.ControlModifier)
        assert [element.id for element in dialog._element_clipboard] == ["owner"]

        before_ids = {element.id for element in dialog.template.info_elements}
        QTest.keyClick(dialog.canvas.viewport(), Qt.Key_V, Qt.ControlModifier)
        app.processEvents()
        new_ids = {element.id for element in dialog.template.info_elements} - before_ids
        assert len(new_ids) == 1
        pasted = next(element for element in dialog.template.info_elements if element.id in new_ids)
        assert pasted.visible
        assert not dialog.canvas.group_has_collision((pasted.id,))

        dialog.canvas.viewport().setFocus()
        QTest.keyClick(dialog.canvas.viewport(), Qt.Key_Backspace)
        app.processEvents()
        assert not pasted.visible
        assert "隐藏" in dialog.action_feedback.text()

        owner = next(element for element in dialog.template.info_elements if element.id == "owner")
        dialog.canvas.select_element("owner")
        dialog.name_edit.setText("预设名称")
        dialog.name_edit.setFocus()
        QTest.keyClick(dialog.name_edit, Qt.Key_Backspace)
        app.processEvents()
        assert dialog.name_edit.text() == "预设名"
        assert owner.visible
    finally:
        dialog._saved_signature = dialog._current_signature()
        dialog.close()
        app.processEvents()


def test_qr_group_buttons_and_real_resize_handle_are_interactive(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(
        AppSettings(),
        SettingsStore(tmp_path / "settings.json"),
        template_path=tmp_path / "layout.json",
    )
    dialog.resize(1180, 740)
    dialog.show()
    app.processEvents()
    try:
        dialog.canvas.select_elements(("info_qr", "info_uas"))
        app.processEvents()
        qr = next(entry for entry in dialog.template.info_elements if entry.id == "info_qr")
        uas = next(entry for entry in dialog.template.info_elements if entry.id == "info_uas")
        qr_item = dialog.canvas.items_by_id["info_qr"]
        uas_item = dialog.canvas.items_by_id["info_uas"]

        assert qr_item.zValue() > uas_item.zValue()
        assert not dialog.rotate_selected_button.isVisible()

        original_side = qr.width_mm
        QTest.mouseClick(dialog.smaller_element_button, Qt.LeftButton)
        app.processEvents()
        assert qr.width_mm == pytest.approx(original_side - 1.0)
        assert uas.width_mm == pytest.approx(qr.width_mm)
        assert "缩放" in dialog.action_feedback.text()

        QTest.mouseClick(dialog.larger_element_button, Qt.LeftButton)
        app.processEvents()
        assert qr.width_mm == pytest.approx(original_side)
        assert uas.y_mm == pytest.approx(qr.y_mm + qr.height_mm)

        drag_before = qr.width_mm
        local_handle = qr_item.rect().bottomRight() - QPointF(1.3, 1.3)
        scene_start = qr_item.mapToScene(local_handle)
        scene_end = scene_start - QPointF(2.0, 2.0)
        start_point = dialog.canvas.mapFromScene(scene_start)
        end_point = dialog.canvas.mapFromScene(scene_end)
        assert dialog.canvas.items(start_point)[0] is qr_item
        QTest.mousePress(dialog.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, start_point)
        assert qr_item._resizing
        QTest.mouseMove(dialog.canvas.viewport(), end_point, 40)
        QTest.mouseRelease(dialog.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, end_point)
        app.processEvents()
        assert qr.width_mm < drag_before
        assert qr.width_mm == pytest.approx(qr.height_mm)
        assert uas.width_mm == pytest.approx(qr.width_mm)
        assert uas.y_mm == pytest.approx(qr.y_mm + qr.height_mm)

        QTest.mouseClick(dialog.remove_element_button, Qt.LeftButton)
        app.processEvents()
        assert not qr.visible and not uas.visible
        assert "隐藏" in dialog.action_feedback.text()
    finally:
        dialog._saved_signature = dialog._current_signature()
        dialog.close()
        app.processEvents()


def test_qr_group_duplicate_button_adds_a_real_pair_when_space_exists(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(
        AppSettings(),
        SettingsStore(tmp_path / "settings.json"),
        template_path=tmp_path / "layout.json",
    )
    dialog.resize(1180, 740)
    dialog.show()
    app.processEvents()
    try:
        # Free the right side so the duplicate command can be verified through
        # a real button click instead of by calling an internal method.
        for element in dialog.template.info_elements:
            if element.id not in {"info_qr", "info_uas"}:
                element.visible = False
        dialog._reload_kind()
        dialog.canvas.select_elements(("info_qr", "info_uas"))
        app.processEvents()
        before_ids = {entry.id for entry in dialog.template.info_elements}

        QTest.mouseClick(dialog.copy_element_button, Qt.LeftButton)
        app.processEvents()

        after_ids = {entry.id for entry in dialog.template.info_elements}
        new_ids = tuple(after_ids - before_ids)
        assert len(new_ids) == 2
        assert any(element_id.endswith("_qr") for element_id in new_ids)
        assert any(element_id.endswith("_uas") for element_id in new_ids)
        assert not dialog.canvas.group_has_collision(new_ids)
        assert "副本已添加" in dialog.action_feedback.text()
    finally:
        dialog._saved_signature = dialog._current_signature()
        dialog.close()
        app.processEvents()


def test_personal_preset_popup_is_rounded_and_constrained(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    dialog.show()
    app.processEvents()
    try:
        assert isinstance(dialog.saved_preset_combo, RoundedNameComboBox)
        dialog.saved_preset_combo.showPopup()
        app.processEvents()
        popup = dialog.saved_preset_combo._popup
        assert popup.isVisible()
        assert popup.objectName() == "NamedPresetPopupWindow"
        assert not popup.mask().isEmpty()
        assert popup.height() <= 280
    finally:
        dialog.saved_preset_combo.hidePopup()
        dialog.close()
        app.processEvents()


def test_default_preset_names_include_size_and_avoid_duplicates(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    first = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    second = None
    try:
        assert first._save_named_preset() is True
        assert (tmp_path / "layout-presets" / "60×40-我的预设.json").is_file()
        second = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
        assert second._save_named_preset() is True
        assert (tmp_path / "layout-presets" / "60×40-我的预设1.json").is_file()
        assert second.template.name == "60×40-我的预设1"
    finally:
        first.close()
        if second is not None:
            second.close()
        app.processEvents()


def test_edit_size_panel_lists_and_deletes_personal_presets(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        dialog.name_edit.setText("临时打印预设")
        assert dialog._save_named_preset() is True
        saved_path = tmp_path / "layout-presets" / "临时打印预设.json"
        assert saved_path.is_file()
        assert dialog.saved_preset_combo.currentData() == saved_path
        assert dialog.delete_preset_button.isEnabled()

        monkeypatch.setattr("uom_printer.ui.layout_editor.confirm_danger", lambda *args, **kwargs: True)
        dialog._delete_selected_preset()

        assert not saved_path.exists()
        assert dialog.saved_preset_combo.currentData() is None
        assert dialog.delete_preset_button.isEnabled() is False
        assert dialog.template.name == "60×40 安全预设"
    finally:
        dialog.close()
        app.processEvents()


def test_personal_presets_can_switch_repeatedly_then_delete_without_blank_canvas(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        dialog.name_edit.setText("快速切换A")
        assert dialog._save_named_preset() is True
        dialog.name_edit.setText("快速切换B")
        assert dialog._save_named_preset() is True

        for _ in range(12):
            for index in range(dialog.saved_preset_combo.count()):
                dialog.saved_preset_combo.setCurrentIndex(index)
                dialog._named_preset_changed(index)
                app.processEvents()
                assert dialog.canvas.preview_item is not None
                assert not dialog.canvas.preview_item.pixmap().isNull()
                assert dialog.canvas.items_by_id
                assert all(item.scene() is dialog.canvas.canvas_scene for item in dialog.canvas.grid_items)

        monkeypatch.setattr("uom_printer.ui.layout_editor.confirm_danger", lambda *args, **kwargs: True)
        dialog._delete_selected_preset()
        app.processEvents()
        assert dialog.canvas.preview_item is not None
        assert not dialog.canvas.preview_item.pixmap().isNull()
        assert dialog.canvas.items_by_id
    finally:
        dialog.close()
        app.processEvents()


def test_embedded_editor_prompts_before_discarding_unsaved_changes(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    page = LayoutEditorPage(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    closed: list[bool] = []
    page.close_requested.connect(lambda: closed.append(True))
    try:
        page.canvas.select_element("owner")
        page._resize_selected(-0.5)
        assert page.has_unsaved_changes()
        monkeypatch.setattr(page, "_prompt_unsaved_changes", lambda: "cancel")
        page.reject()
        assert closed == []
        monkeypatch.setattr(page, "_prompt_unsaved_changes", lambda: "discard")
        page.reject()
        assert closed == [True]
    finally:
        page._saved_signature = page._current_signature()
        page.close()
        app.processEvents()


def test_layout_editors_do_not_show_ineffective_center_view_button(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    page = LayoutEditorPage(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    try:
        assert not any(button.text() == "居中显示" for button in page.findChildren(QPushButton))
    finally:
        page.close()
        app.processEvents()


def test_window_mode_canvas_uses_available_center_space(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = LayoutEditorDialog(AppSettings(), SettingsStore(tmp_path / "settings.json"), template_path=tmp_path / "layout.json")
    dialog.resize(1080, 700)
    dialog.show()
    app.processEvents()
    try:
        paper_rect = dialog.canvas.mapFromScene(dialog.canvas.canvas_scene.sceneRect()).boundingRect()
        assert paper_rect.width() >= 430
        assert paper_rect.height() >= 285
    finally:
        dialog.close()
        app.processEvents()


def test_unsaved_choice_dialog_has_clear_three_button_hierarchy() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = RoundedMessageDialog(
        None,
        "保存这次排版吗？",
        "标签位置或尺寸已经调整，返回前还没有保存。",
        detail="保存后会加入“我的预设”；不保存会恢复进入编辑页前的排版。",
        kind="warning",
        action_specs=(
            ("cancel", "继续编辑", "secondary"),
            ("discard", "不保存", "danger-secondary"),
            ("save", "保存并返回", "primary"),
        ),
        default_action="save",
    )
    dialog.show()
    app.processEvents()
    try:
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        assert {"继续编辑", "不保存", "保存并返回"} <= buttons.keys()
        assert buttons["继续编辑"].objectName() == "RoundedDialogCancel"
        assert buttons["不保存"].objectName() == "RoundedDialogDangerSecondary"
        assert buttons["保存并返回"].objectName() == "RoundedDialogConfirm"
        buttons["保存并返回"].click()
        assert dialog.selected_action == "save"
    finally:
        dialog.close()
        app.processEvents()


def test_registration_submit_dialog_uses_green_default_action_and_readable_detail() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = RoundedMessageDialog(
        None,
        "确认提交实名登记",
        "请核对本架无人机的最终登记资料。",
        detail="登记人：演示用户\n机型：DJI 演示机型 X1\n序列号：DEMO-SERIAL-0001",
        kind="success",
        action_specs=(
            ("cancel", "取消", "secondary"),
            ("confirm", "确认提交", "success"),
        ),
        default_action="confirm",
    )
    dialog.show()
    app.processEvents()
    try:
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        detail = dialog.findChild(QLabel, "RoundedDialogDetail")
        assert buttons["取消"].objectName() == "RoundedDialogCancel"
        assert buttons["确认提交"].objectName() == "RoundedDialogSuccessConfirm"
        assert buttons["确认提交"].isDefault() is True
        assert detail is not None
        assert detail.property("kind") == "success"
        assert 'QLabel#RoundedDialogDetail[kind="success"]' in APP_STYLE
        assert "font-size: 14px" in APP_STYLE
    finally:
        dialog.close()
        app.processEvents()
