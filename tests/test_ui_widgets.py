import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from uom_printer.settings import AppSettings
from uom_printer.ui.paper_selector import PaperPresetComboBox
from uom_printer.ui.settings_dialog import SettingsDialog
from uom_printer.ui.rounded_dialog import FaceVerificationDialog
from uom_printer.ui.widgets import AspectRatioPreview, CopyCountSelector, PhotoDropTile, SpeechBubble, WheelSafeComboBox


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_preview_keeps_sixty_by_forty_ratio() -> None:
    app()
    preview = AspectRatioPreview()
    assert preview.heightForWidth(360) == 240
    assert preview.heightForWidth(300) == 200

    image = QImage(600, 400, QImage.Format_RGB32)
    image.fill(0xFFFFFFFF)
    preview.resize(360, 240)
    preview.set_source_pixmap(QPixmap.fromImage(image))
    assert preview.pixmap() is not None
    assert preview.pixmap().width() == 360
    assert preview.pixmap().height() == 240


def test_speech_bubble_updates_state_and_copy() -> None:
    app()
    bubble = SpeechBubble("默认", "默认说明")
    bubble.set_message("打印成功", "这次机器没摸鱼", "success")
    assert bubble.title_label.text() == "打印成功"
    assert bubble.subtitle_label.text() == "这次机器没摸鱼"
    assert bubble.title_label.property("state") == "success"


def test_speech_bubble_width_follows_text_length() -> None:
    app()
    bubble = SpeechBubble("短话", "好了")
    short_width = bubble.sizeHint().width()
    bubble.set_message(
        "这是一个明显更长但仍然需要保持紧凑的提示标题",
        "内容增长时气泡才应该跟着增长，达到上限后自动换行。",
    )
    long_size = bubble.sizeHint()
    assert long_size.width() > short_width
    assert long_size.width() <= 680

    compact = SpeechBubble("待命", "等你开工", compact=True)
    compact_short = compact.sizeHint().width()
    compact.set_message("打印任务已提交", "马上送进Windows打印队列")
    assert compact.sizeHint().width() > compact_short
    assert compact.sizeHint().width() <= 250


def test_top_left_speech_bubble_points_upward() -> None:
    app()
    bubble = SpeechBubble("正在查询", "我去UOM里核对一下。", pointer_position="top-left")
    bubble.resize(bubble.sizeHint())

    assert bubble.pointer_tip() == QPoint(25, 1)
    assert bubble.minimumHeight() == 64


def test_copy_count_selector_ignores_mouse_wheel() -> None:
    app()
    selector = CopyCountSelector(2)

    class WheelEvent:
        ignored = False

        def ignore(self) -> None:
            self.ignored = True

    event = WheelEvent()
    selector.wheelEvent(event)
    assert selector.value() == 2
    assert event.ignored is True


def test_printer_combo_ignores_mouse_wheel() -> None:
    app()
    combo = WheelSafeComboBox()
    combo.addItems(["打印机 A", "打印机 B"])
    combo.setCurrentIndex(0)

    class WheelEvent:
        ignored = False

        def ignore(self) -> None:
            self.ignored = True

    event = WheelEvent()
    combo.wheelEvent(event)
    assert combo.currentIndex() == 0
    assert event.ignored is True


def test_copy_count_buttons_only_show_while_interacting() -> None:
    app()
    selector = CopyCountSelector(2)
    assert selector.minus_button.property("quiet") is True
    assert selector.plus_button.property("quiet") is True

    selector._set_step_buttons_quiet(False)
    assert selector.minus_button.property("quiet") is False
    assert selector.plus_button.property("quiet") is False

    selector._set_step_buttons_quiet(True)
    assert selector.minus_button.property("quiet") is True
    assert selector.plus_button.property("quiet") is True


def test_poll_interval_is_fixed_to_three_to_ten_seconds(monkeypatch) -> None:
    app()
    monkeypatch.setattr("uom_printer.ui.settings_dialog.list_printers", lambda: [])
    settings = AppSettings()
    store = type("Store", (), {"save": lambda self, value: None})()
    dialog = SettingsDialog(settings, store)
    assert not hasattr(dialog, "poll_min")
    assert not hasattr(dialog, "poll_max")
    values = dialog._values()
    assert values.poll_jitter_min_seconds == 3
    assert values.poll_jitter_max_seconds == 10
    dialog.close()


