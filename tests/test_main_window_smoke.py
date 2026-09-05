import base64
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("UOM_WINE_COMPAT", "1")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QStackedWidget, QWidget

import uom_printer.ui.main_window as main_window_module
from uom_printer.ui.main_window import MainWindow
from uom_printer.dji_service import DjiProductInfo
from uom_printer.dji_web import DjiDeviceResult
from uom_printer.layout_template import default_layout_template, load_layout_template, save_layout_template
from uom_printer.models import UomRecord
from uom_printer.model_catalog import ModelCatalogStore
from uom_printer.paths import layout_template_path
from uom_printer.settings import AppSettings, SettingsStore
from uom_printer.registration import PreparedRegistrationPhoto
from uom_printer.ui.widgets import ToggleSwitch
from uom_printer.uom_web import UomWebFailure


DEMO_DJI_MODEL = "DJI 演示机型 X1"
DEMO_UOM_MODEL_CODE = "DEMO-X1"


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def make_window(tmp_path, monkeypatch) -> MainWindow:
    monkeypatch.setenv("UOM_PRINTER_APP_DATA", str(tmp_path / "app-data"))
    monkeypatch.setenv("UOM_PRINTER_DESKTOP", str(tmp_path / "desktop"))
    window = MainWindow()
    window.show()
    app().processEvents()
    return window


def close_window(window: MainWindow) -> None:
    window.force_quit = True
    window.close()


def seed_model_catalog(
    window: MainWindow,
    tmp_path: Path,
    models: list[dict[str, str]],
    *,
    dji_titles: list[str] | None = None,
) -> None:
    store = ModelCatalogStore(
        tmp_path / "model-catalog.json",
        min_uom_models=1,
        min_dji_products=1,
    )
    titles = dji_titles or [str(models[0].get("chanpmc") or DEMO_DJI_MODEL)]
    products = [
        {
            "title": title,
            "slug": f"demo-{index}",
            "url": f"https://www.dji.com/cn/support/product/demo-{index}",
        }
        for index, title in enumerate(titles)
    ]
    store.save_sources(
        {"id": "demo-company-id", "unitName": "演示厂商"},
        models,
        products,
    )
    window.model_catalog = store
    window._refresh_model_catalog_ui()


def face_context_payload(provider: str = "wx") -> dict[str, object]:
    qr_pixmap = QPixmap(24, 24)
    qr_pixmap.fill(Qt.white)
    qr_bytes = QByteArray()
    qr_buffer = QBuffer(qr_bytes)
    assert qr_buffer.open(QIODevice.WriteOnly)
    assert qr_pixmap.save(qr_buffer, "PNG")
    qr_png = base64.b64encode(bytes(qr_bytes)).decode("ascii")
    return {
        "owner": {"xingm": "演示用户", "zhengjhm": "DEMO-CERT"},
        "faceProvider": provider,
        "availableFaceProviders": [
            {"value": "wx", "title": "微信小程序"},
            {"value": "zfb", "title": "支付宝小程序"},
        ],
        "faceQrDataUrl": f"data:image/png;base64,{qr_png}",
    }