def test_paper_selector_uses_rounded_immediate_popup() -> None:
    application = app()
    selector = PaperPresetComboBox()
    selector.resize(220, 40)
    selector.show()
    selector.showPopup()
    application.processEvents()
    try:
        assert selector._popup.isVisible()
        assert selector._popup.testAttribute(Qt.WA_TranslucentBackground)
        assert not selector._popup.mask().isEmpty()
        popup_image = selector._popup.grab().toImage()
        background = popup_image.pixelColor(popup_image.width() // 2, 2)
        assert background.alpha() == 255
        assert min(background.red(), background.green(), background.blue()) >= 245
        target = 1 if selector.currentIndex() != 1 else 2
        selector._popup_row_pressed(target)
        assert selector.currentIndex() == target
        assert not selector._popup.isVisible()
    finally:
        selector.close()
        application.processEvents()


def test_personal_preset_delegate_uses_the_user_name_as_title() -> None:
    selector = PaperPresetComboBox()
    selector.addItem("维修台长名称预设  ▾", (50.0, 40.0))
    row = selector.count() - 1
    selector.setItemData(row, "/tmp/demo-preset.json", Qt.UserRole + 2)
    title, secondary = selector._popup.list_view.itemDelegate().display_texts(selector.model().index(row, 0))
    assert title == "维修台长名称预设"
    assert secondary == "我的预设 · 50 × 40 mm"


def test_photo_drop_tile_accepts_one_supported_photo_with_feedback(tmp_path) -> None:
    app()
    photo = tmp_path / "demo-photo.jpg"
    photo.write_bytes(b"demo")
    tile = PhotoDropTile("机身照片", "拖入或点击选择")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(photo))])

    class Event:
        accepted = False
        ignored = False

        def mimeData(self):
            return mime

        def acceptProposedAction(self) -> None:
            self.accepted = True

        def ignore(self) -> None:
            self.ignored = True

    enter = Event()
    tile.dragEnterEvent(enter)
    assert enter.accepted is True
    assert tile.property("dropActive") is True
    assert tile.detail_label.text() == "松手即可使用"

    dropped: list[str] = []
    tile.fileDropped.connect(dropped.append)
    drop = Event()
    tile.dropEvent(drop)
    assert drop.accepted is True
    assert dropped == [str(photo)]
    assert tile.property("dropActive") is False


def test_photo_drop_tile_displays_selected_photo_preview(tmp_path) -> None:
    app()
    photo = tmp_path / "demo-preview.png"
    image = QImage(640, 480, QImage.Format_RGB32)
    image.fill(0xFF2D6CDF)
    assert image.save(str(photo))
    tile = PhotoDropTile("机身照片", "拖入或点击选择")

    tile.set_file(photo)

    assert tile.property("selected") is True
    assert tile.has_preview() is True
    assert tile.icon_label.text() == ""
    assert tile.icon_label.pixmap() is not None
    assert tile.icon_label.pixmap().size() == tile.icon_label.size()
    assert tile.detail_label.text() == "点击可更换"
    assert tile.toolTip() == str(photo)


def test_face_verification_dialog_closes_after_success() -> None:
    application = app()
    image = QImage(260, 260, QImage.Format_RGB32)
    image.fill(0xFFFFFFFF)
    dialog = FaceVerificationDialog(None, QPixmap.fromImage(image))
    dialog.show()
    application.processEvents()
    assert dialog.isVisible()

    dialog.mark_success()
    assert dialog.status_label.property("state") == "success"
    QTest.qWait(760)
    assert not dialog.isVisible()


def test_face_verification_dialog_defaults_to_wechat_and_switches_to_official_alipay() -> None:
    application = app()
    image = QImage(260, 260, QImage.Format_RGB32)
    image.fill(0xFFFFFFFF)
    pixmap = QPixmap.fromImage(image)
    dialog = FaceVerificationDialog(
        None,
        pixmap,
        provider="wx",
        available_providers=("wx", "zfb"),
    )
    requested: list[str] = []
    dialog.provider_switch_requested.connect(requested.append)
    dialog.show()
    application.processEvents()

    assert dialog.provider == "wx"
    assert dialog.title_label.text() == "微信人脸认证"
    assert dialog.switch_button.text() == "切换支付宝"
    close_button = dialog.findChild(QPushButton, "RoundedDialogClose")
    assert close_button is not None
    assert "稍后可重新打开" in close_button.toolTip()
    dialog.emphasize_provider_switch()
    assert dialog.switch_button.property("recommended") is True
    QTest.mouseClick(dialog.switch_button, Qt.LeftButton)
    assert requested == ["zfb"]

    dialog.set_provider_qr("zfb", pixmap, ("wx", "zfb"))
    assert dialog.provider == "zfb"
    assert dialog.title_label.text() == "支付宝人脸认证"
    assert dialog.switch_button.text() == "切换微信"
    dialog.close()