def test_manual_import_failure_shows_rounded_dialog_and_system_notification(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    dialogs: list[tuple[str, str]] = []
    notifications: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(
        main_window_module,
        "critical",
        lambda _parent, title, message: dialogs.append((title, message)) or 0,
    )
    monkeypatch.setattr(
        window,
        "_notify",
        lambda title, message, error=False: notifications.append((title, message, error)),
    )

    window._manual_failed("不支持的二维码：识别到的内容不是UOM实名登记码", "trace")

    assert dialogs == [("实名码识别失败", "不支持的二维码：识别到的内容不是UOM实名登记码")]
    assert notifications == [
        ("UOM自动打印报错", "手动导入处理失败：不支持的二维码：识别到的内容不是UOM实名登记码", True)
    ]
    close_window(window)


def test_sidebar_button_click_animation_preserves_monitoring(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    fake_web_surface = QWidget()
    window.uom_view = fake_web_surface
    window.monitoring = True
    frames: list[float] = []
    widths: list[int] = []
    window.sidebar_width_animation.valueChanged.connect(lambda value: frames.append(float(value)))
    window.sidebar_width_animation.valueChanged.connect(lambda _value: widths.append(window.sidebar_panel.width()))

    QTest.mouseClick(window.sidebar_toggle_button, Qt.LeftButton)
    QTest.qWait(300)
    assert window.sidebar_panel.isHidden()
    assert window.sidebar_toggle_button.text() == "展开"
    assert window.monitoring is True
    assert fake_web_surface.updatesEnabled()
    assert len({round(value, 2) for value in frames}) >= 5
    assert frames[0] > frames[-1]
    # The WebEngine surface is resized only once after the fade.  Keeping the
    # sidebar width stable during animation prevents Windows compositor trails.
    assert set(widths) == {374}

    QTest.mouseClick(window.sidebar_toggle_button, Qt.LeftButton)
    QTest.qWait(300)
    assert window.sidebar_panel.isVisible()
    assert window.sidebar_panel.width() == 374
    assert window.sidebar_toggle_button.text() == "收起"
    assert window.monitoring is True
    assert fake_web_surface.updatesEnabled()

    # A quick second click must reverse from the current opacity instead of flashing.
    QTest.mouseClick(window.sidebar_toggle_button, Qt.LeftButton)
    QTest.qWait(70)
    assert window._sidebar_animation_effect is not None
    mid_opacity = window._sidebar_animation_effect.opacity()
    assert 0.0 < mid_opacity < 1.0
    QTest.mouseClick(window.sidebar_toggle_button, Qt.LeftButton)
    QTest.qWait(300)
    assert window.sidebar_panel.isVisible()
    assert window.sidebar_panel.width() == 374
    close_window(window)


def test_product_name_is_uom_auto_print(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    assert window.windowTitle() == "UOM自动打印"
    assert window.tray_icon.toolTip() == "UOM自动打印"
    assert window.floating_window.windowTitle() == "UOM自动打印状态"
    assert (
        window.floating_window.bubble.subtitle_label.width()
        >= window.floating_window.bubble.subtitle_label.fontMetrics().horizontalAdvance("拖个实名码给我")
    )
    assert isinstance(window.auto_print, ToggleSwitch)
    assert isinstance(window.manual_auto, ToggleSwitch)
    assert window.paper_selector.count() == 19
    assert window.paper_selector.isEnabled() is False
    assert window.paper_change_button.text() == "修改"
    assert window.edit_layout_button.text() == "编辑"
    assert not hasattr(window, "drop_assistant")
    assert not hasattr(window, "drag_probe")
    assert not hasattr(window, "global_drag_monitor")
    assert not window.sidebar_scroll.isAncestorOf(window.paper_toolbar)
    assert not hasattr(window, "_window_corners")
    close_window(window)


def test_copy_buttons_refresh_feedback_and_progress_autohide(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)

    QTest.mouseClick(window.qr_copies.plus_button, Qt.LeftButton)
    assert window.qr_copies.value() == 3
    assert window.settings.qr_label_copies == 3
    assert "共4张" in window.copy_summary.text()

    QTest.mouseClick(window.info_copies.minus_button, Qt.LeftButton)
    assert window.info_copies.value() == 1
    QTest.mouseClick(window.info_copies.plus_button, Qt.LeftButton)
    assert window.info_copies.value() == 2
    assert window.settings.info_label_copies == 2

    QTest.mouseClick(window.refresh_uom_button, Qt.LeftButton)
    assert window.refresh_uom_button.property("feedback") == "clicked"
    assert "离线界面测试正常" in window.log_view.toPlainText()
    QTest.qWait(220)
    assert window.refresh_uom_button.property("feedback") in ("", None)

    window._web_load_started()
    window._web_load_progress(64)
    assert window.web_progress.isVisible()
    assert window.web_progress.value() == 64
    window._web_load_finished(True)
    QTest.qWait(420)
    assert window.web_progress.isHidden()
    close_window(window)


def test_device_info_preview_is_above_double_qr_preview(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    sidebar_layout = window.info_preview.parentWidget().parentWidget().layout()
    info_card = window.info_preview.parentWidget()
    qr_card = window.qr_preview.parentWidget()
    assert sidebar_layout.indexOf(info_card) < sidebar_layout.indexOf(qr_card)
    close_window(window)


def test_sidebar_mode_switch_is_view_only(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.monitoring = True
    window.monitor_timer.start(7000)
    remaining = window.monitor_timer.remainingTime()

    QTest.mouseClick(window.lookup_mode_button, Qt.LeftButton)
    assert window.sidebar_pages.currentIndex() == 1
    assert not window.sidebar_scroll.isAncestorOf(window.mode_switch)
    assert window.sidebar_scroll.verticalScrollBar().value() == 0
    assert window.monitoring is True
    assert window.monitor_timer.isActive()
    assert 0 < window.monitor_timer.remainingTime() <= remaining

    QTest.mouseClick(window.auto_mode_button, Qt.LeftButton)
    assert window.sidebar_pages.currentIndex() == 0
    assert window.monitoring is True
    assert window.monitor_timer.isActive()
    close_window(window)


def test_registration_mode_is_view_only_and_exposes_the_guarded_flow(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.monitoring = True
    window.monitor_timer.start(7000)

    QTest.mouseClick(window.registration_mode_button, Qt.LeftButton)

    assert window.sidebar_pages.currentIndex() == 2
    assert window.monitoring is True
    assert window.monitor_timer.isActive()
    assert window.registration_identify_button.text() == "先更新型号库"
    assert window.registration_prepare_button is window.registration_identify_button
    assert not window.registration_prepare_button.isEnabled()
    assert not hasattr(window.registration_panel, "registration_face_card")
    assert not hasattr(window, "registration_submit_button")
    assert window.cancellation_button.text() == "注销"
    assert window.cancellation_serial_input.placeholderText() == "序列号或唯一识别码"
    assert window.registration_front_tile.width() == window.registration_front_tile.height()
    assert window.registration_serial_tile.width() == window.registration_serial_tile.height()
    assert window.registration_front_tile.layout().itemAt(0).alignment() & Qt.AlignHCenter
    assert window.registration_serial_tile.layout().itemAt(0).alignment() & Qt.AlignHCenter
    registration_title = next(
        label
        for label in window.registration_panel.findChildren(QLabel, "SectionTitle")
        if label.text() == "实名登记准备"
    )
    title_rect = QRect(
        registration_title.mapTo(window.registration_panel, QPoint(0, 0)),
        registration_title.size(),
    )
    reset_rect = QRect(
        window.registration_reset_button.mapTo(window.registration_panel, QPoint(0, 0)),
        window.registration_reset_button.size(),
    )
    card_rect = QRect(
        window.registration_panel.registration_card.mapTo(window.registration_panel, QPoint(0, 0)),
        window.registration_panel.registration_card.size(),
    )
    assert not title_rect.intersects(reset_rect)
    assert card_rect.contains(reset_rect)
    assert (
        window.registration_front_tile.detail_label.geometry().bottom()
        <= window.registration_front_tile.contentsRect().bottom()
    )
    assert (
        window.registration_serial_tile.detail_label.geometry().bottom()
        <= window.registration_serial_tile.contentsRect().bottom()
    )
    photo_bottom = window.registration_front_tile.mapTo(
        window.registration_panel,
        QPoint(0, window.registration_front_tile.height()),
    ).y()
    identify_top = window.registration_identify_button.mapTo(
        window.registration_panel,
        QPoint(0, 0),
    ).y()
    assert photo_bottom < identify_top
    window._dji_login_state_changed(True, "DJI官网已登录")
    assert window.dji_login_status.text() == "大疆查询：已登录"
    assert window.dji_login_status.property("loggedIn") is True
    assert window.dji_open_button.text() == "大疆查询"
    assert window.web_home_button.text() == "UOM首页"
    close_window(window)


def test_fresh_install_shows_empty_catalog_without_bundled_data(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)

    window._switch_sidebar_mode(2)
    app().processEvents()

    assert window.model_catalog.summary().available is False
    assert "首次使用" in window.registration_model_catalog_status.text()
    assert window.registration_model_update_button.text() == "更新"
    close_window(window)


def test_catalog_update_combines_both_official_sources_and_refreshes_ui(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.model_catalog = ModelCatalogStore(
        tmp_path / "catalog-update.json",
        min_uom_models=1,
        min_dji_products=1,
    )
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    monkeypatch.setattr(
        window.uom_web,
        "fetch_official_brand_models",
        lambda _manufacturer, success, _failure: success(
            {
                "manufacturer": {"id": "demo-company-id", "unitName": "演示厂商"},
                "models": [
                    {"id": "demo-model", "chanpmc": DEMO_DJI_MODEL, "chanpxh": DEMO_UOM_MODEL_CODE}
                ],
            }
        ),
    )
    monkeypatch.setattr(
        main_window_module,
        "fetch_dji_support_catalog",
        lambda: [
            {
                "title": DEMO_DJI_MODEL,
                "slug": "demo-model",
                "url": "https://www.dji.com/cn/support/product/demo-model",
            }
        ],
    )

    window.start_model_catalog_update()
    for _attempt in range(20):
        if not window._model_catalog_update_busy:
            break
        QTest.qWait(50)

    summary = window.model_catalog.summary()
    assert summary.available is True
    assert (summary.uom_count, summary.dji_count) == (1, 1)
    assert "UOM 1 条" in window.registration_model_catalog_status.text()
    assert "DJI 1 条" in window.registration_model_catalog_status.text()
    assert window.registration_model_update_button.isEnabled()
    close_window(window)


def test_failed_catalog_update_keeps_previous_complete_catalog(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    old_models = [
        {"id": f"old-{index}", "chanpmc": f"DJI 旧型号 {index}", "chanpxh": f"OLD-{index}"}
        for index in range(4)
    ]
    seed_model_catalog(
        window,
        tmp_path,
        old_models,
        dji_titles=[f"DJI 旧型号 {index}" for index in range(4)],
    )
    original = window.model_catalog.path.read_bytes()
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    monkeypatch.setattr(
        window.uom_web,
        "fetch_official_brand_models",
        lambda _manufacturer, success, _failure: success(
            {
                "manufacturer": {"id": "demo-company-id", "unitName": "演示厂商"},
                "models": [{"id": "partial", "chanpmc": "DJI 残缺型号", "chanpxh": "PARTIAL"}],
            }
        ),
    )
    monkeypatch.setattr(
        main_window_module,
        "fetch_dji_support_catalog",
        lambda: [
            {
                "title": "DJI 残缺型号",
                "slug": "partial",
                "url": "https://www.dji.com/cn/support/product/partial",
            }
        ],
    )

    window.start_model_catalog_update()
    for _attempt in range(20):
        if not window._model_catalog_update_busy:
            break
        QTest.qWait(50)

    assert window.model_catalog.path.read_bytes() == original
    assert window.model_catalog.summary().uom_count == 4
    assert "已继续保留上一次完整型号库" in window.registration_model_catalog_status.text()
    close_window(window)


def test_registration_action_button_follows_human_workflow_states(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.resize(1460, 900)
    window._switch_sidebar_mode(2)
    app().processEvents()
    jpeg = b"\xff\xd8\xff\xdbDEMO\xff\xd9"
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")

    window._registration_stage = "face_closed"
    window._refresh_registration_action_button()
    assert window.registration_prepare_button.text() == "登录UOM后继续"
    assert window.registration_prepare_button.isEnabled()

    window._registration_prepared_photos = {
        "front": PreparedRegistrationPhoto(jpeg, "uom-front.jpg", 320, 320),
        "serial": PreparedRegistrationPhoto(jpeg, "uom-serial.jpg", 320, 320),
    }
    window._refresh_registration_action_button()
    assert window.registration_prepare_button.text() == "重新打开人脸认证"
    assert window.registration_prepare_button.isEnabled()

    window._registration_face_verified = True
    window._registration_stage = "model"
    window._refresh_registration_action_button()
    assert window.registration_prepare_button.text() == "正在准备登记资料…"
    assert not window.registration_prepare_button.isEnabled()

    continued: list[bool] = []
    window._registration_pending_form = {"chanpxlh": "DEMO-SERIAL-0001"}
    window._registration_stage = "ready_submit"
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    monkeypatch.setattr(window, "submit_prepared_registration", lambda: continued.append(True))
    window._refresh_registration_action_button()
    assert window.registration_prepare_button.text() == "继续提交"
    assert window.registration_prepare_button.isEnabled()
    assert window.registration_prepare_button is window.registration_identify_button
    app().processEvents()
    photo_bottom = window.registration_front_tile.mapTo(
        window,
        QPoint(0, window.registration_front_tile.height()),
    ).y()
    identify_top = window.registration_identify_button.mapTo(window, QPoint(0, 0)).y()
    assert identify_top >= photo_bottom
    QTest.mouseClick(window.registration_prepare_button, Qt.LeftButton)
    assert continued == [True]
    close_window(window)


def test_changing_photo_invalidates_verified_pending_registration(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    replacement = tmp_path / "replacement.jpg"
    replacement.write_bytes(b"demo")
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_resolved_serial = "DEMO-SERIAL-0001"
    window._registration_photo_paths = {
        "front": tmp_path / "old-front.jpg",
        "serial": tmp_path / "old-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_face_verified = True
    window._registration_pending_form = {"chanpxlh": "DEMO-SERIAL-0001"}
    window._registration_stage = "ready_submit"

    window._set_registration_photo("front", replacement)

    assert window._registration_photo_paths["front"] == replacement
    assert window._registration_dji_result is None
    assert window._registration_face_verified is False
    assert window._registration_pending_form is None
    assert window._registration_stage == "idle"
    assert window.registration_prepare_button.text() == "先更新型号库"
    assert not window.registration_prepare_button.isEnabled()
    assert "旧的待提交资料已作废" in window.registration_state.text()
    close_window(window)


def test_dji_toolbar_entry_opens_embedded_session_without_popup_or_restarting_lookup(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    loaded: list[bool] = []

    class FakeDjiWeb:
        query_active = False
        is_logged_in = True

        def ensure_loaded(self) -> None:
            loaded.append(True)

    window.dji_web = FakeDjiWeb()
    window.dji_view = QWidget()
    window.web_content_stack = QStackedWidget()
    window.uom_view = QWidget()
    window.web_content_stack.addWidget(window.uom_view)
    window.dji_sidebar_overlay = QFrame(window.sidebar_panel)
    window.registration_serial_input.setText("DEMO-SERIAL-0001")

    window.open_dji_login()

    assert loaded == [True]
    assert not hasattr(window, "dji_verification_dialog")
    assert window.dji_sidebar_overlay.isVisible()
    assert window.web_content_stack.currentWidget() is window.uom_view
    assert window.dji_verification_bar.isVisible()
    assert "左侧打开DJI官网" in window.registration_state.text()
    assert window.dji_login_status.metaObject().className() == "QLabel"
    close_window(window)


def test_dji_registration_query_uses_embedded_bar_and_can_cancel(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    started: list[str] = []
    cancelled: list[bool] = []

    class FakeDjiWeb:
        query_active = False
        is_logged_in = True

        def start_query(self, serial: str) -> None:
            started.append(serial)
            self.query_active = True

        def cancel_query(self) -> None:
            if self.query_active:
                cancelled.append(True)
            self.query_active = False

    fake_dji = FakeDjiWeb()
    window.dji_web = fake_dji
    window.dji_view = QWidget()
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    seed_model_catalog(
        window,
        tmp_path,
        [{"id": "demo-model", "chanpmc": DEMO_DJI_MODEL, "chanpxh": DEMO_UOM_MODEL_CODE}],
    )

    window.start_dji_registration_lookup()

    assert started == ["DEMO-SERIAL-0001"]
    assert window._active_web_source == "dji"
    assert window.dji_verification_bar.isVisible()
    assert "左侧大疆官方验证区" in window.dji_verification_status.text()
    assert not hasattr(window, "dji_verification_dialog")

    QTest.mouseClick(window.dji_verification_cancel_button, Qt.LeftButton)
    assert cancelled == [True]
    assert not window.dji_verification_bar.isVisible()
    assert window.registration_identify_button.text() == "重新识别并认证"
    close_window(window)


def test_dji_login_state_updates_status_and_explicit_entry(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)

    window._dji_login_state_changed(False, "DJI官网待登录")
    assert window.dji_login_status.text() == "大疆查询：未登录"
    assert window.dji_open_button.text() == "大疆查询"
    window._dji_login_state_changed(True, "DJI官网已登录")
    assert window.dji_login_status.text() == "大疆查询：已登录"
    assert window.dji_open_button.text() == "大疆查询"
    assert window.dji_login_status.property("loggedIn") is True
    window._uom_login_state_changed(True, "UOM官网已登录")
    assert window.uom_state.text() == "UOM：已登录"
    window._show_web_source("dji")
    window._dji_status_changed("正在读取精准机型…", "working")
    assert window.uom_state.text() == "UOM：已登录"
    close_window(window)


def test_registration_never_submits_when_final_confirmation_is_cancelled(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    submitted: list[dict] = []
    prompt_details: list[str] = []
    monkeypatch.setattr(
        main_window_module,
        "confirm_submit",
        lambda *_args, **kwargs: prompt_details.append(str(kwargs.get("detail") or "")) or False,
    )
    monkeypatch.setattr(
        window.uom_web,
        "submit_personal_registration",
        lambda form, _success, _failure: submitted.append(form),
    )
    window._registration_pending_form = {
        "xingm": "演示用户",
        "chanpmc": DEMO_DJI_MODEL,
        "chanpxh": DEMO_UOM_MODEL_CODE,
        "chanpxlh": "DEMO-SERIAL-0001",
        "kongjzl": "0.455",
        "zuidqfzl": "0.468",
        "mfgDate": "2026-07-26",
        "shiyyt": ["01", "02"],
    }
    window._registration_model_match_source = "人工确认"

    window.submit_prepared_registration()

    assert submitted == []
    assert "型号确认：人工确认" in prompt_details[0]
    assert "已取消提交" in window.registration_state.text()
    assert window.registration_prepare_button.text() == "继续提交"
    assert window.registration_prepare_button.isEnabled()
    close_window(window)


def test_prepared_registration_automatically_opens_final_confirmation(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    auto_submit: list[bool] = []
    window._registration_owner = {"xingm": "演示用户"}
    window._registration_uom_model = {"chanpmc": "演示机型"}
    window._registration_face_verified = True
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    monkeypatch.setattr(
        main_window_module,
        "build_personal_registration_form",
        lambda *_args, **_kwargs: {
            "xingm": "演示用户",
            "chanpmc": DEMO_DJI_MODEL,
            "chanpxh": DEMO_UOM_MODEL_CODE,
            "chanpxlh": "DEMO-SERIAL-0001",
            "kongjzl": "0.455",
            "zuidqfzl": "0.468",
            "mfgDate": "2026-07-26",
            "shiyyt": ["01", "02"],
        },
    )
    monkeypatch.setattr(window, "submit_prepared_registration", lambda: auto_submit.append(True))

    window._build_pending_registration("DEMO-FRONT", "DEMO-SERIAL")
    app().processEvents()

    assert auto_submit == [True]
    assert "正在打开最终确认" in window.registration_state.text()
    close_window(window)


def test_automatic_registration_submit_error_shows_popup_and_notification(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    popups: list[tuple[str, str]] = []
    notifications: list[tuple[str, str, bool]] = []
    window._registration_pending_form = {
        "xingm": "演示用户",
        "chanpmc": DEMO_DJI_MODEL,
        "chanpxh": DEMO_UOM_MODEL_CODE,
        "chanpxlh": "DEMO-SERIAL-0001",
        "kongjzl": "0.455",
        "zuidqfzl": "0.468",
        "mfgDate": "2026-07-26",
        "shiyyt": ["01", "02"],
    }
    monkeypatch.setattr(main_window_module, "confirm_submit", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        main_window_module,
        "information",
        lambda _parent, title, message: popups.append((title, message)),
    )
    monkeypatch.setattr(
        window,
        "_notify",
        lambda title, message, error=False: notifications.append((title, message, error)),
    )
    monkeypatch.setattr(
        window.uom_web,
        "submit_personal_registration",
        lambda _form, _success, failure: failure("接口字段校验失败"),
    )

    window.submit_prepared_registration()

    assert popups == [("实名登记未完成", "接口字段校验失败")]
    assert notifications == [("UOM实名登记未完成", "接口字段校验失败", True)]
    assert "接口字段校验失败" in window.registration_state.text()
    assert window._registration_pending_form is not None
    assert window.registration_prepare_button.text() == "继续提交"
    close_window(window)


def test_registration_submit_slow_feedback_explains_official_wait(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window._registration_operation_generation = 8
    window._registration_stage = "submitting"

    window._registration_submit_waiting(8, long_wait=False)
    assert "官方响应有点慢" in window.registration_state.text()

    window._registration_submit_waiting(8, long_wait=True)
    assert "软件没有卡住" in window.registration_state.text()

    window._registration_stage = "idle"
    window._registration_submit_waiting(8, long_wait=True)
    assert "软件没有卡住" in window.registration_state.text()
    close_window(window)


def test_successful_registration_releases_all_left_side_state(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    front_path = tmp_path / "demo-front.jpg"
    serial_path = tmp_path / "demo-serial.jpg"
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_resolved_serial = "DEMO-SERIAL-0001"
    window._registration_photo_paths = {"front": front_path, "serial": serial_path}
    window.registration_front_tile.set_file(front_path)
    window.registration_serial_tile.set_file(serial_path)
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_uom_model = {"chanpxh": DEMO_UOM_MODEL_CODE}
    window._registration_owner = {"xingm": "演示用户"}
    window._registration_face_verified = True
    window._registration_pending_form = {"chanpxlh": "DEMO-SERIAL-0001"}
    window._registration_front_quote = "DEMO-FRONT"
    window._registration_serial_quote = "DEMO-SERIAL"

    window._clear_registration_session_after_success("UOM已接受本次登记。")

    assert window.registration_serial_input.text() == ""
    assert window._registration_photo_paths == {"front": None, "serial": None}
    assert window.registration_front_tile.property("selected") is False
    assert window.registration_serial_tile.property("selected") is False
    assert window._registration_dji_result is None
    assert window._registration_uom_model is None
    assert window._registration_owner is None
    assert window._registration_face_verified is False
    assert window._registration_pending_form is None
    assert window._registration_front_quote == ""
    assert window._registration_serial_quote == ""
    assert window._registration_stage == "idle"
    assert not window.registration_identify_button.isEnabled()
    assert "可以继续登记下一架" in window.registration_state.text()
    close_window(window)


def test_registration_reset_clears_only_current_flow_and_stays_available_while_busy(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    seed_model_catalog(
        window,
        tmp_path,
        [{"id": "demo-model", "chanpmc": DEMO_DJI_MODEL, "chanpxh": DEMO_UOM_MODEL_CODE}],
    )
    catalog_path = window.model_catalog.path
    printer_name = window.settings.printer_name
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_face_verified = True
    window._registration_pending_form = {"chanpxlh": "DEMO-SERIAL-0001"}
    window._registration_stage = "submitting"
    window._set_registration_controls_busy(True)

    assert window.registration_reset_button.isEnabled()
    old_operation_generation = window._registration_operation_generation
    old_face_generation = window._registration_face_request_generation
    window._reset_registration_flow()

    assert window.registration_serial_input.text() == ""
    assert window._registration_photo_paths == {"front": None, "serial": None}
    assert window._registration_dji_result is None
    assert window._registration_face_verified is False
    assert window._registration_pending_form is None
    assert window._registration_stage == "idle"
    assert window.registration_serial_input.isEnabled()
    assert window.registration_front_tile.isEnabled()
    assert window.registration_serial_tile.isEnabled()
    assert not window.registration_reset_button.isEnabled()
    assert window._registration_operation_generation > old_operation_generation
    assert window._registration_face_request_generation > old_face_generation
    assert window.model_catalog.path == catalog_path
    assert window.model_catalog.summary().available is True
    assert window.settings.printer_name == printer_name
    assert "已重置" in window.registration_state.text()
    close_window(window)


def test_late_registration_submit_callback_is_ignored_after_reset(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    callbacks = {}
    popups = []
    window._registration_pending_form = {
        "xingm": "演示用户",
        "chanpmc": DEMO_DJI_MODEL,
        "chanpxh": DEMO_UOM_MODEL_CODE,
        "chanpxlh": "DEMO-SERIAL-0001",
        "kongjzl": "0.455",
        "zuidqfzl": "0.468",
        "mfgDate": "2026-07-26",
        "shiyyt": ["01", "02"],
    }
    monkeypatch.setattr(main_window_module, "confirm_submit", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main_window_module, "information", lambda *args, **_kwargs: popups.append(args))
    monkeypatch.setattr(
        window.uom_web,
        "submit_personal_registration",
        lambda _form, success, failure: callbacks.update(success=success, failure=failure),
    )

    window.submit_prepared_registration()
    assert window._registration_stage == "submitting"
    window._reset_registration_flow()
    callbacks["success"]({"message": "迟到的成功回调"})
    callbacks["failure"]("迟到的失败回调")

    assert window._registration_stage == "idle"
    assert window._registration_pending_form is None
    assert "已重置" in window.registration_state.text()
    assert popups == []
    close_window(window)


def test_model_catalog_timeout_releases_update_button_and_ignores_late_results(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window._model_catalog_update_generation = 12
    window._model_catalog_update_busy = True
    window._model_catalog_pending_uom = None
    window._model_catalog_pending_dji = None
    window._refresh_model_catalog_ui()
    assert not window.registration_model_update_button.isEnabled()

    window._model_catalog_update_timed_out(12)

    assert window._model_catalog_update_busy is False
    assert window.registration_model_update_button.isEnabled()
    assert "更新等待超时" in window.registration_model_catalog_status.text()
    window._model_catalog_dji_ready(
        12,
        [{"title": DEMO_DJI_MODEL, "slug": "late", "url": "https://example.invalid/late"}],
    )
    assert window._model_catalog_pending_dji is None
    close_window(window)


def test_uom_refresh_watchdog_restores_retry_button_when_webengine_never_answers(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.wine_compat_mode = False
    monkeypatch.setattr(window.uom_web, "reload", lambda: None)

    window.refresh_uom_page()
    generation = window.uom_refresh_generation
    assert window.uom_refreshing is True
    assert not window.refresh_uom_button.isEnabled()

    window._uom_refresh_timed_out(generation)

    assert window.uom_refreshing is False
    assert window.refresh_uom_button.isEnabled()
    assert window.refresh_uom_button.text() == "重试"
    assert window.uom_state.text() == "UOM：连接异常"
    assert "刷新等待超时" in window.log_view.toPlainText()
    close_window(window)


def test_retry_after_second_photo_failure_reuses_first_uploaded_quote(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    jpeg = b"\xff\xd8\xff\xdbDEMO\xff\xd9"
    window._registration_prepared_photos = {
        "front": PreparedRegistrationPhoto(jpeg, "uom-front.jpg", 320, 320),
        "serial": PreparedRegistrationPhoto(jpeg, "uom-serial.jpg", 320, 320),
    }
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_uom_model = {"chanpxh": DEMO_UOM_MODEL_CODE}
    window._registration_face_verified = True
    window._registration_front_quote = "ALREADY-UPLOADED-FRONT"
    uploaded: list[str] = []
    built: list[tuple[str, str]] = []

    def upload(_data, filename, success, _failure) -> None:
        uploaded.append(filename)
        success({"quoteCode": "NEW-SERIAL-QUOTE"})

    monkeypatch.setattr(window.uom_web, "upload_registration_photo", upload)
    monkeypatch.setattr(window, "_build_pending_registration", lambda front, serial: built.append((front, serial)))

    window._upload_registration_photos()

    assert uploaded == ["uom-serial.jpg"]
    assert built == [("ALREADY-UPLOADED-FRONT", "NEW-SERIAL-QUOTE")]
    close_window(window)


def test_unknown_submit_result_is_checked_before_any_retry(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window._registration_pending_form = {"chanpxlh": "DEMO-SERIAL-0001"}
    window._registration_stage = "submit_unknown"
    checked: list[str] = []
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    monkeypatch.setattr(type(window.uom_web), "is_page_ready", property(lambda _service: True))
    monkeypatch.setattr(main_window_module, "information", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(window, "_notify", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        window.uom_web,
        "search_registered_aircraft",
        lambda serial, success, _failure: checked.append(serial) or success([{"id": "DEMO-ROW"}]),
    )

    window._verify_registration_after_unknown_submit()

    assert checked == ["DEMO-SERIAL-0001"]
    assert window._registration_pending_form is None
    assert window._registration_stage == "idle"
    assert "可以继续登记下一架" in window.registration_state.text()
    close_window(window)


def test_official_web_collapse_keeps_same_page_and_does_not_reload(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    original_uom_web = window.uom_web
    original_dji_web = window.dji_web

    class FakePage:
        def __init__(self) -> None:
            self.lifecycle_calls: list[object] = []

        def setLifecycleState(self, state: object) -> None:
            self.lifecycle_calls.append(state)

    class FakeUomWeb:
        is_logged_in = True

        def __init__(self) -> None:
            self.page = FakePage()

    fake_uom = FakeUomWeb()
    window.wine_compat_mode = False
    window.uom_web = fake_uom
    window.dji_web = type("FakeDji", (), {"is_logged_in": True})()
    window.resize(1340, 820)
    app().processEvents()
    expanded_geometry = window.geometry()
    window._refresh_official_web_toggle_visibility()

    assert window.official_web_toggle_button.isVisible()
    window._set_official_web_collapsed(True, announce=False)
    assert window.web_card.isHidden()
    assert window.header_bubble.isHidden()
    assert window.compact_header_bubble_container.isVisible()
    assert window.width() == 480
    assert window.minimumWidth() == 480
    assert window.maximumWidth() == 480
    assert window.sidebar_panel.width() == 448
    assert window.body_layout.contentsMargins().left() == 16
    assert window.width() - window.sidebar_panel.width() == 32
    assert window.official_web_toggle_button.text() == "展开官网"
    assert len(fake_uom.page.lifecycle_calls) == 1
    pointer_tip = window.compact_header_bubble.mapTo(
        window,
        window.compact_header_bubble.pointer_tip(),
    )
    avatar_center = window.header_avatar.mapTo(window, window.header_avatar.rect().center())
    assert abs(pointer_tip.x() - avatar_center.x()) <= 2
    assert pointer_tip.y() > avatar_center.y()
    window._show_header_message("正在查询", "我去UOM里核对一下。", "working")
    assert window.compact_header_bubble.title_label.text() == "正在查询"
    assert window.compact_header_bubble.subtitle_label.text() == "我去UOM里核对一下。"
    assert window.compact_header_bubble.title_label.property("state") == "working"

    window._set_official_web_collapsed(False, announce=False)
    assert window.web_card.isVisible()
    assert window.header_bubble.isVisible()
    assert window.compact_header_bubble_container.isHidden()
    assert window.geometry() == expanded_geometry
    assert window.sidebar_panel.width() == 374
    assert window.minimumWidth() == 1180
    assert window.maximumWidth() == 16777215
    assert window.official_web_toggle_button.text() == "收起官网"
    assert len(fake_uom.page.lifecycle_calls) == 2

    window.uom_web = original_uom_web
    window.dji_web = original_dji_web
    window.wine_compat_mode = True
    close_window(window)


def test_header_web_version_and_monitor_controls_have_the_same_size(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    version_chip = window.findChild(QLabel, "VersionChip")

    assert version_chip is not None
    sizes = {
        (window.official_web_toggle_button.width(), window.official_web_toggle_button.height()),
        (version_chip.width(), version_chip.height()),
        (window.status_chip.width(), window.status_chip.height()),
    }
    assert sizes == {(108, 40)}

    close_window(window)


def test_uom_page_failure_pauses_active_registration_but_keeps_inputs(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_face_verified = True
    window._registration_stage = "model"
    window._set_registration_controls_busy(True)

    window._uom_page_ready(False)

    assert window.registration_serial_input.text() == "DEMO-SERIAL-0001"
    assert all(window._registration_photo_paths.values())
    assert window._registration_dji_result is not None
    assert window.registration_serial_input.isEnabled()
    assert window.registration_prepare_button.text() == "继续准备"
    assert window.uom_state.text() == "UOM：连接异常"
    close_window(window)


def test_missing_model_catalog_releases_controls_and_keeps_completed_face_state(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_face_verified = True
    window.registration_model_chip.setText("DJI已确认")
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    window._set_registration_controls_busy(True)
    window._match_registration_uom_model(then_upload=True)

    assert window.registration_serial_input.isEnabled()
    assert window._registration_face_verified is True
    assert window._registration_dji_result is not None
    assert window.registration_model_chip.text() == "需更新"
    assert window.registration_prepare_button.text() == "继续准备"
    assert window.registration_prepare_button.isEnabled()
    assert "本地型号库尚未更新" in window.registration_state.text()
    close_window(window)


def test_ambiguous_uom_models_wait_for_manual_selection_before_upload(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window._switch_sidebar_mode(2)
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_face_verified = True
    uploads: list[bool] = []
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    seed_model_catalog(
        window,
        tmp_path,
        [
            {
                "id": "demo-model-a",
                "chanpxh": "DEMO-MODEL-CODE-VERY-LONG-1234567890",
                "chanpmc": DEMO_DJI_MODEL,
                "kongjzl": "0.45",
                "zuidqfzl": "0.47",
            },
            {
                "id": "demo-model-b",
                "chanpxh": "DEMO-B",
                "chanpmc": DEMO_DJI_MODEL,
                "kongjzl": "0.46",
                "zuidqfzl": "0.49",
            },
            {
                "id": "demo-model-search-only",
                "chanpxh": "SEARCH-ONLY",
                "chanpmc": "DJI 其他演示机型",
                "kongjzl": "0.60",
                "zuidqfzl": "0.72",
            },
        ],
    )
    monkeypatch.setattr(window, "_upload_registration_photos", lambda: uploads.append(True))

    window._match_registration_uom_model(then_upload=True)
    app().processEvents()

    assert uploads == []
    assert window._registration_stage == "model_selection"
    assert window.registration_model_chip.text() == "请选择"
    assert window.registration_prepare_button.text() == "请先选择精准机型"
    assert not window.registration_prepare_button.isEnabled()
    assert window.registration_prepare_button.property("workflowState") == "waiting"
    assert window.registration_panel.registration_model_candidates_frame.isVisible()
    assert len(window.registration_panel._model_candidate_buttons) == 2
    assert len(window.registration_panel._model_candidate_cards) == 2
    assert len(window.registration_panel._model_candidate_meta_labels) == 2
    assert not window.registration_panel.registration_model_confirm_button.isEnabled()
    window.registration_panel.registration_model_search.setText("SEARCH-ONLY")
    app().processEvents()
    assert len(window.registration_panel._model_candidate_cards) == 1
    assert window.registration_panel.selected_model_candidate() is None
    assert window.registration_panel._model_candidates[0]["chanpxh"] == "SEARCH-ONLY"
    window.registration_panel.registration_model_search.clear()
    app().processEvents()
    assert len(window.registration_panel._model_candidate_cards) == 2

    window.resize(1180, 760)
    window.show()
    app().processEvents()
    candidate_frame = window.registration_panel.registration_model_candidates_frame
    photo_bottom_in_panel = window.registration_front_tile.mapTo(
        window.registration_panel,
        QPoint(0, window.registration_front_tile.height() - 1),
    ).y()
    identify_top_in_panel = window.registration_identify_button.mapTo(
        window.registration_panel,
        QPoint(0, 0),
    ).y()
    assert photo_bottom_in_panel + 8 < identify_top_in_panel
    unselected_height = candidate_frame.height()
    unselected_next_card_top = window.registration_panel.registration_cancellation_card.mapTo(
        window.registration_panel,
        QPoint(0, 0),
    ).y()
    confirm_bottom_in_frame = window.registration_panel.registration_model_confirm_button.mapTo(
        candidate_frame,
        QPoint(0, window.registration_panel.registration_model_confirm_button.height() - 1),
    ).y()
    confirm_top_in_frame = window.registration_panel.registration_model_confirm_button.mapTo(
        candidate_frame,
        QPoint(0, 0),
    ).y()
    last_candidate_bottom_in_frame = window.registration_panel._model_candidate_cards[-1].mapTo(
        candidate_frame,
        QPoint(0, window.registration_panel._model_candidate_cards[-1].height() - 1),
    ).y()
    assert last_candidate_bottom_in_frame + 6 < confirm_top_in_frame
    bottom_clearance = candidate_frame.height() - confirm_bottom_in_frame
    assert 12 <= bottom_clearance <= 20
    confirm_left_in_frame = window.registration_panel.registration_model_confirm_button.mapTo(
        candidate_frame,
        QPoint(0, 0),
    ).x()
    assert confirm_left_in_frame >= 0
    assert (
        confirm_left_in_frame + window.registration_panel.registration_model_confirm_button.width()
        <= candidate_frame.width()
    )
    assert (
        window.registration_panel.registration_model_confirm_button.fontMetrics().height() + 12
        <= window.registration_panel.registration_model_confirm_button.height()
    )
    for option, detail in zip(
        window.registration_panel._model_candidate_buttons,
        window.registration_panel._model_candidate_meta_labels,
        strict=True,
    ):
        assert option.fontMetrics().height() <= option.height()
        assert detail.fontMetrics().height() <= detail.height()
    viewport = window.sidebar_scroll.viewport()
    viewport_right = viewport.contentsRect().right()
    for widget in (
        window.registration_panel.registration_model_candidates_frame,
        window.registration_panel.registration_model_confirm_button,
        *window.registration_panel._model_candidate_cards,
    ):
        right = widget.mapTo(viewport, QPoint(widget.width() - 1, 0)).x()
        assert right <= viewport_right
    confirm_bottom = window.registration_panel.registration_model_confirm_button.mapTo(
        window.registration_panel,
        QPoint(0, window.registration_panel.registration_model_confirm_button.height() - 1),
    ).y()
    next_card_top = window.registration_panel.registration_cancellation_card.mapTo(
        window.registration_panel,
        QPoint(0, 0),
    ).y()
    assert confirm_bottom < next_card_top

    first_card = window.registration_panel._model_candidate_cards[0]
    QTest.mouseClick(
        first_card,
        Qt.LeftButton,
        pos=QPoint(first_card.width() - 14, first_card.height() // 2),
    )
    assert window.registration_panel.selected_model_candidate()["chanpxh"].startswith(
        "DEMO-MODEL-CODE"
    )
    assert window.registration_panel.registration_model_confirm_button.isEnabled()
    assert abs(candidate_frame.height() - unselected_height) <= 2

    model_top = window.registration_panel.registration_model_card.mapTo(
        window.sidebar_scroll.widget(),
        QPoint(0, 0),
    ).y()
    window.sidebar_scroll.verticalScrollBar().setValue(max(0, model_top - 8))
    app().processEvents()
    second_card = window.registration_panel._model_candidate_cards[1]
    QTest.mouseClick(
        second_card,
        Qt.LeftButton,
        pos=QPoint(second_card.width() - 14, second_card.height() // 2),
    )
    assert window.registration_panel.registration_model_confirm_button.isEnabled()
    assert window.registration_panel.selected_model_candidate()["chanpxh"] == "DEMO-B"
    assert abs(candidate_frame.height() - unselected_height) <= 2
    selected_next_card_top = window.registration_panel.registration_cancellation_card.mapTo(
        window.registration_panel,
        QPoint(0, 0),
    ).y()
    assert abs(selected_next_card_top - unselected_next_card_top) <= 2
    window.registration_panel.registration_model_confirm_button.click()

    assert uploads == [True]
    assert window._registration_uom_model is not None
    assert window._registration_uom_model["chanpxh"] == "DEMO-B"
    assert window._registration_uom_model["shengccsid"] == "demo-company-id"
    assert window.registration_model_chip.text() == "UOM已匹配"
    assert window.registration_panel.registration_model_candidates_frame.isHidden()
    close_window(window)


def test_single_low_confidence_uom_candidate_is_shown_for_manual_confirmation(
    tmp_path, monkeypatch
) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window._switch_sidebar_mode(2)
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(
        f"{DEMO_DJI_MODEL} 增强图传",
        "2026-07-28",
    )
    window._registration_face_verified = True
    uploads: list[bool] = []
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    seed_model_catalog(
        window,
        tmp_path,
        [
            {
                "id": "demo-model-a",
                "chanpxh": DEMO_UOM_MODEL_CODE,
                "chanpmc": DEMO_DJI_MODEL,
                "kongjzl": "0.45",
                "zuidqfzl": "0.47",
            }
        ],
    )
    monkeypatch.setattr(window, "_upload_registration_photos", lambda: uploads.append(True))

    window._match_registration_uom_model(then_upload=True)
    app().processEvents()

    assert uploads == []
    assert window._registration_stage == "model_selection"
    assert window.registration_panel.registration_model_candidates_frame.isVisible()
    assert len(window.registration_panel._model_candidate_buttons) == 1
    assert "1 个优先候选" in window.registration_model_detail.text()

    QTest.mouseClick(window.registration_panel._model_candidate_cards[0], Qt.LeftButton)
    assert window.registration_panel.registration_model_confirm_button.isEnabled()
    window.registration_panel.registration_model_confirm_button.click()

    assert uploads == [True]
    assert window._registration_uom_model is not None
    assert window._registration_uom_model["chanpxh"] == DEMO_UOM_MODEL_CODE
    close_window(window)


def test_submit_connection_loss_preserves_form_and_never_blindly_resubmits(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window._registration_pending_form = {
        "xingm": "演示用户",
        "chanpmc": DEMO_DJI_MODEL,
        "chanpxh": DEMO_UOM_MODEL_CODE,
        "chanpxlh": "DEMO-SERIAL-0001",
        "kongjzl": "0.455",
        "zuidqfzl": "0.468",
        "mfgDate": "2026-07-26",
        "shiyyt": ["01", "02"],
    }
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    submitted: list[bool] = []
    monkeypatch.setattr(main_window_module, "confirm_submit", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main_window_module, "information", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(window, "_notify", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(type(window.uom_web), "is_page_ready", property(lambda _service: False))

    def submit(_form, _success, failure) -> None:
        submitted.append(True)
        failure(
            UomWebFailure(
                "UOM官网响应超时。",
                kind="unknown",
                outcome_unknown=True,
            )
        )

    monkeypatch.setattr(window.uom_web, "submit_personal_registration", submit)

    window.submit_prepared_registration()

    assert submitted == [True]
    assert window._registration_stage == "submit_unknown"
    assert window._registration_pending_form is not None
    assert window.registration_prepare_button.text() == "核对登记结果"
    close_window(window)


def test_dji_result_is_not_guessed_when_uom_is_logged_out(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)

    window._dji_result_ready(DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26"))

    assert window._registration_dji_result is not None
    assert window._registration_uom_model is None
    assert window.registration_model_title.text() == DEMO_DJI_MODEL
    assert "登录UOM" in window.registration_state.text()
    close_window(window)


def test_dji_result_starts_face_gate_without_uom_business_requests(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    monkeypatch.setattr(
        type(window.uom_web),
        "is_logged_in",
        property(lambda _service: True),
    )
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    prepared: list[bool] = []
    model_queries: list[bool] = []
    photo_uploads: list[bool] = []
    submissions: list[bool] = []
    monkeypatch.setattr(window, "prepare_uom_registration", lambda: prepared.append(True))
    monkeypatch.setattr(
        window.uom_web,
        "fetch_official_brand_model",
        lambda *_args, **_kwargs: model_queries.append(True),
    )
    monkeypatch.setattr(
        window.uom_web,
        "upload_registration_photo",
        lambda *_args, **_kwargs: photo_uploads.append(True),
    )
    monkeypatch.setattr(
        window.uom_web,
        "submit_personal_registration",
        lambda *_args, **_kwargs: submissions.append(True),
    )

    window._dji_result_ready(DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26"))

    assert window._registration_uom_model is None
    assert window.registration_model_chip.text() == "DJI已确认"
    assert window.registration_model_title.text() == DEMO_DJI_MODEL
    assert prepared == [True]
    assert model_queries == []
    assert photo_uploads == []
    assert submissions == []
    assert "认证前不会查询UOM型号" in window.registration_state.text()
    close_window(window)


def test_registration_business_helpers_are_hard_blocked_before_face_success(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    model_queries: list[bool] = []
    photo_uploads: list[bool] = []
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_owner = {"xingm": "演示用户"}
    window._registration_uom_model = {"id": "demo-model"}
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    monkeypatch.setattr(
        window.uom_web,
        "fetch_official_brand_model",
        lambda *_args, **_kwargs: model_queries.append(True),
    )
    monkeypatch.setattr(
        window.uom_web,
        "upload_registration_photo",
        lambda *_args, **_kwargs: photo_uploads.append(True),
    )

    window._match_registration_uom_model(then_upload=True)
    window._upload_registration_photos()
    window._build_pending_registration("DEMO-FRONT", "DEMO-SERIAL")

    assert model_queries == []
    assert photo_uploads == []
    assert window._registration_pending_form is None
    assert "已拦截" in window.registration_state.text()
    close_window(window)


def test_face_success_then_matches_model_and_uploads_without_early_submit(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda _service: True))
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    sequence: list[str] = []
    submissions: list[bool] = []
    seed_model_catalog(
        window,
        tmp_path,
        [
            {
                "id": "demo-model",
                "chanpmc": DEMO_DJI_MODEL,
                "chanpxh": DEMO_UOM_MODEL_CODE,
                "kongjzl": "0.455",
                "zuidqfzl": "0.468",
            }
        ],
    )
    monkeypatch.setattr(window, "_upload_registration_photos", lambda: sequence.append("upload"))
    monkeypatch.setattr(
        window.uom_web,
        "submit_personal_registration",
        lambda *_args, **_kwargs: submissions.append(True),
    )
    monkeypatch.setattr(
        window.uom_web,
        "poll_face_verification",
        lambda _owner, provider, success, _failure: success(
            {"completed": True, "started": False, "code": 4, "provider": provider}
        ),
    )
    window._registration_context_ready(face_context_payload())
    assert window.registration_face_dialog is not None
    assert window.registration_face_dialog.isVisible()
    assert sequence == []
    assert submissions == []

    window._poll_registration_face()
    assert sequence == ["upload"]
    assert window._registration_model_match_source == "自动精确匹配"
    assert submissions == []
    QTest.qWait(720)

    assert window.registration_face_dialog is None
    assert "认证已通过" in window.registration_state.text()
    close_window(window)


def test_closing_face_dialog_stops_polling_and_allows_new_qr(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    jpeg = b"\xff\xd8\xff\xdbDEMO\xff\xd9"
    window.registration_serial_input.setText("DEMO-SERIAL-0001")
    window._registration_photo_paths = {
        "front": tmp_path / "demo-front.jpg",
        "serial": tmp_path / "demo-serial.jpg",
    }
    window._registration_dji_result = DjiDeviceResult(DEMO_DJI_MODEL, "2026-07-26")
    window._registration_prepared_photos = {
        "front": PreparedRegistrationPhoto(jpeg, "uom-front.jpg", 320, 320),
        "serial": PreparedRegistrationPhoto(jpeg, "uom-serial.jpg", 320, 320),
    }
    window._set_registration_controls_busy(True)
    window._registration_context_ready(face_context_payload())
    assert window.registration_face_dialog is not None
    assert window.registration_face_timer.isActive()

    window.registration_face_dialog.reject()
    app().processEvents()

    assert window.registration_face_dialog is None
    assert not window.registration_face_timer.isActive()
    assert window._registration_face_polling is False
    assert window._registration_face_poll_inflight is False
    assert window.registration_serial_input.isEnabled()
    assert window.registration_prepare_button.isEnabled()
    assert window.registration_prepare_button.text() == "重新打开人脸认证"
    assert "认证已关闭" in window.registration_state.text()
    close_window(window)


def test_old_face_context_callback_cannot_reopen_after_provider_switch(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    pending: list[tuple[object, object, str]] = []

    def capture(success, failure, provider="wx") -> None:
        pending.append((success, failure, provider))

    monkeypatch.setattr(window.uom_web, "fetch_personal_registration_context", capture)
    window._request_registration_face_context("wx")
    window._request_registration_face_context("zfb")
    assert [item[2] for item in pending] == ["wx", "zfb"]

    pending[0][0](face_context_payload("wx"))
    assert window.registration_face_dialog is None

    pending[1][0](face_context_payload("zfb"))
    assert window.registration_face_dialog is not None
    assert window.registration_face_dialog.provider == "zfb"
    close_window(window)


def test_face_poll_does_not_overlap_inflight_request(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    callbacks: list[tuple[object, object]] = []
    window._registration_owner = {"xingm": "演示用户", "zhengjhm": "DEMO-CERT"}
    window._registration_face_provider = "wx"
    window._registration_face_polling = True

    monkeypatch.setattr(
        window.uom_web,
        "poll_face_verification",
        lambda _owner, _provider, success, failure: callbacks.append((success, failure)),
    )
    window._poll_registration_face()
    window._poll_registration_face()
    assert len(callbacks) == 1

    callbacks[0][0]({"completed": False, "started": False, "code": 0})
    window._poll_registration_face()
    assert len(callbacks) == 2
    close_window(window)


def test_saving_custom_layout_keeps_monitor_timer_running(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.monitoring = True
    window.monitor_timer.start(7000)
    window.settings.custom_layout_enabled = True
    window.settings.layout_template_name = "50×40 安全预设"

    window.apply_settings(window.settings)

    assert window.monitoring is True
    assert window.monitor_timer.isActive()
    assert window.monitor_button.text() == "停止监听"
    assert "自动监听保持运行" in window.log_view.toPlainText()
    close_window(window)


def test_layout_editor_saves_preset_without_switching_current_paper(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.monitoring = True
    window.monitor_timer.start(7000)

    original_row = next(
        row for row in range(window.paper_selector.count())
        if window.paper_selector.itemData(row) == (50.0, 40.0)
    )
    window.paper_change_button.click()
    window.paper_selector.setCurrentIndex(original_row)
    window.paper_change_button.click()
    app().processEvents()
    assert window.settings.layout_template_name == "50×40 安全预设"

    window.open_layout_editor()
    app().processEvents()
    page = window.layout_editor_page
    assert page is not None
    assert window.main_stack.currentWidget() is page
    assert page.isWindow() is False
    assert page.info_kind_button.text() == "标签 1"
    assert page.qr_kind_button.text() == "标签 2"
    assert page.element_list.count() == 13
    page.qr_kind_button.click()
    app().processEvents()
    assert page.element_list.count() == 13

    page.name_edit.setText("门店演示预设")
    page._save()
    app().processEvents()

    assert window.main_stack.currentWidget() is window.main_page
    assert window.monitoring is True
    assert window.monitor_timer.isActive()
    assert any("门店演示预设" in window.paper_selector.itemText(row) for row in range(window.paper_selector.count()))
    assert window.paper_selector.current_paper() == (50.0, 40.0)
    assert window.settings.paper_width_mm == 50.0
    assert window.settings.layout_template_name == "50×40 安全预设"
    builtin_row = next(
        row for row in range(window.paper_selector.count())
        if window.paper_selector.itemData(row) == (60.0, 40.0)
        and window.paper_selector.itemData(row, Qt.UserRole + 2) is None
    )
    custom_row = next(
        row for row in range(window.paper_selector.count())
        if "门店演示预设" in window.paper_selector.itemText(row)
    )
    window.paper_change_button.click()
    window.paper_selector.setCurrentIndex(builtin_row)
    window.paper_change_button.click()
    assert window.settings.layout_template_name == "60×40 安全预设"
    window.paper_change_button.click()
    window.paper_selector.setCurrentIndex(custom_row)
    window.paper_change_button.click()
    assert window.settings.layout_template_name == "门店演示预设"
    assert window.settings.layout_preset_file == "门店演示预设.json"
    close_window(window)

    reopened = make_window(tmp_path, monkeypatch)
    assert reopened.settings.layout_template_name == "门店演示预设"
    assert reopened.settings.layout_preset_file == "门店演示预设.json"
    assert "门店演示预设" in reopened.paper_selector.currentText()
    close_window(reopened)


def test_legacy_active_personal_preset_updates_without_reverting_after_restart(tmp_path, monkeypatch) -> None:
    app()
    monkeypatch.setenv("UOM_PRINTER_APP_DATA", str(tmp_path / "app-data"))
    monkeypatch.setenv("UOM_PRINTER_DESKTOP", str(tmp_path / "desktop"))

    active = default_layout_template(60, 40)
    active.name = "60×40 安全预设"
    preset_path = layout_template_path().parent / "layout-presets" / "60×40 安全预设.json"
    save_layout_template(active, preset_path)
    save_layout_template(active, layout_template_path())
    legacy_settings = AppSettings(
        custom_layout_enabled=True,
        layout_template_name=active.name,
        layout_preset_file="",
        paper_width_mm=60,
        paper_height_mm=40,
    )
    SettingsStore().save(legacy_settings)

    window = make_window(tmp_path, monkeypatch)
    window.open_layout_editor()
    app().processEvents()
    page = window.layout_editor_page
    assert page is not None
    assert page._active_preset_path == preset_path
    assert page._editing_current_preset is True

    changed_font_size = page.template.info_elements[-1].font_size_mm + 0.2
    page.template.info_elements[-1].font_size_mm = changed_font_size
    page._save()
    app().processEvents()

    assert window.settings.layout_preset_file == preset_path.name
    assert window.paper_selector.current_preset_path() == preset_path
    assert load_layout_template(preset_path).info_elements[-1].font_size_mm == changed_font_size
    assert load_layout_template(layout_template_path()).info_elements[-1].font_size_mm == changed_font_size
    close_window(window)

    reopened = make_window(tmp_path, monkeypatch)
    try:
        assert reopened.settings.layout_preset_file == preset_path.name
        assert reopened.paper_selector.current_preset_path() == preset_path
        assert load_layout_template(layout_template_path()).info_elements[-1].font_size_mm == changed_font_size
    finally:
        close_window(reopened)


def test_last_selected_paper_survives_restart(tmp_path, monkeypatch) -> None:
    app()
    first = make_window(tmp_path, monkeypatch)
    target = next(
        row for row in range(first.paper_selector.count())
        if first.paper_selector.itemData(row) == (50.0, 40.0)
    )
    first.paper_change_button.click()
    first.paper_selector.setCurrentIndex(target)
    first.paper_change_button.click()
    app().processEvents()
    close_window(first)

    second = make_window(tmp_path, monkeypatch)
    assert second.settings.layout_template_name == "50×40 安全预设"
    assert second.paper_selector.current_paper() == (50.0, 40.0)
    close_window(second)


def test_floating_window_is_closed_and_reopened_from_tray_without_stopping_monitor(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.monitoring = True
    window.show_floating()
    assert window.floating_window.isVisible()
    assert window.float_action.text() == "关闭悬浮窗"
    assert not hasattr(window.floating_window, "close_button")

    window.float_action.trigger()
    app().processEvents()
    assert not window.floating_window.isVisible()
    assert window.monitoring is True
    assert window.float_action.text() == "显示悬浮窗"

    window.float_action.trigger()
    app().processEvents()
    assert window.floating_window.isVisible()
    assert window.monitoring is True
    close_window(window)


def test_paper_selection_applies_only_after_confirmation_and_defers_heavy_rerender(tmp_path, monkeypatch) -> None:
    application = app()
    window = make_window(tmp_path, monkeypatch)
    rendered = []
    window._rerender_current_labels = lambda template: rendered.append(template.name)
    original_width = window.settings.paper_width_mm
    target = next(
        row for row in range(window.paper_selector.count())
        if window.paper_selector.itemData(row) == (50.0, 40.0)
    )
    window.paper_change_button.click()
    window.paper_selector.setCurrentIndex(target)
    assert window.settings.paper_width_mm == original_width
    assert window.paper_change_button.text() == "确认"
    assert rendered == []

    window.paper_change_button.click()
    assert window.settings.paper_width_mm == 50.0
    assert window.paper_selector.isEnabled() is False
    assert window.paper_change_button.text() == "修改"
    assert rendered == []
    QTest.qWait(110)
    application.processEvents()
    assert rendered == ["50×40 安全预设"]
    close_window(window)


def test_clicking_elsewhere_auto_saves_pending_paper_selection(tmp_path, monkeypatch) -> None:
    application = app()
    window = make_window(tmp_path, monkeypatch)
    target = next(
        row for row in range(window.paper_selector.count())
        if window.paper_selector.itemData(row) == (50.0, 40.0)
    )
    window.paper_change_button.click()
    window.paper_selector.setCurrentIndex(target)
    assert window.settings.paper_width_mm != 50.0

    QTest.mouseClick(window.auto_mode_button, Qt.LeftButton)
    application.processEvents()

    assert window.settings.paper_width_mm == 50.0
    assert window.paper_change_button.text() == "修改"
    assert window.paper_selector.isEnabled() is False
    close_window(window)


def test_editing_layout_and_floating_mode_commit_pending_paper_selection(tmp_path, monkeypatch) -> None:
    application = app()
    window = make_window(tmp_path, monkeypatch)
    target = next(
        row for row in range(window.paper_selector.count())
        if window.paper_selector.itemData(row) == (50.0, 40.0)
    )
    window.paper_change_button.click()
    window.paper_selector.setCurrentIndex(target)
    window.open_layout_editor()
    application.processEvents()
    assert window.settings.paper_width_mm == 50.0
    assert window.paper_change_button.text() == "修改"
    assert window.layout_editor_page is not None
    window._close_layout_editor()

    other = next(
        row for row in range(window.paper_selector.count())
        if window.paper_selector.itemData(row) == (60.0, 40.0)
        and window.paper_selector.itemData(row, Qt.UserRole + 2) is None
    )
    window.paper_change_button.click()
    window.paper_selector.setCurrentIndex(other)
    window.show_floating()
    application.processEvents()
    assert window.settings.paper_width_mm == 60.0
    assert window.paper_change_button.text() == "修改"
    assert window.paper_selector.isEnabled() is False
    close_window(window)


def test_paper_edit_states_keep_toolbar_height_and_selection_persists(tmp_path, monkeypatch) -> None:
    application = app()
    window = make_window(tmp_path, monkeypatch)
    locked_height = window.paper_toolbar.height()
    target = next(
        row for row in range(window.paper_selector.count())
        if window.paper_selector.itemData(row) == (50.0, 40.0)
    )
    window.paper_change_button.click()
    application.processEvents()
    assert window.paper_toolbar.height() == locked_height
    window.paper_selector.setCurrentIndex(target)
    window.paper_change_button.click()
    application.processEvents()
    assert window.paper_toolbar.height() == locked_height
    close_window(window)

    reopened = make_window(tmp_path, monkeypatch)
    assert reopened.paper_selector.current_paper() == (50.0, 40.0)
    assert reopened.paper_selector.isEnabled() is False
    assert reopened.paper_change_button.text() == "修改"
    close_window(reopened)


def test_disabling_print_actions_does_not_auto_scroll_short_window(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window.resize(1180, 760)
    app().processEvents()
    bar = window.sidebar_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)

    for button in (window.latest_button, window.import_button, window.print_button):
        assert button.focusPolicy() == Qt.NoFocus
        window._set_sidebar_action_enabled(button, False)
        QTest.qWait(70)
        assert bar.value() == 0
        window._set_sidebar_action_enabled(button, True)
        QTest.qWait(70)
        assert bar.value() == 0

    close_window(window)


def test_lookup_page_offers_serial_and_registration_code_paths(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    QTest.mouseClick(window.lookup_mode_button, Qt.LeftButton)
    assert window.lookup_button.text() == "序列号查询"
    assert window.lookup_qr_button.text() == "导入机身实名码"
    assert not hasattr(window, "lookup_cancel_button")
    assert window.lookup_owned_actions.isHidden()
    assert not window.lookup_copy_button.isEnabled()

    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Air 3S",
        "1581FDEMO00000000005",
        "原机主",
        phone_number="13800000000",
        empty_weight="724 g",
        manufacturer="大疆",
    )
    window.lookup_button.setEnabled(False)
    window.lookup_qr_button.setEnabled(False)
    window.lookup_qr_button.setText("识别中…")
    window._lookup_succeeded(
        {"record": record, "product": None, "source": "机身实名码", "detail_error": ""}
    )
    assert window.lookup_source.text() == "机身实名码"
    assert "UOM实名码详情" in window.lookup_state.text()
    assert window.lookup_values["phone_number"].text() == "13800000000"
    assert window.lookup_button.isEnabled()
    assert window.lookup_qr_button.isEnabled()
    assert window.lookup_qr_button.text() == "导入机身实名码"
    assert not window.lookup_owned_actions.isHidden()
    assert window.lookup_print_button.isEnabled()
    assert window.lookup_copy_button.isEnabled()
    close_window(window)


def test_serial_lookup_uses_fast_public_endpoint_without_waiting_for_web_session(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        window,
        "_start_public_lookup",
        lambda serial, login_error="", request_generation=None, ownership_checked=False: calls.append(
            (serial, login_error, request_generation, ownership_checked)
        ),
    )
    window.lookup_serial_input.setText("1581FDEMO00000000006")
    window.query_registration()
    assert len(calls) == 1
    assert calls[0][0] == "1581FDEMO00000000006"
    assert calls[0][1] == ""
    assert calls[0][2] == window.lookup_request_generation
    assert calls[0][3] is True
    close_window(window)


def test_logged_in_serial_lookup_checks_current_account_before_public_endpoint(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    account_calls = []
    public_calls = []
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda self: True))
    monkeypatch.setattr(
        window.uom_web,
        "search_registered_aircraft",
        lambda serial, success, failure: account_calls.append((serial, success, failure)),
    )
    monkeypatch.setattr(
        window,
        "_start_public_lookup",
        lambda *args, **kwargs: public_calls.append((args, kwargs)),
    )

    window.lookup_serial_input.setText("UAS-DEMO-0001")
    window.query_registration()

    assert len(account_calls) == 1
    assert account_calls[0][0] == "UAS-DEMO-0001"
    assert public_calls == []
    close_window(window)


def test_all_lookup_results_enable_print_and_cancellation_lives_on_registration_page(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Air 3S",
        "1581TESTCURRENTACCOUNT",
        "演示用户",
        phone_number="138****8000",
        manufacturer="大疆",
    )
    owned_row = {
        "id": "owned-row-1",
        "uasCode": record.uas_code,
        "chanpxlh": record.aircraft_serial,
    }

    window._lookup_succeeded(
        {
            "record": record,
            "product": None,
            "source": "当前账号登记",
            "detail_error": "",
            "account_row": owned_row,
            "ownership_checked": True,
        }
    )
    assert window.lookup_print_button.isEnabled()
    assert not window.lookup_owned_actions.isHidden()
    assert window.lookup_copy_button.isEnabled()
    assert window._lookup_account_row == owned_row

    window._lookup_succeeded(
        {
            "record": record,
            "product": None,
            "source": "UOM公开查询",
            "detail_error": "",
            "ownership_checked": True,
        }
    )
    assert window.lookup_print_button.isEnabled()
    assert not window.lookup_owned_actions.isHidden()
    assert window.lookup_copy_button.isEnabled()
    assert window._lookup_account_row is None
    assert window.cancellation_button.text() == "注销"
    close_window(window)


def test_owned_lookup_print_requires_printer_and_runs_existing_print_flow(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    row = {
        "id": "owned-row-1",
        "uasCode": "UAS-DEMO-0001",
        "chanpxlh": "1581TESTCURRENTACCOUNT",
    }
    messages: list[tuple[str, str]] = []
    tasks: list[tuple[dict, bool]] = []
    monkeypatch.setattr(
        "uom_printer.ui.main_window.information",
        lambda _parent, title, message: messages.append((title, message)),
    )
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Air 3S",
        "1581TESTCURRENTACCOUNT",
        "演示用户",
        qr_payload="https://example.invalid/uom-demo",
    )
    window._lookup_succeeded(
        {
            "record": record,
            "product": None,
            "source": "当前账号登记",
            "detail_error": "",
            "account_row": row,
            "ownership_checked": True,
        }
    )

    window.settings.printer_name = ""
    QTest.mouseClick(window.lookup_print_button, Qt.LeftButton)
    assert messages and messages[-1][0] == "请先选择打印机"
    assert tasks == []

    window.settings.printer_name = "测试打印机"
    monkeypatch.setattr(
        window,
        "_uom_row_task",
        lambda task_row, should_print: (
            tasks.append((task_row, should_print))
            or {"labels": None, "print_error": ""}
        ),
    )
    monkeypatch.setattr(window, "_start_worker", lambda worker: worker.run())
    monkeypatch.setattr(window, "_notify", lambda *args, **kwargs: None)

    QTest.mouseClick(window.lookup_print_button, Qt.LeftButton)

    assert tasks == [(row, True)]
    assert window.lookup_print_button.text() == "打印"
    assert window.lookup_print_button.isEnabled()
    assert "当前查询设备的标签已提交" in window.log_view.toPlainText()
    close_window(window)


def test_external_qr_lookup_prints_without_account_ownership(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    record = UomRecord(
        "UAS-EXTERNAL-001",
        "DJI Air 3S",
        "1581EXTERNAL000001",
        "外部演示用户",
        phone_number="138****8000",
        qr_payload="https://uom.caac.gov.cn/#/uav-regist-show/00000000-0000-0000-0000-000000000001",
        raw={"id": "external-row"},
    )
    tasks: list[tuple[dict, bool]] = []
    window._lookup_succeeded(
        {
            "record": record,
            "product": None,
            "source": "机身实名码",
            "detail_error": "",
            "ownership_checked": True,
        }
    )
    window.settings.printer_name = "测试打印机"
    monkeypatch.setattr(
        window,
        "_uom_row_task",
        lambda task_row, should_print: (
            tasks.append((task_row, should_print))
            or {"labels": None, "print_error": ""}
        ),
    )
    monkeypatch.setattr(window, "_start_worker", lambda worker: worker.run())
    monkeypatch.setattr(window, "_notify", lambda *args, **kwargs: None)

    QTest.mouseClick(window.lookup_print_button, Qt.LeftButton)

    assert len(tasks) == 1
    assert tasks[0][0]["erwm"] == record.qr_payload
    assert tasks[0][0]["chanpxlh"] == record.aircraft_serial
    assert tasks[0][1] is True
    assert window.lookup_print_button.isEnabled()
    close_window(window)


def test_public_serial_lookup_with_rebuilt_qr_uses_existing_print_flow(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    record = UomRecord(
        "UAS-PUBLIC-001",
        "DJI Air 3S",
        "1581PUBLIC00000001",
        "公开用户",
        qr_payload=(
            "https://uom.caac.gov.cn/#/uav-regist-show/"
            "00000000-0000-0000-0000-000000000001"
        ),
    )
    window._lookup_succeeded(
        {
            "record": record,
            "product": None,
            "source": "UOM公开查询",
            "detail_error": "",
            "ownership_checked": True,
        }
    )
    window.settings.printer_name = "测试打印机"
    tasks: list[tuple[dict, bool]] = []
    monkeypatch.setattr(
        window,
        "_uom_row_task",
        lambda row, should_print: tasks.append((row, should_print)) or {"labels": None, "print_error": ""},
    )
    monkeypatch.setattr(window, "_start_worker", lambda worker: worker.run())
    monkeypatch.setattr(window, "_notify", lambda *args, **kwargs: None)

    QTest.mouseClick(window.lookup_print_button, Qt.LeftButton)

    assert len(tasks) == 1
    assert tasks[0][0]["erwm"] == record.qr_payload
    assert tasks[0][1] is True
    assert window.lookup_print_button.isEnabled()
    close_window(window)


def test_registration_cancellation_confirms_owned_device_then_submits_transfer_reason(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    submitted: list[dict] = []
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda self: True))
    monkeypatch.setattr("uom_printer.ui.main_window.confirm_danger", lambda *args, **kwargs: True)
    monkeypatch.setattr("uom_printer.ui.main_window.information", lambda *args, **kwargs: None)
    owned_row = {
        "id": "owned-row-1",
        "uasCode": "UAS-DEMO-0001",
        "chanpxlh": "1581TESTCURRENTACCOUNT",
        "chanpmc": "DJI Air 3S",
    }
    monkeypatch.setattr(
        window.uom_web,
        "search_registered_aircraft",
        lambda _identifier, success, _failure: success([owned_row]),
    )
    monkeypatch.setattr(
        window.uom_web,
        "cancel_registered_aircraft",
        lambda row, success, failure: (submitted.append(row), success({"message": "注销成功"})),
    )
    window.cancellation_serial_input.setText("1581TESTCURRENTACCOUNT")

    QTest.mouseClick(window.cancellation_button, Qt.LeftButton)
    assert submitted[0]["id"] == "owned-row-1"
    assert window.cancellation_serial_input.text() == ""
    assert "注销成功" in window.cancellation_state.text()
    assert "实名注销成功" in window.log_view.toPlainText()
    close_window(window)


def test_registration_cancellation_confirmation_can_stop_submission(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    submitted = []
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda self: True))
    monkeypatch.setattr("uom_printer.ui.main_window.confirm_danger", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        window.uom_web,
        "search_registered_aircraft",
        lambda _identifier, success, _failure: success(
            [{"id": "owned-row-1", "uasCode": "UAS-DEMO-0001", "chanpxlh": "1581TESTCURRENTACCOUNT"}]
        ),
    )
    monkeypatch.setattr(window.uom_web, "cancel_registered_aircraft", lambda *args: submitted.append(args))
    window.cancellation_serial_input.setText("UAS-DEMO-0001")

    QTest.mouseClick(window.cancellation_button, Qt.LeftButton)

    assert submitted == []
    assert window.cancellation_button.isEnabled()
    assert "已取消" in window.cancellation_state.text()
    assert "已取消本次实名注销" in window.log_view.toPlainText()
    close_window(window)


def test_registration_cancellation_rejects_device_not_owned_by_current_account(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda self: True))
    monkeypatch.setattr(
        window.uom_web,
        "search_registered_aircraft",
        lambda _identifier, success, _failure: success([]),
    )
    monkeypatch.setattr(
        "uom_printer.ui.main_window.information",
        lambda _parent, title, message: messages.append((title, message)),
    )
    window.cancellation_serial_input.setText("1581NOTCURRENTACCOUNT")

    QTest.mouseClick(window.cancellation_button, Qt.LeftButton)

    assert messages == [("无法注销", "这个机器不是你的，无法注销。")]
    assert window.cancellation_button.isEnabled()
    assert window.cancellation_serial_input.isEnabled()
    assert window.cancellation_serial_input.text() == ""
    assert window.cancellation_state.text() == "这个机器不是你的，无法注销。"
    close_window(window)


def test_registration_cancellation_submit_failure_releases_current_identifier(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    monkeypatch.setattr(type(window.uom_web), "is_logged_in", property(lambda self: True))
    monkeypatch.setattr("uom_printer.ui.main_window.confirm_danger", lambda *args, **kwargs: True)
    monkeypatch.setattr("uom_printer.ui.main_window.information", lambda *args, **kwargs: None)
    owned_row = {
        "id": "owned-row-1",
        "uasCode": "UAS-DEMO-0001",
        "chanpxlh": "DEMO-SERIAL-0001",
        "chanpmc": "演示机型",
    }
    monkeypatch.setattr(
        window.uom_web,
        "search_registered_aircraft",
        lambda _identifier, success, _failure: success([owned_row]),
    )
    monkeypatch.setattr(
        window.uom_web,
        "cancel_registered_aircraft",
        lambda _row, _success, failure: failure("UOM接口暂时不可用"),
    )
    window.cancellation_serial_input.setText("DEMO-SERIAL-0001")

    QTest.mouseClick(window.cancellation_button, Qt.LeftButton)

    assert window.cancellation_serial_input.text() == ""
    assert window.cancellation_serial_input.isEnabled()
    assert window.cancellation_button.isEnabled()
    assert window.cancellation_button.text() == "注销"
    assert "注销失败" in window.cancellation_state.text()
    close_window(window)


def test_copy_lookup_information_copies_all_visible_fields(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Air 3S",
        "DEMO-SN-2026-000001",
        "演示用户",
        phone_number="13800000000",
        empty_weight="724 g",
        product_model="CZ3SCLV",
        status="正常",
    )
    window._lookup_succeeded(
        {"record": record, "product": None, "source": "UOM公开查询", "detail_error": "", "ownership_checked": True}
    )

    QTest.mouseClick(window.lookup_copy_button, Qt.LeftButton)

    copied = QApplication.clipboard().text()
    assert "实名标识：UAS-DEMO-0001" in copied
    assert "所有人：演示用户" in copied
    assert "手机号：13800000000" in copied
    assert "序列号：DEMO-SN-2026-000001" in copied
    assert "信息来源：UOM公开查询" in copied
    close_window(window)


def test_printer_selection_is_moved_to_bottom_menu(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    assert window.printer_menu_button.text() == "打印机"
    assert not hasattr(window, "printer_combo")
    close_window(window)


def test_dropped_registration_photo_on_lookup_page_starts_lookup_recognition(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window._switch_sidebar_mode(1)
    photo = tmp_path / "机身实名码.jpg"
    calls = []
    monkeypatch.setattr(window, "process_registration_code", lambda path: calls.append(path))

    class Url:
        def toLocalFile(self) -> str:
            return str(photo)

    class Mime:
        def urls(self):
            return [Url()]

    class DropEvent:
        accepted = False

        def mimeData(self):
            return Mime()

        def acceptProposedAction(self) -> None:
            self.accepted = True

    event = DropEvent()
    window._set_lookup_drop_active(True)
    window.dropEvent(event)
    assert window.sidebar_pages.currentIndex() == 1
    assert calls == [photo]
    assert event.accepted is True
    assert window._lookup_drop_active is False
    assert window.lookup_qr_button.text() == "导入机身实名码"
    close_window(window)


def test_dropped_photo_on_auto_page_uses_unified_label_import(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    photo = tmp_path / "手机拍照实名码.jpg"
    manual_calls = []
    lookup_calls = []
    monkeypatch.setattr(
        window,
        "process_manual",
        manual_calls.append,
    )
    monkeypatch.setattr(window, "process_registration_code", lambda path: lookup_calls.append(path))

    class Url:
        def toLocalFile(self) -> str:
            return str(photo)

    class Mime:
        def urls(self):
            return [Url()]

    class DropEvent:
        accepted = False

        def mimeData(self):
            return Mime()

        def acceptProposedAction(self) -> None:
            self.accepted = True

    event = DropEvent()
    window._set_sidebar_drop_active(True)
    window.dropEvent(event)

    assert window.sidebar_pages.currentIndex() == 0
    assert manual_calls == [photo]
    assert lookup_calls == []
    assert event.accepted is True
    assert window._sidebar_drop_active is False
    assert window.sidebar_drop_overlay.isHidden()
    close_window(window)


def test_dragging_file_anywhere_over_auto_sidebar_shows_import_overlay(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    photo = tmp_path / "registration-screenshot.png"

    class Url:
        def toLocalFile(self) -> str:
            return str(photo)

    class Mime:
        def urls(self):
            return [Url()]

    class DragMoveEvent:
        accepted = False

        def __init__(self, point) -> None:
            self._point = QPointF(point)

        def mimeData(self):
            return Mime()

        def position(self) -> QPointF:
            return self._point

        def acceptProposedAction(self) -> None:
            self.accepted = True

    sidebar_point = window.mapFromGlobal(
        window.info_preview.mapToGlobal(window.info_preview.rect().center())
    )
    inside_event = DragMoveEvent(sidebar_point)
    window.dragMoveEvent(inside_event)
    assert inside_event.accepted is True
    assert window._sidebar_drop_active is True
    assert window.sidebar_drop_overlay.isVisible()
    assert window.sidebar_drop_overlay.geometry() == window.sidebar_panel.rect()
    assert window.sidebar_drop_title.text() == "松手即可导入"

    web_point = window.mapFromGlobal(window.web_card.mapToGlobal(window.web_card.rect().center()))
    outside_event = DragMoveEvent(web_point)
    window.dragMoveEvent(outside_event)
    assert outside_event.accepted is True
    assert window._sidebar_drop_active is False
    assert window.sidebar_drop_overlay.isHidden()
    close_window(window)


def test_floating_window_drop_uses_normal_import_flow_and_stays_on_screen(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    photo = tmp_path / "floating-drop.png"
    photo.write_bytes(b"image")
    calls = []
    monkeypatch.setattr(
        window,
        "process_manual",
        calls.append,
    )

    class Url:
        def toLocalFile(self) -> str:
            return str(photo)

    class Mime:
        def urls(self):
            return [Url()]

    class DropEvent:
        accepted = False

        def mimeData(self):
            return Mime()

        def acceptProposedAction(self) -> None:
            self.accepted = True

    drag_event = DropEvent()
    window.floating_window.dragEnterEvent(drag_event)
    assert drag_event.accepted is True
    assert window.floating_window._drop_active is True
    assert "松手即可导入" in window.floating_window.bubble.title_label.text()

    drop_event = DropEvent()
    window.floating_window.dropEvent(drop_event)
    assert drop_event.accepted is True
    assert window.floating_window._drop_active is False
    assert calls == [photo]

    screen = app().primaryScreen()
    assert screen is not None
    area = screen.availableGeometry()
    top_left = window.floating_window._clamped_position(QPoint(-100000, -100000), screen)
    bottom_right = window.floating_window._clamped_position(QPoint(100000, 100000), screen)
    assert top_left.x() >= area.left() + 6
    assert top_left.y() >= area.top() + 6
    assert bottom_right.x() + window.floating_window.width() <= area.right() - 5
    assert bottom_right.y() + window.floating_window.height() <= area.bottom() - 5
    close_window(window)


def test_manual_import_task_does_not_print_when_switch_is_off(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    source = tmp_path / "dragged-registration.pdf"
    labels = object()
    submitted = []

    class FakePipeline:
        def process_import(self, path, source="manual"):
            assert path == source_file
            assert source == "manual"
            return labels

        def submit_print(self, result):
            submitted.append(result)

    source_file = source
    monkeypatch.setattr(window, "pipeline", lambda: FakePipeline())

    result = window._manual_task(source_file, should_print=False)

    assert result["labels"] is labels
    assert result["printed"] is False
    assert result["print_error"] == ""
    assert submitted == []
    close_window(window)


def test_manual_import_passes_current_toggle_state_to_worker(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    source = tmp_path / "dragged-registration.pdf"
    captured = []
    monkeypatch.setattr(
        window,
        "_manual_task",
        lambda path, should_print: captured.append((path, should_print)) or {"labels": object(), "printed": False, "print_error": ""},
    )
    monkeypatch.setattr(window, "_manual_result", lambda _result: None)
    monkeypatch.setattr(window, "_start_worker", lambda worker: worker.run())

    window.manual_auto.setChecked(False)
    window.process_manual(source)

    assert captured == [(source, False)]
    close_window(window)


def test_uom_monitor_task_does_not_print_when_auto_print_is_off(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    labels = object()
    submitted = []

    class FakePipeline:
        def process_uom_row(self, row):
            assert row == {"id": "new-row"}
            return labels

        def submit_print(self, result):
            submitted.append(result)

    monkeypatch.setattr(window, "pipeline", lambda: FakePipeline())
    result = window._uom_row_task({"id": "new-row"}, should_print=False)

    assert result["labels"] is labels
    assert result["printed"] is False
    assert submitted == []
    close_window(window)


def test_unified_import_picker_accepts_pdf_and_common_images(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    photo = tmp_path / "screenshot.png"
    captured = {}
    calls = []

    def fake_picker(_parent, title, directory, file_filter):
        captured.update(title=title, directory=directory, file_filter=file_filter)
        return str(photo), file_filter

    monkeypatch.setattr("uom_printer.ui.main_window.QFileDialog.getOpenFileName", fake_picker)
    monkeypatch.setattr(window, "process_manual", lambda path: calls.append(path))

    window.choose_import_file()

    assert calls == [photo]
    assert "UOM实名码" in captured["title"]
    for extension in ("*.pdf", "*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"):
        assert extension in captured["file_filter"]
    assert window.import_button.text() == "导入实名码"
    close_window(window)


def test_dragging_registration_file_over_lookup_card_shows_feedback(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    window._switch_sidebar_mode(1)
    app().processEvents()
    photo = tmp_path / "机身实名码.png"

    class Url:
        def toLocalFile(self) -> str:
            return str(photo)

    class Mime:
        def urls(self):
            return [Url()]

    class DragMoveEvent:
        accepted = False

        def __init__(self, point) -> None:
            self._point = QPointF(point)

        def mimeData(self):
            return Mime()

        def position(self) -> QPointF:
            return self._point

        def acceptProposedAction(self) -> None:
            self.accepted = True

    card_center = window.mapFromGlobal(window.lookup_card.mapToGlobal(window.lookup_card.rect().center()))
    inside_event = DragMoveEvent(card_center)
    window.dragMoveEvent(inside_event)
    assert inside_event.accepted is True
    assert window._lookup_drop_active is True
    assert window.lookup_card.property("dropActive") is True
    assert window.lookup_qr_button.property("dropActive") is True
    assert window.lookup_qr_button.text() == "松开即可识别实名码"

    web_point = window.mapFromGlobal(window.web_card.mapToGlobal(window.web_card.rect().center()))
    outside_event = DragMoveEvent(web_point)
    window.dragMoveEvent(outside_event)
    assert outside_event.accepted is True
    assert window._lookup_drop_active is False
    assert window.lookup_qr_button.text() == "导入机身实名码"
    close_window(window)


def test_query_page_does_not_inherit_auto_page_scroll_height(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    QTest.mouseClick(window.lookup_mode_button, Qt.LeftButton)
    app().processEvents()
    query_height = window.sidebar_pages.sizeHint().height()
    current_height = window.sidebar_pages.currentWidget().sizeHint().height()
    assert abs(query_height - current_height) <= 2
    assert window.sidebar_scroll.verticalScrollBar().maximum() < 700
    close_window(window)


def test_query_scroll_ends_at_product_card_without_blank_tail(tmp_path, monkeypatch) -> None:
    app()
    window = make_window(tmp_path, monkeypatch)
    QTest.mouseClick(window.lookup_mode_button, Qt.LeftButton)
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Air 3S",
        "1581FDEMO00000000005",
        "演示用户",
        phone_number="13800000000",
        empty_weight="724 g",
        manufacturer="大疆",
    )
    product = DjiProductInfo(
        "DJI Air 3S",
        "1 英寸 CMOS 主摄 | 45 分钟续航 | O4 高清图传",
        "https://www.dji.com/cn/product/air-3s",
        "",
        specs=tuple(f"核心参数 {index}：测试数据" for index in range(10)),
    )
    window._lookup_succeeded({"record": record, "product": product, "source": "当前账号登记", "detail_error": ""})
    QTest.qWait(30)
    bar = window.sidebar_scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    app().processEvents()
    product_bottom = window.product_card.mapTo(
        window.sidebar_scroll.viewport(), window.product_card.rect().bottomLeft()
    ).y()
    assert abs(window.sidebar_scroll.viewport().height() - 1 - product_bottom) <= 2
    close_window(window)
