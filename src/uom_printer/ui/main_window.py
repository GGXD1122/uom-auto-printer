from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPoint,
    QRect,
    QSignalBlocker,
    Qt,
    QThreadPool,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QAction, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..diagnostics import get_logger
from ..dji_service import DjiProductInfo, fetch_dji_product, fetch_dji_support_catalog
from ..dji_web import DjiDeviceResult, DjiWebService
from ..history import HistoryStore
from ..label_renderer import render_info_label, render_qr_label, save_label_set_outputs
from ..layout_template import default_layout_template, load_layout_template, save_layout_template
from ..models import ProcessedLabel, ProcessedLabelSet, UomRecord
from ..model_catalog import ModelCatalogError, ModelCatalogStore
from ..paths import layout_template_path, log_dir, output_dir, resource_path
from ..printing import list_printers
from ..registration import (
    PreparedRegistrationPhoto,
    RegistrationValidationError,
    build_personal_registration_form,
    prepare_registration_photo,
)
from ..settings import (
    AppSettings,
    DEFAULT_POLL_MAX_SECONDS,
    DEFAULT_POLL_MIN_SECONDS,
    SettingsStore,
)
from ..uom_web import (
    UomWebFailure,
    UomWebService,
    WineCompatibleUomWebService,
    rank_uom_model_candidates,
)
from ..uom_service import (
    extract_uom_payload_from_file,
    fetch_uom_record,
    fetch_uom_record_by_serial,
    is_complete_phone_number,
    qr_image_from_payload,
    record_from_uom_row,
)
from ..workers import Worker
from .floating_window import FloatingStatusWindow
from .layout_editor import LayoutEditorPage
from .paper_selector import PaperPresetComboBox
from .printer_dialog import PrinterDialog
from .registration_panel import RegistrationPanel
from .rounded_dialog import FaceVerificationDialog, about, confirm_danger, confirm_submit, critical, information
from .settings_dialog import SettingsDialog
from .widgets import (
    AspectRatioPreview,
    CopyCountSelector,
    CurrentPageStackedWidget,
    FeedbackButton,
    PhotoDropTile,
    RoundedAvatarLabel,
    SpeechBubble,
    ToggleSwitch,
)


class MainWindow(QMainWindow):
    workflow_log = Signal(str, str)
    DEFAULT_BUBBLE_TITLE = "专门给你们做的全自动实名打印工具"
    DEFAULT_BUBBLE_SUBTITLE = "右边在线实名，10秒内帮你把码打好（牛不牛）"
    DJI_UOM_MANUFACTURER = "深圳市大疆创新科技有限公司"
    SIDEBAR_WIDTH = 374
    COMPACT_WINDOW_WIDTH = 480
    COMPACT_SIDEBAR_WIDTH = 448

    def __init__(self, log_path: Path | None = None) -> None:
        super().__init__()
        self.file_logger = get_logger()
        self.log_path = log_path
        self.store = SettingsStore()
        self.settings = self.store.load()
        self.history = HistoryStore()
        self.model_catalog = ModelCatalogStore()
        self.wine_compat_mode = os.environ.get("UOM_WINE_COMPAT") == "1"
        self.uom_web = (
            WineCompatibleUomWebService(self)
            if self.wine_compat_mode
            else UomWebService(self)
        )
        self.dji_web: DjiWebService | None = None if self.wine_compat_mode else DjiWebService(self)
        self.current_labels: ProcessedLabelSet | None = None
        # Compatibility alias used by a few older helpers. New code uses current_labels.
        self.current_label: ProcessedLabel | None = None
        self.monitoring = False
        self.poll_running = False
        self.uom_queue: list[tuple[dict[str, Any], str, bool]] = []
        self.uom_labels: list[ProcessedLabelSet] = []
        self.active_workers: set[Worker] = set()
        self.uom_refreshing = False
        self.uom_refresh_generation = 0
        self.uom_poll_failure_streak = 0
        self.web_load_generation = 0
        self._sidebar_animation_target = self.settings.sidebar_collapsed
        self._sidebar_animation_overlay: QLabel | None = None
        self._sidebar_animation_effect: QGraphicsOpacityEffect | None = None
        self._sidebar_snapshot = QPixmap()
        self.force_quit = False
        self.lookup_request_generation = 0
        self.lookup_public_request_generation = -1
        self._lookup_account_row: dict[str, Any] | None = None
        self._lookup_record: UomRecord | None = None
        self._lookup_drop_active = False
        self._sidebar_drop_active = False
        self._active_web_source = "uom"
        self._registration_photo_paths: dict[str, Path | None] = {"front": None, "serial": None}
        self._registration_photo_preview_generation: dict[str, int] = {"front": 0, "serial": 0}
        self._registration_prepared_photos: dict[str, PreparedRegistrationPhoto] = {}
        self._registration_dji_result: DjiDeviceResult | None = None
        self._registration_resolved_serial = ""
        self._registration_uom_model: dict[str, Any] | None = None
        self._registration_model_candidates: list[dict[str, Any]] = []
        self._registration_model_candidate_manufacturer: dict[str, Any] = {}
        self._registration_model_selection_then_upload = False
        self._registration_model_match_source = ""
        self._registration_owner: dict[str, Any] | None = None
        self._registration_face_provider = "wx"
        self._registration_available_face_providers: tuple[str, ...] = ("wx",)
        self._registration_face_verified = False
        self._registration_pending_form: dict[str, Any] | None = None
        self._registration_face_polling = False
        self._registration_face_poll_inflight = False
        self._registration_face_request_generation = 0
        self._registration_face_started_polls = 0
        self._registration_face_wait_polls = 0
        self._registration_submit_prompt_open = False
        self._registration_stage = "idle"
        self._registration_failure_kind = ""
        self._registration_controls_busy = False
        self._registration_operation_generation = 0
        self._registration_front_quote = ""
        self._registration_serial_quote = ""
        self._registration_submit_unknown_checks = 0
        self.registration_cancellation_generation = 0
        self.registration_face_dialog: FaceVerificationDialog | None = None
        self._dji_inline_verification_active = False
        self._dji_sidebar_restore_collapsed: bool | None = None
        self._dji_lazy_load_scheduled = False
        self._uom_page_healthy: bool | None = None
        self._official_web_collapsed = False
        self._official_web_expanded_geometry: QRect | None = None
        self._official_web_expanded_maximized = False
        self._official_web_expanded_fullscreen = False
        self._model_catalog_update_generation = 0
        self._model_catalog_update_busy = False
        self._model_catalog_pending_uom: dict[str, Any] | None = None
        self._model_catalog_pending_dji: list[dict[str, Any]] | None = None
        self._model_catalog_first_update_attempted = False
        self.registration_face_timer = QTimer(self)
        self.registration_face_timer.setInterval(5000)
        self.registration_face_timer.timeout.connect(self._poll_registration_face)
        self.header_message_timer = QTimer(self)
        self.header_message_timer.setSingleShot(True)
        self.header_message_timer.timeout.connect(self._restore_header_message)
        self._sidebar_scroll_restore_value: int | None = None
        self.sidebar_scroll_restore_timer = QTimer(self)
        self.sidebar_scroll_restore_timer.setSingleShot(True)
        self.sidebar_scroll_restore_timer.timeout.connect(self._apply_sidebar_scroll_restore)
        self.sidebar_scroll_restore_followup = QTimer(self)
        self.sidebar_scroll_restore_followup.setSingleShot(True)
        self.sidebar_scroll_restore_followup.timeout.connect(self._finish_sidebar_scroll_restore)
        self.layout_editor_page: LayoutEditorPage | None = None
        self._pending_layout_template = None
        self._paper_selection_editing = False
        self.layout_rerender_timer = QTimer(self)
        self.layout_rerender_timer.setSingleShot(True)
        self.layout_rerender_timer.setInterval(90)
        self.layout_rerender_timer.timeout.connect(self._flush_layout_rerender)

        self.thread_pool = QThreadPool.globalInstance()
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setSingleShot(True)
        self.monitor_timer.timeout.connect(self.poll_source)
        self.workflow_log.connect(self.append_log)
        self.uom_web.login_state_changed.connect(self._uom_login_state_changed)
        self.uom_web.page_ready_changed.connect(self._uom_page_ready)
        if self.dji_web is not None:
            self.dji_web.status_changed.connect(self._dji_status_changed)
            self.dji_web.login_state_changed.connect(self._dji_login_state_changed)
            self.dji_web.result_ready.connect(self._dji_result_ready)
            self.dji_web.query_failed.connect(self._dji_query_failed)
        self.floating_window = FloatingStatusWindow()
        self.floating_window.expand_requested.connect(self.restore_from_floating)
        self.floating_window.file_dropped.connect(self._floating_file_dropped)
        self.floating_window.position_changed.connect(self._save_floating_position)

        self.setWindowTitle("UOM自动打印")
        self.resize(1460, 900)
        self.setMinimumSize(1180, 760)
        self.setAcceptDrops(True)
        self._build_ui()
        self._refresh_model_catalog_ui()
        QTimer.singleShot(0, self._sync_sidebar_page_height)
        self._build_tray()
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
            self._application_event_filter_installed = True
        else:
            self._application_event_filter_installed = False
        self._refresh_status()
        if not self.wine_compat_mode:
            QTimer.singleShot(100, self.uom_web.ensure_loaded)
        self.append_log("info", "软件已启动。请在右侧UOM官网登录并完成实名登记。")
        if self.wine_compat_mode:
            self.append_log("warn", "当前为离线界面测试模式：可测试标签生成和预览，UOM网页功能请在Windows正式版中验证。")
        if self.log_path:
            self.append_log("info", "诊断日志已创建，日志中不会写入UOM登录凭据。")
        self.file_logger.info(
            "启动设置 | poll=%ss | printer=%s | auto_monitor=%s | auto_print=%s",
            self.settings.poll_seconds,
            self.settings.printer_name or "未选择",
            self.settings.auto_monitor,
            self.settings.auto_print,
        )
        if self.settings.auto_monitor:
            QTimer.singleShot(1200, self.start_monitor)

    def _build_ui(self) -> None:
        root = QStackedWidget()
        root.setObjectName("MainPageStack")
        self.setCentralWidget(root)
        self.main_stack = root
        self.main_page = QWidget(objectName="MainWorkspacePage")
        root.addWidget(self.main_page)
        root_layout = QVBoxLayout(self.main_page)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.header = QFrame(objectName="Header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(18, 8, 22, 8)
        header_layout.setSpacing(9)
        avatar_block = QWidget()
        avatar_layout = QVBoxLayout(avatar_block)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        avatar_layout.setSpacing(0)
        self.header_avatar = RoundedAvatarLabel(resource_path("assets/gegexd-avatar.jpg"))
        self.header_avatar.setFixedSize(46, 46)
        avatar_name = QLabel("鸽鸽XD", objectName="AvatarName")
        avatar_name.setAlignment(Qt.AlignCenter)
        avatar_layout.addWidget(self.header_avatar, 0, Qt.AlignHCenter)
        avatar_layout.addWidget(avatar_name)
        self.header_bubble = SpeechBubble(self.DEFAULT_BUBBLE_TITLE, self.DEFAULT_BUBBLE_SUBTITLE)
        self.header_bubble.setMaximumWidth(680)
        header_layout.addWidget(avatar_block, 0, Qt.AlignVCenter)
        header_layout.addWidget(self.header_bubble)
        header_layout.addStretch(1)
        # 顶部右侧的三个状态控件保持同一尺寸，避免窗口宽度或文字长度造成跳动。
        header_control_width = 108
        header_control_height = 40
        self.official_web_toggle_button = FeedbackButton(
            "收起官网",
            objectName="HeaderControlButton",
            elevated=False,
        )
        self.official_web_toggle_button.setFixedSize(header_control_width, header_control_height)
        self.official_web_toggle_button.setToolTip("隐藏右侧官方网页；登录态和自动处理继续保留")
        self.official_web_toggle_button.clicked.connect(self.toggle_official_web)
        self.official_web_toggle_button.hide()
        header_layout.addWidget(self.official_web_toggle_button)
        version_chip = QLabel(f"V{__version__}", objectName="VersionChip")
        version_chip.setFixedSize(header_control_width, header_control_height)
        version_chip.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(version_chip)
        self.status_chip = QLabel("未监听", objectName="StatusChip")
        self.status_chip.setProperty("state", "idle")
        self.status_chip.setFixedSize(header_control_width, header_control_height)
        self.status_chip.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.status_chip)
        root_layout.addWidget(self.header)

        self.compact_header_bubble_container = QWidget(objectName="CompactHeaderBubbleContainer")
        compact_bubble_layout = QHBoxLayout(self.compact_header_bubble_container)
        compact_bubble_layout.setContentsMargins(16, 0, 16, 0)
        self.compact_header_bubble = SpeechBubble(
            self.DEFAULT_BUBBLE_TITLE,
            self.DEFAULT_BUBBLE_SUBTITLE,
            pointer_position="top-left",
        )
        self.compact_header_bubble.setMaximumWidth(self.COMPACT_SIDEBAR_WIDTH)
        self.compact_header_bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        compact_bubble_layout.addWidget(self.compact_header_bubble, 1)
        self.compact_header_bubble_container.hide()
        root_layout.addWidget(self.compact_header_bubble_container)

        self.body_layout = QHBoxLayout()
        self.body_layout.setContentsMargins(16, 16, 16, 16)
        self.body_layout.setSpacing(14)
        root_layout.addLayout(self.body_layout, 1)

        self.sidebar_panel = QWidget(objectName="SidebarPanel")
        self.sidebar_panel.setFixedWidth(self.SIDEBAR_WIDTH)
        sidebar_panel_layout = QVBoxLayout(self.sidebar_panel)
        sidebar_panel_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_panel_layout.setSpacing(10)

        self.paper_toolbar = QFrame(objectName="SidebarPaperToolbar")
        paper_toolbar_layout = QHBoxLayout(self.paper_toolbar)
        paper_toolbar_layout.setContentsMargins(9, 7, 7, 7)
        paper_toolbar_layout.setSpacing(7)
        paper_toolbar_layout.addWidget(QLabel("纸张", objectName="LayoutFieldLabel"))
        self.paper_selector = PaperPresetComboBox()
        self.paper_selector.setMinimumWidth(0)
        self.paper_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.paper_selector.set_current_paper(
            self.settings.paper_width_mm,
            self.settings.paper_height_mm,
            self.settings.layout_template_name,
            self.settings.layout_preset_file,
        )
        selected_preset = self.paper_selector.current_preset_path()
        resolved_preset_file = selected_preset.name if selected_preset is not None else ""
        if self.settings.layout_preset_file != resolved_preset_file:
            self.settings.layout_preset_file = resolved_preset_file
            selected_template = self.paper_selector.current_template()
            if selected_template is not None:
                self.settings.layout_template_name = selected_template.name
            self.store.save(self.settings)
        self.paper_selector.paperChanged.connect(self._paper_size_changed)
        self.paper_selector.setEnabled(False)
        paper_toolbar_layout.addWidget(self.paper_selector, 1)
        self.paper_change_button = FeedbackButton("修改", objectName="PresetEditButton", elevated=False)
        self.paper_change_button.setProperty("mode", "edit")
        self.paper_change_button.setToolTip("点击修改后选择标签格式，点确认或界面其他位置即可保存")
        self.paper_change_button.clicked.connect(self._toggle_paper_selection_editing)
        paper_toolbar_layout.addWidget(self.paper_change_button)
        self.edit_layout_button = FeedbackButton("编辑", objectName="Primary", elevated=False)
        self.edit_layout_button.setToolTip("进入可视化编辑页面，调整标签1和标签2")
        self.edit_layout_button.clicked.connect(self.open_layout_editor)
        paper_toolbar_layout.addWidget(self.edit_layout_button)
        sidebar_panel_layout.addWidget(self.paper_toolbar)

        self.mode_switch = QFrame(objectName="SidebarModeSwitch")
        mode_switch_layout = QHBoxLayout(self.mode_switch)
        mode_switch_layout.setContentsMargins(4, 4, 4, 4)
        mode_switch_layout.setSpacing(4)
        self.auto_mode_button = FeedbackButton("自动打印", objectName="SidebarModeButton", elevated=False)
        self.lookup_mode_button = FeedbackButton("信息查询", objectName="SidebarModeButton", elevated=False)
        self.registration_mode_button = FeedbackButton("实名/注销", objectName="SidebarModeButton", elevated=False)
        self.auto_mode_button.setProperty("active", True)
        self.lookup_mode_button.setProperty("active", False)
        self.registration_mode_button.setProperty("active", False)
        self.auto_mode_button.clicked.connect(lambda: self._switch_sidebar_mode(0))
        self.lookup_mode_button.clicked.connect(lambda: self._switch_sidebar_mode(1))
        self.registration_mode_button.clicked.connect(lambda: self._switch_sidebar_mode(2))
        self.auto_mode_button.setToolTip("显示标签预览与打印控制；后台监听状态不会改变")
        self.lookup_mode_button.setToolTip("按飞行器序列号查询实名信息；后台监听仍继续运行")
        self.registration_mode_button.setToolTip("精准识别机型并准备实名登记；页面底部可注销本人设备")
        mode_switch_layout.addWidget(self.auto_mode_button)
        mode_switch_layout.addWidget(self.lookup_mode_button)
        mode_switch_layout.addWidget(self.registration_mode_button)
        sidebar_panel_layout.addWidget(self.mode_switch)

        sidebar = QWidget()
        sidebar.setObjectName("SidebarContent")
        sidebar.setMinimumWidth(350)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(10)
        sidebar_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setObjectName("SidebarScroll")
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Keep wheel/trackpad scrolling, but do not leave a permanent strip
        # between the cards and the UOM page.
        self.sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar_width_animation = QVariantAnimation(self)
        self.sidebar_width_animation.valueChanged.connect(self._sidebar_animation_frame)
        self.sidebar_width_animation.finished.connect(self._sidebar_animation_finished)
        self.sidebar_scroll.setWidget(sidebar)
        sidebar_panel_layout.addWidget(self.sidebar_scroll, 1)
        self.body_layout.addWidget(self.sidebar_panel)

        self.sidebar_pages = CurrentPageStackedWidget()
        self.sidebar_pages.setObjectName("SidebarPages")
        auto_page = QWidget(objectName="SidebarPage")
        auto_layout = QVBoxLayout(auto_page)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(10)
        query_page = QWidget(objectName="SidebarPage")
        query_layout = QVBoxLayout(query_page)
        query_layout.setContentsMargins(0, 0, 0, 0)
        query_layout.setSpacing(10)
        query_layout.setAlignment(Qt.AlignTop)
        self.registration_panel = RegistrationPanel()
        self.registration_panel.identify_requested.connect(self._registration_primary_action)
        self.registration_panel.cancellation_requested.connect(self.start_registration_cancellation)
        self.registration_panel.photo_clicked.connect(self._choose_registration_photo)
        self.registration_panel.photo_dropped.connect(self._registration_photo_dropped)
        self.registration_panel.model_candidate_confirmed.connect(
            self._confirm_registration_uom_model_candidate
        )
        self.registration_panel.model_catalog_update_requested.connect(
            self.start_model_catalog_update
        )
        self.registration_panel.reset_requested.connect(self._confirm_reset_registration_flow)
        self.registration_serial_input = self.registration_panel.registration_serial_input
        self.registration_front_tile = self.registration_panel.registration_front_tile
        self.registration_serial_tile = self.registration_panel.registration_serial_tile
        self.registration_identify_button = self.registration_panel.registration_identify_button
        self.registration_reset_button = self.registration_panel.registration_reset_button
        self.registration_state = self.registration_panel.registration_state
        self.registration_model_chip = self.registration_panel.registration_model_chip
        self.registration_model_title = self.registration_panel.registration_model_title
        self.registration_model_detail = self.registration_panel.registration_model_detail
        self.registration_model_catalog_status = self.registration_panel.registration_model_catalog_status
        self.registration_model_update_button = self.registration_panel.registration_model_update_button
        self.registration_prepare_button = self.registration_panel.registration_prepare_button
        self.cancellation_serial_input = self.registration_panel.cancellation_serial_input
        self.cancellation_button = self.registration_panel.cancellation_button
        self.cancellation_state = self.registration_panel.cancellation_state
        self.registration_serial_input.textChanged.connect(self._registration_input_changed)
        self.sidebar_pages.addWidget(auto_page)
        self.sidebar_pages.addWidget(query_page)
        self.sidebar_pages.addWidget(self.registration_panel)
        sidebar_layout.addWidget(self.sidebar_pages)

        qr_preview_card = QFrame(objectName="SidebarCard")
        qr_preview_layout = QVBoxLayout(qr_preview_card)
        qr_preview_layout.setContentsMargins(12, 11, 12, 12)
        qr_preview_layout.setSpacing(7)
        qr_preview_header = QHBoxLayout()
        qr_preview_header.addWidget(QLabel("标签 2", objectName="SectionTitle"))
        qr_preview_header.addStretch()
        self.qr_result_status = QLabel("等待生成", objectName="Subtitle")
        qr_preview_header.addWidget(self.qr_result_status)
        self.qr_copies = CopyCountSelector(max(1, self.settings.qr_label_copies))
        qr_preview_header.addWidget(self.qr_copies)
        qr_preview_layout.addLayout(qr_preview_header)
        self.qr_preview = AspectRatioPreview("自动显示双二维码和\n两条实名登记标识")
        self.qr_preview.setObjectName("PreviewCanvas")
        self.qr_preview.setProperty("state", "empty")
        qr_preview_layout.addWidget(self.qr_preview)

        info_preview_card = QFrame(objectName="SidebarCard")
        info_preview_layout = QVBoxLayout(info_preview_card)
        info_preview_layout.setContentsMargins(12, 11, 12, 12)
        info_preview_layout.setSpacing(7)
        info_preview_header = QHBoxLayout()
        info_preview_header.addWidget(QLabel("标签 1", objectName="SectionTitle"))
        info_preview_header.addStretch()
        self.info_result_status = QLabel("等待生成", objectName="Subtitle")
        info_preview_header.addWidget(self.info_result_status)
        self.info_copies = CopyCountSelector(max(1, self.settings.info_label_copies))
        info_preview_header.addWidget(self.info_copies)
        info_preview_layout.addLayout(info_preview_header)
        self.info_preview = AspectRatioPreview("左侧二维码，右侧自动显示\n姓名、电话、机型、序列号和重量")
        self.info_preview.setObjectName("PreviewCanvas")
        self.info_preview.setProperty("state", "empty")
        info_preview_layout.addWidget(self.info_preview)
        auto_layout.addWidget(info_preview_card)
        auto_layout.addWidget(qr_preview_card)

        # Compatibility aliases for older UI smoke-test helpers.
        self.preview = self.qr_preview
        self.result_status = self.qr_result_status
        self.qr_copies.valueChanged.connect(self._copy_counts_changed)
        self.info_copies.valueChanged.connect(self._copy_counts_changed)

        actions_card = QFrame(objectName="SidebarCard")
        self.import_drop_card = actions_card
        self.import_drop_card.setProperty("dropActive", False)
        actions_layout = QVBoxLayout(actions_card)
        actions_layout.setContentsMargins(14, 12, 14, 12)
        actions_layout.setSpacing(8)
        actions_layout.addWidget(QLabel("打印与自动化", objectName="SectionTitle"))
        self.copy_summary = QLabel(self._copy_summary(), objectName="CopySummary")
        actions_layout.addWidget(self.copy_summary)
        button_grid = QGridLayout()
        button_grid.setSpacing(8)
        self.monitor_button = FeedbackButton("开启监听", objectName="Primary")
        self.monitor_button.clicked.connect(self.toggle_monitor)
        self.monitor_button.setToolTip("开始持续读取UOM最新登记；只有点击停止才会结束")
        self.latest_button = FeedbackButton("读取最新并打印", objectName="Accent")
        self.latest_button.clicked.connect(self.read_latest_and_print)
        self.import_button = FeedbackButton("导入实名码", objectName="ImportDropButton")
        self.import_button.setProperty("dropActive", False)
        self.import_button.clicked.connect(self.choose_import_file)
        self.import_button.setToolTip("支持官方PDF、手机照片和截图；图片会识别链接后重建清晰二维码")
        self.print_button = FeedbackButton("立即打印")
        self.print_button.setEnabled(False)
        self.print_button.setToolTip("生成标签后可提交到当前Windows打印机")
        self.print_button.clicked.connect(self.print_current)
        # In a short window these buttons sit near the bottom of a QScrollArea.
        # If a focused button is disabled while printing, Qt transfers focus
        # to the next control and scrolls it into view. Mouse interaction and
        # press feedback do not require focus, so keep the viewport stationary.
        for action_button in (
            self.monitor_button,
            self.latest_button,
            self.import_button,
            self.print_button,
        ):
            action_button.setFocusPolicy(Qt.NoFocus)
        button_grid.addWidget(self.monitor_button, 0, 0)
        button_grid.addWidget(self.latest_button, 0, 1)
        button_grid.addWidget(self.import_button, 1, 0)
        button_grid.addWidget(self.print_button, 1, 1)
        actions_layout.addLayout(button_grid)
        options = QHBoxLayout()
        self.auto_print = ToggleSwitch("新增登记自动打印")
        self.auto_print.setChecked(self.settings.auto_print)
        self.auto_print.toggled.connect(self._auto_print_changed)
        self.manual_auto = ToggleSwitch("导入后自动打印")
        self.manual_auto.setChecked(self.settings.manual_import_auto_print)
        self.manual_auto.toggled.connect(self._manual_auto_changed)
        options.addWidget(self.auto_print)
        options.addWidget(self.manual_auto)
        actions_layout.addLayout(options)
        auto_layout.addWidget(actions_card)

        status_card = QFrame(objectName="SidebarCard")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 11, 14, 11)
        status_layout.setSpacing(6)
        status_header = QHBoxLayout()
        status_header.addWidget(QLabel("运行状况", objectName="SectionTitle"))
        status_header.addStretch()
        self.mode_chip = QLabel("UOM官网", objectName="ModeChip")
        status_header.addWidget(self.mode_chip)
        status_layout.addLayout(status_header)
        self.status_detail = QLabel("等待开始监听", objectName="StatusDetail")
        self.status_detail.setWordWrap(True)
        status_layout.addWidget(self.status_detail)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_view.setMaximumHeight(112)
        self.log_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_layout.addWidget(self.log_view)
        auto_layout.addWidget(status_card)

        menu_card = QFrame(objectName="SidebarCard")
        menu_layout = QGridLayout(menu_card)
        menu_layout.setContentsMargins(12, 10, 12, 10)
        menu_layout.setSpacing(7)
        menu_buttons = (
            ("设置", self.open_settings),
            ("打印机", self.open_printer_dialog),
            ("标签文件", self.open_output),
            ("日志", self.open_logs),
            ("悬浮窗", self.toggle_floating),
            ("关于软件", self.show_about),
        )
        for index, (text, callback) in enumerate(menu_buttons):
            button = FeedbackButton(text, objectName="MenuButton")
            button.clicked.connect(callback)
            menu_layout.addWidget(button, index // 3, index % 3)
            if text == "打印机":
                self.printer_menu_button = button
            elif text == "悬浮窗":
                self.floating_button = button
        auto_layout.addWidget(menu_card)
        auto_layout.addStretch()

        self.lookup_card = QFrame(objectName="LookupDropCard")
        self.lookup_card.setProperty("dropActive", False)
        self.lookup_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        lookup_layout = QVBoxLayout(self.lookup_card)
        lookup_layout.setContentsMargins(14, 13, 14, 14)
        lookup_layout.setSpacing(9)
        lookup_layout.addWidget(QLabel("实名信息查询", objectName="SectionTitle"))
        lookup_intro = QLabel(
            "序列号用于快速查询基础信息；完整联系电话请导入或直接拖入机身实名码照片、截图或PDF。",
            objectName="StatusDetail",
        )
        lookup_intro.setWordWrap(True)
        lookup_layout.addWidget(lookup_intro)
        lookup_row = QHBoxLayout()
        lookup_row.setSpacing(8)
        self.lookup_serial_input = QLineEdit()
        self.lookup_serial_input.setPlaceholderText("输入飞行器序列号")
        self.lookup_serial_input.setClearButtonEnabled(True)
        self.lookup_serial_input.returnPressed.connect(self.query_registration)
        self.lookup_button = FeedbackButton("序列号查询", objectName="Accent")
        self.lookup_button.clicked.connect(self.query_registration)
        lookup_row.addWidget(self.lookup_serial_input, 1)
        lookup_row.addWidget(self.lookup_button)
        lookup_layout.addLayout(lookup_row)
        self.lookup_qr_button = FeedbackButton("导入机身实名码", objectName="MenuButton")
        self.lookup_qr_button.setProperty("dropActive", False)
        self.lookup_qr_button.clicked.connect(self.choose_registration_code)
        self.lookup_qr_button.setToolTip("支持点击选择，也可把实名码照片、截图或PDF直接拖进软件")
        lookup_layout.addWidget(self.lookup_qr_button)
        self.lookup_state = QLabel("等待输入序列号", objectName="LookupState")
        self.lookup_state.setProperty("state", "idle")
        self.lookup_state.setWordWrap(True)
        self.lookup_state.setMaximumHeight(72)
        self.lookup_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        lookup_layout.addWidget(self.lookup_state)
        query_layout.addWidget(self.lookup_card)

        result_card = QFrame(objectName="SidebarCard")
        result_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(14, 13, 14, 14)
        result_layout.setSpacing(9)
        result_header = QHBoxLayout()
        result_header.addWidget(QLabel("查询结果", objectName="SectionTitle"))
        result_header.addStretch()
        self.lookup_source = QLabel("尚未查询", objectName="ModeChip")
        result_header.addWidget(self.lookup_source)
        self.lookup_owned_actions = QFrame(objectName="LookupOwnedActions")
        owned_actions_layout = QHBoxLayout(self.lookup_owned_actions)
        owned_actions_layout.setContentsMargins(3, 3, 3, 3)
        owned_actions_layout.setSpacing(4)
        self.lookup_print_button = FeedbackButton("打印", objectName="LookupPrint", elevated=False)
        self.lookup_print_button.setFixedSize(68, 30)
        self.lookup_print_button.setEnabled(False)
        self.lookup_print_button.setToolTip("生成当前设备标签并提交到已选打印机")
        self.lookup_print_button.clicked.connect(self.print_lookup_result)
        owned_actions_layout.addWidget(self.lookup_print_button)
        self.lookup_owned_actions.hide()
        result_header.addWidget(self.lookup_owned_actions)
        result_layout.addLayout(result_header)
        result_grid = QGridLayout()
        result_grid.setHorizontalSpacing(10)
        result_grid.setVerticalSpacing(8)
        self.lookup_values: dict[str, QLabel] = {}
        lookup_fields = (
            ("实名标识", "uas_code"),
            ("所有人", "owner_name"),
            ("手机号", "phone_number"),
            ("机型", "model_name"),
            ("产品型号", "product_model"),
            ("序列号", "aircraft_serial"),
            ("空机重量", "empty_weight"),
            ("登记状态", "status"),
        )
        for row_index, (caption, key) in enumerate(lookup_fields):
            caption_label = QLabel(caption, objectName="LookupCaption")
            value_label = QLabel("—", objectName="LookupValue")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setWordWrap(True)
            result_grid.addWidget(caption_label, row_index, 0, Qt.AlignTop)
            result_grid.addWidget(value_label, row_index, 1)
            self.lookup_values[key] = value_label
        result_grid.setColumnStretch(1, 1)
        result_layout.addLayout(result_grid)
        copy_row = QHBoxLayout()
        copy_row.setContentsMargins(0, 1, 0, 0)
        copy_row.addStretch()
        self.lookup_copy_button = FeedbackButton("复制信息", objectName="LookupCopy", elevated=False)
        self.lookup_copy_button.setFixedSize(86, 30)
        self.lookup_copy_button.setEnabled(False)
        self.lookup_copy_button.setToolTip("复制当前查询卡片中的全部信息")
        self.lookup_copy_button.clicked.connect(self.copy_lookup_information)
        copy_row.addWidget(self.lookup_copy_button)
        result_layout.addLayout(copy_row)
        query_layout.addWidget(result_card)

        self.product_card = QFrame(objectName="SidebarCard")
        self.product_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        product_layout = QVBoxLayout(self.product_card)
        product_layout.setContentsMargins(14, 13, 14, 14)
        product_layout.setSpacing(8)
        product_header = QHBoxLayout()
        product_header.addWidget(QLabel("大疆官方机型资料", objectName="SectionTitle"))
        product_header.addStretch()
        product_header.addWidget(QLabel("DJI官网", objectName="ModeChip"))
        product_layout.addLayout(product_header)
        self.lookup_product_image = QLabel("查询后显示对应机型图片", objectName="ProductImage")
        self.lookup_product_image.setAlignment(Qt.AlignCenter)
        self.lookup_product_image.setFixedHeight(168)
        product_layout.addWidget(self.lookup_product_image)
        self.lookup_product_title = QLabel("等待查询", objectName="ProductTitle")
        self.lookup_product_title.setWordWrap(True)
        product_layout.addWidget(self.lookup_product_title)
        self.lookup_product_summary = QLabel("匹配成功后显示大疆官网的简短产品参数。", objectName="ProductSummary")
        self.lookup_product_summary.setWordWrap(True)
        self.lookup_product_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        product_layout.addWidget(self.lookup_product_summary)
        query_layout.addWidget(self.product_card)

        self.web_card = QFrame(objectName="WebCard")
        web_layout = QVBoxLayout(self.web_card)
        web_layout.setContentsMargins(0, 0, 0, 0)
        web_layout.setSpacing(0)
        web_toolbar = QFrame(objectName="WebToolbar")
        toolbar_layout = QHBoxLayout(web_toolbar)
        toolbar_layout.setContentsMargins(15, 10, 12, 10)
        toolbar_layout.setSpacing(8)
        self.sidebar_toggle_button = FeedbackButton("收起", objectName="SidebarToggle", elevated=False)
        self.sidebar_toggle_button.setToolTip("折叠左侧控制栏，让UOM网页占满内容区")
        self.sidebar_toggle_button.clicked.connect(self.toggle_sidebar)
        toolbar_layout.addWidget(self.sidebar_toggle_button)
        self.web_title_label = QLabel("UOM 官方平台", objectName="SectionTitle")
        toolbar_layout.addWidget(self.web_title_label)
        self.refresh_uom_button = FeedbackButton("刷新", objectName="GhostSmall", elevated=False)
        self.refresh_uom_button.clicked.connect(self._refresh_active_web)
        toolbar_layout.addWidget(self.refresh_uom_button)
        toolbar_layout.addStretch()
        dji_logged_in = bool(self.dji_web is not None and self.dji_web.is_logged_in)
        self.dji_login_status = QLabel(
            "大疆查询：已登录" if dji_logged_in else "大疆查询：未登录",
            objectName="DjiLoginStatus",
        )
        self.dji_login_status.setProperty("loggedIn", dji_logged_in)
        self.dji_login_status.setToolTip(
            "DJI官网会话正常"
            if dji_logged_in
            else "DJI官网尚未登录"
        )
        toolbar_layout.addWidget(self.dji_login_status)
        self.dji_open_button = FeedbackButton(
            "大疆查询",
            objectName="DjiOpenButton",
            elevated=False,
        )
        self.dji_open_button.setToolTip("在左侧打开窄高的大疆官方验证区，右侧继续保留UOM")
        self.dji_open_button.clicked.connect(self.open_dji_login)
        toolbar_layout.addWidget(self.dji_open_button)
        self.uom_state = QLabel(
            "UOM：已登录" if self.uom_web.is_logged_in else "UOM：未登录",
            objectName="StatusChip",
        )
        self.uom_state.setProperty("state", "success" if self.uom_web.is_logged_in else "idle")
        self.web_home_button = FeedbackButton("UOM首页", objectName="GhostSmall", elevated=False)
        self.web_home_button.setToolTip("切换右侧到UOM官方首页")
        self.web_home_button.clicked.connect(self.go_uom_home)
        toolbar_layout.addWidget(self.uom_state)
        toolbar_layout.addWidget(self.web_home_button)
        web_layout.addWidget(web_toolbar)
        self.web_progress = QProgressBar(objectName="WebLoadProgress")
        self.web_progress.setRange(0, 100)
        self.web_progress.setValue(0)
        self.web_progress.setTextVisible(False)
        self.web_progress.setFixedHeight(3)
        self.web_progress.hide()
        web_layout.addWidget(self.web_progress)
        self.dji_verification_bar = QFrame(objectName="DjiVerificationBar")
        dji_verification_layout = QVBoxLayout(self.dji_verification_bar)
        dji_verification_layout.setContentsMargins(12, 10, 10, 10)
        dji_verification_layout.setSpacing(7)
        dji_verification_title_row = QHBoxLayout()
        dji_verification_title_row.setContentsMargins(0, 0, 0, 0)
        dji_verification_title_row.setSpacing(8)
        self.dji_verification_badge = QLabel("DJI", objectName="DjiVerificationBadge")
        self.dji_verification_badge.setAlignment(Qt.AlignCenter)
        self.dji_verification_badge.setFixedSize(34, 24)
        dji_verification_title_row.addWidget(self.dji_verification_badge)
        self.dji_verification_title = QLabel("大疆官方验证", objectName="DjiVerificationTitle")
        dji_verification_title_row.addWidget(self.dji_verification_title)
        dji_verification_title_row.addStretch()
        self.dji_verification_cancel_button = FeedbackButton(
            "取消识别",
            objectName="DjiVerificationCancel",
            elevated=False,
        )
        self.dji_verification_cancel_button.setToolTip("取消本次精准机型查询")
        self.dji_verification_cancel_button.clicked.connect(self._cancel_dji_inline_verification)
        dji_verification_title_row.addWidget(self.dji_verification_cancel_button)
        dji_verification_layout.addLayout(dji_verification_title_row)
        self.dji_verification_status = QLabel(
            "请在下方大疆官方页面完成登录或滑块。",
            objectName="DjiVerificationInlineStatus",
        )
        self.dji_verification_status.setProperty("state", "working")
        self.dji_verification_status.setWordWrap(True)
        dji_verification_layout.addWidget(self.dji_verification_status)
        self.dji_verification_bar.hide()
        self.uom_view: QWebEngineView | None = None
        self.dji_view: QWebEngineView | None = None
        self.dji_sidebar_overlay: QFrame | None = None
        self.dji_sidebar_progress: QProgressBar | None = None
        self.web_content_stack: QStackedWidget | None = None
        if self.wine_compat_mode:
            compat_panel = QFrame(objectName="WineCompatPanel")
            compat_layout = QVBoxLayout(compat_panel)
            compat_layout.setContentsMargins(40, 40, 40, 40)
            compat_layout.addStretch()
            compat_title = QLabel("离线界面测试模式", objectName="WineCompatTitle")
            compat_title.setAlignment(Qt.AlignCenter)
            compat_detail = QLabel(
                "已停用会导致黑屏的嵌入式 UOM 网页渲染。\n\n"
                "你仍可测试手动导入PDF或图片、二维码识别、标签预览和文件生成。\n"
                "UOM 登录、持续监听和得力打印机请在真实 Windows 系统中测试。",
                objectName="WineCompatDetail",
            )
            compat_detail.setAlignment(Qt.AlignCenter)
            compat_detail.setWordWrap(True)
            compat_layout.addWidget(compat_title)
            compat_layout.addSpacing(14)
            compat_layout.addWidget(compat_detail)
            compat_layout.addStretch()
            web_layout.addWidget(compat_panel, 1)
        else:
            self.web_content_stack = QStackedWidget(objectName="OfficialWebStack")
            self.uom_view = QWebEngineView(self)
            self.uom_view.setPage(self.uom_web.page)
            self.uom_view.loadStarted.connect(self._web_load_started)
            self.uom_view.loadProgress.connect(self._web_load_progress)
            self.uom_view.loadFinished.connect(self._web_load_finished)
            self.web_content_stack.addWidget(self.uom_view)
            web_layout.addWidget(self.web_content_stack, 1)
            if self.dji_web is not None:
                self.dji_sidebar_overlay = QFrame(self.sidebar_panel, objectName="DjiSidebarOverlay")
                dji_sidebar_layout = QVBoxLayout(self.dji_sidebar_overlay)
                dji_sidebar_layout.setContentsMargins(0, 0, 0, 0)
                dji_sidebar_layout.setSpacing(0)
                dji_sidebar_layout.addWidget(self.dji_verification_bar)
                self.dji_sidebar_progress = QProgressBar(objectName="DjiSidebarProgress")
                self.dji_sidebar_progress.setRange(0, 100)
                self.dji_sidebar_progress.setValue(0)
                self.dji_sidebar_progress.setTextVisible(False)
                self.dji_sidebar_progress.setFixedHeight(3)
                self.dji_sidebar_progress.hide()
                dji_sidebar_layout.addWidget(self.dji_sidebar_progress)
                self.dji_view = QWebEngineView(self.dji_sidebar_overlay)
                self.dji_view.setObjectName("DjiSidebarWebView")
                self.dji_view.setPage(self.dji_web.page)
                self.dji_view.loadStarted.connect(self._dji_sidebar_load_started)
                self.dji_view.loadProgress.connect(self._dji_sidebar_load_progress)
                self.dji_view.loadFinished.connect(self._dji_sidebar_load_finished)
                dji_sidebar_layout.addWidget(self.dji_view, 1)
                self.dji_sidebar_overlay.setGeometry(self.sidebar_panel.rect())
                self.dji_sidebar_overlay.hide()
        self.body_layout.addWidget(self.web_card, 1)

        self.sidebar_drop_overlay = QFrame(self.sidebar_panel, objectName="SidebarDropOverlay")
        self.sidebar_drop_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        overlay_layout = QVBoxLayout(self.sidebar_drop_overlay)
        overlay_layout.setContentsMargins(24, 24, 24, 24)
        overlay_layout.addStretch()
        self.sidebar_drop_prompt = QFrame(objectName="SidebarDropPrompt")
        self.sidebar_drop_prompt.setMaximumWidth(248)
        prompt_layout = QVBoxLayout(self.sidebar_drop_prompt)
        prompt_layout.setContentsMargins(22, 15, 22, 14)
        prompt_layout.setSpacing(4)
        self.sidebar_drop_title = QLabel("松手即可导入", objectName="SidebarDropTitle")
        self.sidebar_drop_title.setAlignment(Qt.AlignCenter)
        self.sidebar_drop_detail = QLabel("PDF  ·  照片  ·  截图", objectName="SidebarDropDetail")
        self.sidebar_drop_detail.setAlignment(Qt.AlignCenter)
        prompt_layout.addWidget(self.sidebar_drop_title)
        prompt_layout.addWidget(self.sidebar_drop_detail)
        overlay_layout.addWidget(self.sidebar_drop_prompt, 0, Qt.AlignHCenter)
        overlay_layout.addStretch()
        self.sidebar_drop_overlay.hide()
        self.sidebar_panel.installEventFilter(self)

        QTimer.singleShot(0, self._refresh_printers)
        QTimer.singleShot(0, lambda: self._set_sidebar_collapsed(self.settings.sidebar_collapsed, announce=False))

    def pipeline(self) -> ProcessingPipeline:
        from ..pipeline import ProcessingPipeline

        return ProcessingPipeline(self.settings, self.history, lambda level, message: self.workflow_log.emit(level, message))

    def _show_header_message(self, title: str, subtitle: str, state: str, duration_ms: int = 4200) -> None:
        self.header_bubble.set_message(title, subtitle, state)
        self.compact_header_bubble.set_message(title, subtitle, state)
        self.header_message_timer.start(duration_ms)

    def _restore_header_message(self) -> None:
        self.header_bubble.set_message(self.DEFAULT_BUBBLE_TITLE, self.DEFAULT_BUBBLE_SUBTITLE, "idle")
        self.compact_header_bubble.set_message(self.DEFAULT_BUBBLE_TITLE, self.DEFAULT_BUBBLE_SUBTITLE, "idle")

    def _copy_summary(self) -> str:
        qr_copies = max(1, int(self.settings.qr_label_copies))
        info_copies = max(1, int(self.settings.info_label_copies))
        return f"自动打印：标签1×{info_copies}，标签2×{qr_copies}，共{qr_copies + info_copies}张"

    def _copy_counts_changed(self, _value: int = 0) -> None:
        self.settings.qr_label_copies = self.qr_copies.value()
        self.settings.info_label_copies = self.info_copies.value()
        self.store.save(self.settings)
        self.copy_summary.setText(self._copy_summary())
        self.print_button.setToolTip(self._copy_summary())

    def _auto_print_changed(self, checked: bool) -> None:
        self.settings.auto_print = bool(checked)
        self.store.save(self.settings)
        self.append_log("info", "新增登记自动打印已开启。" if checked else "新增登记自动打印已关闭。")

    def _manual_auto_changed(self, checked: bool) -> None:
        self.settings.manual_import_auto_print = bool(checked)
        self.store.save(self.settings)
        self.append_log("info", "导入后自动打印已开启。" if checked else "导入后自动打印已关闭，只生成标签。")

    def _apply_sidebar_scroll_restore(self) -> None:
        if self._sidebar_scroll_restore_value is None:
            return
        self.sidebar_scroll.verticalScrollBar().setValue(self._sidebar_scroll_restore_value)

    def _finish_sidebar_scroll_restore(self) -> None:
        self._apply_sidebar_scroll_restore()
        self._sidebar_scroll_restore_value = None

    def _restore_sidebar_scroll_after_layout(self, value: int) -> None:
        """Undo QScrollArea's focus/layout auto-scroll without blocking user scrolling."""
        self._sidebar_scroll_restore_value = max(0, int(value))
        self._apply_sidebar_scroll_restore()
        # Qt may transfer focus and call ensureWidgetVisible after the current
        # signal returns. Restore once on the next event cycle and once after
        # the style/layout changes have settled.
        self.sidebar_scroll_restore_timer.start(0)
        self.sidebar_scroll_restore_followup.start(45)

    def _set_sidebar_action_enabled(self, button: FeedbackButton, enabled: bool) -> None:
        scroll_value = self.sidebar_scroll.verticalScrollBar().value()
        button.setEnabled(enabled)
        self._restore_sidebar_scroll_after_layout(scroll_value)

    def _switch_sidebar_mode(self, index: int) -> None:
        normalized = max(0, min(2, int(index)))
        if normalized == 0:
            self._set_lookup_drop_active(False)
        elif normalized == 1:
            self._set_sidebar_drop_active(False)
        else:
            self._set_lookup_drop_active(False)
            self._set_sidebar_drop_active(False)
        if self.sidebar_pages.currentIndex() != normalized:
            self.sidebar_pages.setCurrentIndex(normalized)
            self.sidebar_pages.updateGeometry()
            if self.sidebar_pages.currentWidget() is not None:
                self.sidebar_pages.currentWidget().updateGeometry()
            self.sidebar_scroll.verticalScrollBar().setValue(0)
        for button, active in (
            (self.auto_mode_button, normalized == 0),
            (self.lookup_mode_button, normalized == 1),
            (self.registration_mode_button, normalized == 2),
        ):
            if bool(button.property("active")) == active:
                continue
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)
        # This is deliberately a view-only switch. Do not touch monitor_timer,
        # self.monitoring, the UOM page, or any queued print task here.
        if normalized != 2 and self._active_web_source == "dji" and not (
            self.dji_web is not None and self.dji_web.query_active
        ):
            self._show_web_source("uom")
        if normalized == 2:
            QTimer.singleShot(0, self._maybe_start_first_model_catalog_update)
        QTimer.singleShot(0, self._sync_sidebar_page_height)

    def _sync_sidebar_page_height(self) -> None:
        page = self.sidebar_pages.currentWidget()
        if page is None:
            return
        layout = page.layout()
        width = max(350, self.sidebar_scroll.viewport().width())
        height = layout.heightForWidth(width) if layout is not None and layout.hasHeightForWidth() else -1
        if height <= 0:
            height = page.sizeHint().height()
        self.sidebar_pages.setFixedHeight(max(1, height))
        if self.sidebar_pages.currentIndex() in (1, 2) and layout is not None:
            layout.activate()
            content_bottom = max(
                (
                    item.widget().geometry().bottom() + 1
                    for index in range(layout.count())
                    if (item := layout.itemAt(index)).widget() is not None
                ),
                default=height,
            )
            height = content_bottom + layout.contentsMargins().bottom()
            self.sidebar_pages.setFixedHeight(max(1, height))
        self.sidebar_pages.updateGeometry()

    def _set_lookup_state(self, text: str, state: str) -> None:
        self.lookup_state.setText(text)
        self.lookup_state.setProperty("state", state)
        self.lookup_state.style().unpolish(self.lookup_state)
        self.lookup_state.style().polish(self.lookup_state)

    def _set_registration_state(self, text: str, state: str) -> None:
        self.registration_state.setText(text)
        self.registration_state.setProperty("state", state)
        self.registration_state.style().unpolish(self.registration_state)
        self.registration_state.style().polish(self.registration_state)
        self.registration_panel.sync_registration_card_height()
        QTimer.singleShot(0, self._sync_sidebar_page_height)

    def _refresh_model_catalog_ui(self) -> None:
        summary = self.model_catalog.summary()
        if not summary.available:
            self.registration_panel.set_model_catalog_status(
                "本地型号库尚未更新。首次使用请登录UOM，软件会从两个官网拉取完整数据。",
                "empty",
                busy=self._model_catalog_update_busy,
            )
            self._refresh_registration_action_button()
            return
        updated_text = summary.updated_at
        try:
            updated_text = datetime.fromisoformat(updated_text).astimezone().strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            updated_text = "时间未知"
        self.registration_panel.set_model_catalog_status(
            f"本地型号库  UOM {summary.uom_count} 条 · DJI {summary.dji_count} 条 · {updated_text}",
            "ready",
            busy=self._model_catalog_update_busy,
        )
        self._refresh_registration_action_button()

    def _maybe_start_first_model_catalog_update(self) -> None:
        if (
            self._model_catalog_first_update_attempted
            or self._model_catalog_update_busy
            or self.model_catalog.summary().available
        ):
            return
        if not self.uom_web.is_logged_in:
            self.registration_panel.set_model_catalog_status(
                "首次使用需要先登录UOM；登录后会自动拉取UOM与大疆官网型号。",
                "empty",
            )
            return
        self._model_catalog_first_update_attempted = True
        self.start_model_catalog_update()

    def start_model_catalog_update(self) -> None:
        if self._model_catalog_update_busy:
            return
        if not self.uom_web.is_logged_in:
            self._set_official_web_collapsed(False, announce=False)
            self._show_web_source("uom")
            self.registration_panel.set_model_catalog_status(
                "请先登录右侧UOM官网，再更新本地型号库。",
                "error",
            )
            self.registration_model_update_button.flash_error()
            self._set_registration_state("型号库更新需要有效的UOM登录，不需要人脸认证。", "warning")
            return

        self._model_catalog_update_generation += 1
        generation = self._model_catalog_update_generation
        self._model_catalog_update_busy = True
        self._model_catalog_pending_uom = None
        self._model_catalog_pending_dji = None
        self.registration_panel.set_model_catalog_status(
            "正在并行读取UOM全部大疆型号和DJI官网产品目录…",
            "working",
            busy=True,
        )
        self._refresh_registration_action_button()
        self._set_registration_state("正在更新本地型号库，现有登记资料和旧型号库不会改变。", "working")
        self.append_log("step", "开始更新本地型号库：UOM官方型号 + DJI官网产品目录。")
        QTimer.singleShot(50000, lambda: self._model_catalog_update_timed_out(generation))

        def uom_ready(payload: dict[str, Any]) -> None:
            if generation != self._model_catalog_update_generation or not self._model_catalog_update_busy:
                return
            self._model_catalog_pending_uom = dict(payload)
            self._finish_model_catalog_update_if_ready(generation)

        def uom_failed(message: str) -> None:
            self._fail_model_catalog_update(generation, f"UOM型号读取失败：{message}")

        self.uom_web.fetch_official_brand_models(
            self.DJI_UOM_MANUFACTURER,
            uom_ready,
            uom_failed,
        )
        if generation != self._model_catalog_update_generation or not self._model_catalog_update_busy:
            return

        worker = Worker(fetch_dji_support_catalog)
        worker.signals.result.connect(
            lambda products: self._model_catalog_dji_ready(generation, products)
        )
        worker.signals.error.connect(
            lambda message, _trace: self._fail_model_catalog_update(
                generation,
                f"大疆产品目录读取失败：{message}",
            )
        )
        self._start_worker(worker)

    def _model_catalog_update_timed_out(self, generation: int) -> None:
        if generation != self._model_catalog_update_generation or not self._model_catalog_update_busy:
            return
        self._fail_model_catalog_update(
            generation,
            "更新等待超时，请检查UOM页面、系统时间和网络后重试。",
        )

    def _model_catalog_dji_ready(self, generation: int, products: object) -> None:
        if generation != self._model_catalog_update_generation or not self._model_catalog_update_busy:
            return
        if not isinstance(products, list):
            self._fail_model_catalog_update(generation, "大疆产品目录返回格式异常。")
            return
        self._model_catalog_pending_dji = [
            dict(item) for item in products if isinstance(item, dict)
        ]
        self._finish_model_catalog_update_if_ready(generation)

    def _finish_model_catalog_update_if_ready(self, generation: int) -> None:
        if generation != self._model_catalog_update_generation or not self._model_catalog_update_busy:
            return
        if self._model_catalog_pending_uom is None or self._model_catalog_pending_dji is None:
            return
        payload = self._model_catalog_pending_uom
        manufacturer = dict(payload.get("manufacturer") or {})
        models = [dict(item) for item in payload.get("models") or [] if isinstance(item, dict)]
        try:
            catalog = self.model_catalog.save_sources(
                manufacturer,
                models,
                self._model_catalog_pending_dji,
            )
        except (OSError, ModelCatalogError) as exc:
            self._fail_model_catalog_update(generation, str(exc))
            return

        sources = catalog["sources"]
        uom_count = int(sources["uom"]["count"])
        dji_count = int(sources["dji"]["count"])
        self._model_catalog_update_busy = False
        self._model_catalog_pending_uom = None
        self._model_catalog_pending_dji = None
        self._refresh_model_catalog_ui()
        self.registration_model_update_button.flash_success()
        self._set_registration_state(
            f"本地型号库更新完成：UOM {uom_count} 条，DJI {dji_count} 条。",
            "success",
        )
        self.append_log("ok", f"本地型号库更新完成：UOM {uom_count} 条，DJI {dji_count} 条。")
        if self._registration_face_verified and self._registration_dji_result is not None:
            then_upload = self._registration_model_selection_then_upload or bool(
                self._registration_prepared_photos
            )
            QTimer.singleShot(0, lambda: self._match_registration_uom_model(then_upload=then_upload))

    def _fail_model_catalog_update(self, generation: int, message: str) -> None:
        if generation != self._model_catalog_update_generation or not self._model_catalog_update_busy:
            return
        self._model_catalog_update_generation += 1
        self._model_catalog_update_busy = False
        self._model_catalog_pending_uom = None
        self._model_catalog_pending_dji = None
        old_summary = self.model_catalog.summary()
        suffix = "，已继续保留上一次完整型号库。" if old_summary.available else "，本机仍没有可用型号库。"
        self.registration_panel.set_model_catalog_status(
            f"更新失败：{message}{suffix}",
            "error",
        )
        self._refresh_registration_action_button()
        self.registration_model_update_button.flash_error()
        self._set_registration_state(f"型号库更新失败：{message}{suffix}", "error")
        self.append_log("warn", f"本地型号库更新失败：{message}{suffix}")

    def _set_cancellation_state(self, text: str, state: str) -> None:
        self.cancellation_state.setText(text)
        self.cancellation_state.setProperty("state", state)
        self.cancellation_state.style().unpolish(self.cancellation_state)
        self.cancellation_state.style().polish(self.cancellation_state)
        QTimer.singleShot(0, self._sync_sidebar_page_height)

    def _registration_input_changed(self, text: str) -> None:
        serial = str(text or "").strip()
        if self._registration_resolved_serial and serial != self._registration_resolved_serial:
            self._reset_registration_resolution(keep_status=False)
        self._refresh_registration_action_button()

    @staticmethod
    def _uom_failure_kind(message: object) -> str:
        explicit = str(getattr(message, "kind", "") or "").strip().lower()
        if explicit:
            return explicit
        text = str(message or "").lower()
        if any(marker in text for marker in ("超时", "网络", "连接", "加载", "暂时", "runtime")):
            return "network"
        if any(marker in text for marker in ("登录", "令牌", "401", "403", "会话")):
            return "session"
        return "business"

    def _begin_registration_operation(self, stage: str) -> int:
        self._registration_operation_generation += 1
        self._registration_stage = str(stage or "idle")
        self._registration_failure_kind = ""
        self._refresh_registration_action_button()
        return self._registration_operation_generation

    def _pause_registration(self, stage: str, message: object, *, notify: bool = True) -> None:
        error_text = str(message or "实名登记暂未完成。")
        kind = self._uom_failure_kind(message)
        self._registration_operation_generation += 1
        self._registration_stage = str(stage or self._registration_stage or "face")
        self._registration_failure_kind = kind
        if self._registration_stage == "face":
            self._registration_face_request_generation += 1
            self.registration_face_timer.stop()
            self._registration_face_polling = False
            self._registration_face_poll_inflight = False
        self._set_registration_controls_busy(False)

        self._refresh_registration_action_button()
        if kind in {"network", "unknown", "session"}:
            detail = f"{error_text} 本次序列号、照片和已完成步骤都已保留，可以再试一次。"
        else:
            detail = f"{error_text} 本次资料已保留，请检查提示后再试。"
        self._set_registration_state(detail, "error")
        if notify:
            self._notify("UOM实名登记未完成", error_text, error=True)

    def _retry_or_prepare_registration(self) -> None:
        stage = self._registration_stage
        if not self.uom_web.is_logged_in:
            self._set_official_web_collapsed(False, announce=False)
            self._show_web_source("uom")
            self._set_registration_state("请先重新登录UOM，本次序列号和照片仍然保留。", "warning")
            return
        if stage == "submit_unknown":
            self._verify_registration_after_unknown_submit()
            return
        if stage == "ready_submit" and self._registration_pending_form is not None:
            self.submit_prepared_registration()
            return
        if stage == "model" and self._registration_face_verified:
            self._match_registration_uom_model(then_upload=True)
            return
        if stage in {"upload_front", "upload_serial"} and self._registration_face_verified:
            self._upload_registration_photos()
            return
        if stage in {"face", "face_closed"} and self._registration_prepared_photos:
            self._set_registration_controls_busy(True)
            self._set_registration_state("正在重新生成UOM官方人脸认证码…", "working")
            self._begin_registration_operation("face")
            self._request_registration_face_context(self._registration_face_provider)
            return
        self.prepare_uom_registration()

    def _registration_primary_action(self) -> None:
        """Route the single visible action to the next safe workflow step."""

        if (
            self._registration_dji_result is not None
            or self._registration_pending_form is not None
            or self._registration_face_verified
            or self._registration_stage
            in {
                "face",
                "face_closed",
                "model",
                "model_selection",
                "upload_front",
                "upload_serial",
                "ready_submit",
                "submitting",
                "submit_unknown",
                "uom_login",
            }
        ):
            self._retry_or_prepare_registration()
            return
        self.start_dji_registration_lookup()

    def _reset_registration_resolution(self, *, keep_status: bool) -> None:
        self._registration_operation_generation += 1
        if self.dji_web is not None:
            self.dji_web.cancel_query()
        self._hide_dji_inline_verification()
        self._registration_face_request_generation += 1
        self.registration_face_timer.stop()
        self._registration_face_polling = False
        self._registration_face_poll_inflight = False
        self._registration_face_started_polls = 0
        self._registration_face_wait_polls = 0
        if self.registration_face_dialog is not None:
            dialog = self.registration_face_dialog
            self.registration_face_dialog = None
            try:
                dialog.finished.disconnect(self._registration_face_dialog_closed)
            except (RuntimeError, TypeError):
                pass
            dialog.close()
            dialog.deleteLater()
        self._registration_prepared_photos.clear()
        self._registration_dji_result = None
        self._registration_uom_model = None
        self._registration_model_match_source = ""
        self._clear_registration_model_candidates()
        self._registration_owner = None
        self._registration_face_provider = "wx"
        self._registration_available_face_providers = ("wx",)
        self._registration_face_verified = False
        self._registration_pending_form = None
        self._registration_stage = "idle"
        self._registration_failure_kind = ""
        self._registration_front_quote = ""
        self._registration_serial_quote = ""
        self._registration_submit_unknown_checks = 0
        self._registration_resolved_serial = ""
        self.registration_model_chip.setText("待识别")
        self.registration_model_title.setText("尚未读取大疆官方机型")
        self.registration_model_detail.setText("大疆型号先保存在本地，人脸认证通过后才查询UOM型号。")
        self._registration_submit_prompt_open = False
        self._set_registration_controls_busy(False)
        self._refresh_registration_action_button()
        if not keep_status:
            self._set_registration_state("序列号已改变，请重新识别并认证。", "warning")

    def _confirm_reset_registration_flow(self) -> None:
        if not self.registration_reset_button.isEnabled():
            return
        if not confirm_danger(
            self,
            "重置当前实名流程",
            "将清空本次序列号、两张照片、机型识别、人脸认证进度和待提交资料。",
            confirm_text="确认重置",
            cancel_text="继续处理",
            detail="UOM/DJI登录、型号库、打印设置、标签预设和已完成的历史记录不会改变。",
        ):
            return
        self._reset_registration_flow()

    def _reset_registration_flow(self) -> None:
        self._reset_registration_resolution(keep_status=True)
        for slot in self._registration_photo_preview_generation:
            self._registration_photo_preview_generation[slot] += 1
        self._registration_photo_paths = {"front": None, "serial": None}
        self.registration_front_tile.set_file(None)
        self.registration_serial_tile.set_file(None)
        blocker = QSignalBlocker(self.registration_serial_input)
        self.registration_serial_input.clear()
        del blocker
        self._refresh_registration_action_button()
        self._set_registration_state("当前实名流程已重置，可以重新填写。", "success")
        self._show_header_message("本次流程已重置", "登录、型号库和软件设置都没有改变。", "success")
        self.append_log("info", "已手动重置当前实名流程，未改变登录和本地型号库。")

    def _choose_registration_photo(self, slot: str) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择机身照片" if slot == "front" else "选择序列号照片",
            "",
            "照片 (*.heic *.heif *.jpg *.jpeg *.png *.webp);;所有文件 (*.*)",
        )
        if not filename:
            return
        self._set_registration_photo(slot, Path(filename))

    def _registration_photo_dropped(self, slot: str, filename: str) -> None:
        path = Path(filename)
        if not PhotoDropTile.accepts_path(path):
            self._set_registration_state("仅支持HEIC、HEIF、JPG、PNG或WebP照片。", "error")
            return
        self._set_registration_photo(slot, path)
        self._set_registration_state(
            "机身照片已拖入。" if slot == "front" else "序列号照片已拖入。",
            "success",
        )

    def _set_registration_photo(self, slot: str, path: Path) -> None:
        if not PhotoDropTile.accepts_path(path):
            self._set_registration_state("这个文件不是支持的照片格式。", "error")
            return
        workflow_started = bool(
            self._registration_dji_result is not None
            or self._registration_face_verified
            or self._registration_pending_form is not None
            or self._registration_stage not in {"idle", "dji"}
        )
        if workflow_started:
            self._reset_registration_resolution(keep_status=True)
        self._registration_photo_preview_generation[slot] += 1
        self._registration_photo_paths[slot] = path
        tile = self.registration_front_tile if slot == "front" else self.registration_serial_tile
        tile.set_file(path)
        if not tile.has_preview():
            self._start_registration_photo_preview(slot, path)
        self._registration_prepared_photos.pop(slot, None)
        if slot == "front":
            self._registration_front_quote = ""
            self._registration_serial_quote = ""
        else:
            self._registration_serial_quote = ""
        self._registration_pending_form = None
        self._refresh_registration_action_button()
        if workflow_started:
            self._set_registration_state("照片已更换，请重新识别并认证，旧的待提交资料已作废。", "warning")

    def _start_registration_photo_preview(self, slot: str, path: Path) -> None:
        generation = self._registration_photo_preview_generation[slot]
        worker = Worker(
            prepare_registration_photo,
            path,
            filename=f"uom-{slot}.jpg",
            max_bytes=640 * 1024,
            max_dimension=1280,
        )

        def prepared(photo: PreparedRegistrationPhoto) -> None:
            if (
                generation != self._registration_photo_preview_generation[slot]
                or self._registration_photo_paths.get(slot) != path
            ):
                return
            tile = self.registration_front_tile if slot == "front" else self.registration_serial_tile
            if not tile.set_preview_data(photo.data):
                tile.clear_preview("!")
                tile.detail_label.setText("预览失败，请更换")

        def failed(_message: str, _trace: str) -> None:
            if (
                generation != self._registration_photo_preview_generation[slot]
                or self._registration_photo_paths.get(slot) != path
            ):
                return
            tile = self.registration_front_tile if slot == "front" else self.registration_serial_tile
            tile.clear_preview("!")
            tile.detail_label.setText("预览失败，请更换")

        worker.signals.result.connect(prepared)
        worker.signals.error.connect(failed)
        self._start_worker(worker)

    def _set_registration_controls_busy(self, busy: bool) -> None:
        self._registration_controls_busy = bool(busy)
        self.registration_front_tile.setEnabled(not busy)
        self.registration_serial_tile.setEnabled(not busy)
        self.registration_serial_input.setEnabled(not busy)
        self._refresh_registration_action_button()

    def _refresh_registration_action_button(self) -> None:
        """Keep the single registration action aligned with the workflow stage."""
        if not hasattr(self, "registration_identify_button"):
            return

        stage = self._registration_stage
        busy = bool(getattr(self, "_registration_controls_busy", False))
        has_pending_form = self._registration_pending_form is not None
        has_serial = bool(self.registration_serial_input.text().strip())
        has_photos = all(self._registration_photo_paths.values())
        has_base_inputs = bool(
            self._registration_dji_result is not None
            and has_serial
            and has_photos
        )
        has_prepared_photos = all(
            slot in self._registration_prepared_photos for slot in ("front", "serial")
        )

        text = "识别并认证"
        enabled = has_serial and has_photos and not busy
        tooltip = "填写序列号并放入两张照片后开始"
        workflow_state = "action" if enabled else "waiting"

        if stage == "submitting":
            text = "正在提交…"
            tooltip = "实名登记正在提交到UOM官方平台"
            workflow_state = "working"
        elif stage == "submit_unknown" and has_pending_form:
            text = "核对登记结果"
            enabled = not busy and not self._registration_submit_prompt_open
            tooltip = "先核对当前账号，避免网络中断后重复提交"
        elif has_pending_form:
            text = "继续提交"
            enabled = stage == "ready_submit" and not busy and not self._registration_submit_prompt_open
            tooltip = "人脸已验证，继续打开最终确认并提交"
        elif self._registration_face_polling:
            text = "等待人脸验证…"
            enabled = False
            tooltip = "请在手机上完成UOM人脸验证"
            workflow_state = "working"
        elif stage == "model_selection":
            text = "请先选择精准机型"
            enabled = False
            tooltip = "请在精准机型卡片中选择UOM型号代码并点击“选好了”"
            workflow_state = "waiting"
        elif self._registration_face_verified:
            if self._registration_failure_kind and stage in {"model", "upload_front", "upload_serial"}:
                text = "继续准备"
                enabled = has_base_inputs and not busy
                tooltip = "人脸已验证，从中断步骤继续准备提交资料"
            else:
                text = "正在准备登记资料…"
                enabled = False
                tooltip = "人脸已验证，正在自动匹配型号并准备资料"
                workflow_state = "working"
        elif stage == "face_closed" and has_base_inputs and has_prepared_photos:
            text = "重新打开人脸认证"
            enabled = not busy
            tooltip = "重新生成UOM官方人脸验证二维码"
        elif self._registration_failure_kind and has_base_inputs:
            text = "重新打开人脸认证" if has_prepared_photos else "继续准备"
            enabled = not busy
            tooltip = (
                "重新生成UOM官方人脸验证二维码"
                if has_prepared_photos
                else "重试照片处理和实名登记准备"
            )
        elif stage == "face":
            text = "正在准备人脸认证…"
            enabled = False
            tooltip = "正在准备UOM官方人脸验证"
            workflow_state = "working"
        elif self._registration_dji_result is not None:
            text = "继续人脸认证" if self.uom_web.is_logged_in else "登录UOM后继续"
            enabled = has_base_inputs and not busy
            tooltip = "继续进入UOM官方人脸验证" if enabled else "请先完成当前资料准备"
        elif stage == "dji":
            text = "正在查询大疆机型…"
            enabled = False
            tooltip = "请在大疆官方验证区完成登录或滑块"
            workflow_state = "working"
        elif stage == "dji_failed":
            text = "重新识别并认证"
            enabled = has_serial and has_photos and not busy
            tooltip = "重新发起大疆官方机型查询"
        elif not self.model_catalog.summary().available:
            text = "先更新型号库"
            enabled = False
            tooltip = "请先点击精准机型卡片右侧的更新"

        if enabled:
            workflow_state = "action"
        button = self.registration_identify_button
        button.setText(text)
        button.setEnabled(enabled)
        if button.property("workflowState") != workflow_state:
            button.setProperty("workflowState", workflow_state)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()
        button.setToolTip(tooltip)
        reset_available = bool(
            has_serial
            or any(self._registration_photo_paths.values())
            or stage != "idle"
            or self._registration_dji_result is not None
            or self._registration_face_verified
            or has_pending_form
        )
        self.registration_reset_button.setEnabled(reset_available)

    def start_dji_registration_lookup(self) -> None:
        serial = self.registration_serial_input.text().strip()
        if len(serial) < 6:
            self._set_registration_state("序列号太短，请检查后重试。", "error")
            self.registration_identify_button.flash_error()
            return
        if not all(self._registration_photo_paths.values()):
            self._set_registration_state("请先放入机身照片和序列号照片，再开始识别认证。", "error")
            self.registration_identify_button.flash_error()
            return
        if not self.model_catalog.summary().available:
            self._set_registration_state(
                "首次使用需要先完成本地型号库更新；更新完成后再点击“识别并认证”。",
                "warning",
            )
            self.registration_identify_button.flash_error()
            self._maybe_start_first_model_catalog_update()
            return
        if self.dji_web is None:
            information(self, "当前环境不支持", "当前测试环境不加载大疆官方网页，请在Windows正式版中使用。")
            return
        self._reset_registration_resolution(keep_status=True)
        self._begin_registration_operation("dji")
        self._registration_resolved_serial = serial
        self._set_registration_controls_busy(True)
        self._dji_inline_verification_active = True
        self._show_web_source("dji")
        self._set_dji_inline_verification(
            "请在左侧大疆官方验证区完成登录或滑块，成功后会自动继续。",
            "working",
        )
        self._set_registration_state("请在左侧大疆官方验证区完成登录或滑块。", "working")
        self.dji_web.start_query(serial)

    def _dji_status_changed(self, message: str, state: str) -> None:
        if self._dji_inline_verification_active:
            self._set_dji_inline_verification(message, state)
        self._set_registration_state(message, state)

    def _dji_query_failed(self, message: str) -> None:
        self._registration_stage = "dji_failed"
        self._set_registration_controls_busy(False)
        self.registration_identify_button.flash_error()
        self._set_registration_state(message, "error")
        if self._dji_inline_verification_active:
            self._set_dji_inline_verification(message, "error", query_active=False)

    def _dji_result_ready(self, result: object) -> None:
        if not isinstance(result, DjiDeviceResult):
            self._dji_query_failed("大疆官方返回的机型数据格式异常。")
            return
        self._registration_dji_result = result
        self._hide_dji_inline_verification()
        self.registration_model_chip.setText("DJI已确认")
        self.registration_model_title.setText(result.product_name)
        details = ["大疆官方序列号查询已返回精准产品名。"]
        if result.active_time:
            details.append(f"激活时间：{result.active_time}")
        self.registration_model_detail.setText("\n".join(details))
        self.registration_identify_button.flash_success()
        self._show_web_source("uom")
        if self.uom_web.is_logged_in:
            self._set_registration_state(
                "大疆精准机型已确认，正在准备UOM官方人脸认证；认证前不会查询UOM型号或上传登记资料。",
                "success",
            )
            self.prepare_uom_registration()
        else:
            self._registration_stage = "uom_login"
            self._set_registration_controls_busy(False)
            self._set_registration_state("大疆机型已识别，请在右侧登录UOM后再开始人脸认证。", "warning")

    def _clear_registration_model_candidates(self) -> None:
        self._registration_model_candidates = []
        self._registration_model_candidate_manufacturer = {}
        self._registration_model_selection_then_upload = False
        if hasattr(self, "registration_panel"):
            self.registration_panel.clear_model_candidates()

    def _apply_registration_uom_model(
        self,
        manufacturer: dict[str, Any],
        model: dict[str, Any],
        dji_result: DjiDeviceResult,
        *,
        then_upload: bool,
        match_source: str,
    ) -> None:
        selected_model = dict(model)
        selected_model["shengccsid"] = str(
            manufacturer.get("id") or selected_model.get("shengccsid") or ""
        )
        selected_model["shengccsmc"] = str(
            manufacturer.get("unitName") or selected_model.get("shengccsmc") or ""
        )
        self._registration_uom_model = selected_model
        self._registration_model_match_source = str(match_source or "人工确认")
        self._clear_registration_model_candidates()
        self.registration_model_chip.setText("UOM已匹配")
        self.registration_model_title.setText(
            str(selected_model.get("chanpmc") or dji_result.product_name)
        )
        self.registration_model_detail.setText(
            f"UOM型号代码：{str(selected_model.get('chanpxh') or '—')}\n"
            f"空机重量：{str(selected_model.get('kongjzl') or '—')} kg  ·  "
            f"最大起飞重量：{str(selected_model.get('zuidqfzl') or '—')} kg\n"
            f"匹配来源：{self._registration_model_match_source}"
        )
        self._set_registration_state("人脸认证已通过，UOM精准机型匹配成功。", "success")
        self._refresh_registration_action_button()
        if then_upload:
            self._upload_registration_photos()
        else:
            self._set_registration_controls_busy(False)

    def _confirm_registration_uom_model_candidate(self) -> None:
        if self._registration_stage != "model_selection":
            return
        selected = self.registration_panel.selected_model_candidate()
        if selected is None:
            self.registration_model_chip.setText("请选择")
            self._set_registration_state("请先选择一个UOM型号代码，再点击“选好了”。", "warning")
            return
        result = self._registration_dji_result
        if result is None or not self._registration_face_verified:
            self._reset_registration_resolution(keep_status=True)
            self._set_registration_state("本次认证状态已失效，请重新识别并认证。", "error")
            return
        manufacturer = dict(self._registration_model_candidate_manufacturer)
        then_upload = self._registration_model_selection_then_upload
        self._apply_registration_uom_model(
            manufacturer,
            selected,
            result,
            then_upload=then_upload,
            match_source="人工确认",
        )

    def _match_registration_uom_model(self, then_upload: bool = False) -> None:
        if not self._registration_face_verified:
            self._set_registration_state("尚未完成UOM人脸认证，已拦截型号查询和登记数据。", "warning")
            return
        result = self._registration_dji_result
        if result is None:
            self._set_registration_state("请先完成大疆精准机型识别。", "warning")
            return
        if not self.uom_web.is_logged_in:
            self._show_web_source("uom")
            self._set_registration_state("请先在右侧登录UOM官网。", "warning")
            return
        self._clear_registration_model_candidates()
        self._begin_registration_operation("model")
        self._set_registration_state("正在使用本地完整型号库做唯一精确匹配…", "working")
        catalog = self.model_catalog.load()
        if catalog is None:
            self._registration_model_selection_then_upload = then_upload
            self.registration_model_chip.setText("需更新")
            self._pause_registration("model", "本地型号库尚未更新，请先点击精准机型右侧的“更新”。")
            return
        sources = catalog.get("sources") if isinstance(catalog, dict) else None
        uom_source = sources.get("uom") if isinstance(sources, dict) else None
        dji_source = sources.get("dji") if isinstance(sources, dict) else None
        if not isinstance(uom_source, dict) or not isinstance(dji_source, dict):
            self._pause_registration("model", "本地双来源型号库格式异常，请重新更新。")
            return
        manufacturer = dict(uom_source.get("manufacturer") or {})
        models = [
            dict(item) for item in uom_source.get("models") or [] if isinstance(item, dict)
        ]
        official_product_names = [
            str(item.get("title") or "")
            for item in dji_source.get("products") or []
            if isinstance(item, dict)
        ]
        resolution = rank_uom_model_candidates(
            result.product_name,
            models,
            official_product_names=official_product_names,
        )
        if not bool(resolution.get("ok")):
            self.registration_model_chip.setText("需更新")
            self._pause_registration(
                "model",
                str(resolution.get("message") or "本地UOM型号库没有可用型号，请重新更新。"),
            )
            return
        if bool(resolution.get("ambiguous")):
            candidates = [
                dict(candidate)
                for candidate in resolution.get("candidates") or []
                if isinstance(candidate, dict)
            ]
            all_models = [
                dict(candidate)
                for candidate in resolution.get("allModels") or models
                if isinstance(candidate, dict)
            ]
            if not candidates or not manufacturer:
                self._pause_registration("model", "本地型号库没有可供确认的型号。")
                return
            match_type = str(resolution.get("matchType") or "manual_fallback")
            self._registration_uom_model = None
            self._registration_model_candidates = candidates
            self._registration_model_candidate_manufacturer = manufacturer
            self._registration_model_selection_then_upload = then_upload
            self._registration_stage = "model_selection"
            self._registration_failure_kind = ""
            self.registration_model_chip.setText("请选择")
            self.registration_model_title.setText(result.product_name)
            self.registration_model_detail.setText(
                f"本地库给出 {len(candidates)} 个优先候选。请核对型号代码和重量；"
                f"找不到时可搜索全部 {len(all_models)} 个UOM型号。"
            )
            self.registration_panel.show_model_candidates(
                candidates,
                all_models=all_models,
                match_type=match_type,
            )
            self._set_registration_state(
                "人脸认证已通过；当前结果不能安全自动决定，请手动选择正确型号。",
                "warning",
            )
            self._refresh_registration_action_button()
            return
        model = dict(resolution.get("model") or {})
        if not manufacturer or not model:
            self._pause_registration("model", "本地UOM型号库匹配结果格式异常。")
            return
        self._apply_registration_uom_model(
            manufacturer,
            model,
            result,
            then_upload=then_upload,
            match_source="自动精确匹配",
        )

    def prepare_uom_registration(self) -> None:
        if self._registration_dji_result is None:
            self._set_registration_state("请先完成大疆精准机型识别。", "warning")
            return
        if not all(self._registration_photo_paths.values()):
            self._set_registration_state("请先选择机身照片和序列号照片。", "error")
            return
        if not self.uom_web.is_logged_in:
            self._show_web_source("uom")
            self._set_registration_state("请先在右侧登录UOM官网。", "warning")
            return
        self._set_registration_controls_busy(True)
        generation = self._begin_registration_operation("face")
        self._set_registration_state("正在校正HEIC/照片方向并压缩到3MB以内…", "working")
        front_path = self._registration_photo_paths["front"]
        serial_path = self._registration_photo_paths["serial"]
        worker = Worker(self._prepare_registration_photos_task, front_path, serial_path)

        def prepared(result: dict[str, PreparedRegistrationPhoto]) -> None:
            if generation != self._registration_operation_generation:
                return
            self._registration_prepared_photos = dict(result)
            self._set_registration_state(
                "照片只在本地处理完成，正在生成UOM官方人脸认证码；尚未上传任何登记资料…",
                "working",
            )
            self._request_registration_face_context(self._registration_face_provider)

        worker.signals.result.connect(prepared)
        worker.signals.error.connect(
            lambda message, _trace: self._registration_failed(message, stage="face")
            if generation == self._registration_operation_generation
            else None
        )
        self._start_worker(worker)

    @staticmethod
    def _prepare_registration_photos_task(
        front_path: Path | None,
        serial_path: Path | None,
    ) -> dict[str, PreparedRegistrationPhoto]:
        if front_path is None or serial_path is None:
            raise RegistrationValidationError("请选择两张登记照片。")
        return {
            "front": prepare_registration_photo(front_path, filename="uom-front.jpg"),
            "serial": prepare_registration_photo(serial_path, filename="uom-serial.jpg"),
        }

    def _request_registration_face_context(self, provider: str) -> None:
        normalized = str(provider or "wx").strip().lower()
        self._registration_face_verified = False
        self._registration_face_request_generation += 1
        generation = self._registration_face_request_generation
        self.registration_face_timer.stop()
        self._registration_face_polling = False
        self._registration_face_poll_inflight = False
        self._registration_face_started_polls = 0
        self._registration_face_wait_polls = 0
        self.uom_web.fetch_personal_registration_context(
            lambda payload: self._registration_context_ready(payload, generation),
            lambda message: self._registration_face_request_failed(generation, message),
            provider=normalized,
        )

    def _registration_face_request_failed(self, generation: int, message: str) -> None:
        if generation != self._registration_face_request_generation:
            return
        self._registration_face_poll_inflight = False
        self._registration_failed(message)

    def _registration_context_ready(
        self,
        payload: dict[str, Any],
        generation: int | None = None,
    ) -> None:
        if generation is not None and generation != self._registration_face_request_generation:
            return
        if generation is None:
            self._registration_face_request_generation += 1
            generation = self._registration_face_request_generation
        owner = payload.get("owner")
        provider = str(payload.get("faceProvider") or "wx").strip().lower()
        if provider not in FaceVerificationDialog.PROVIDER_LABELS:
            provider = "wx"
        available_providers = tuple(
            str(item.get("value") or "").strip().lower()
            for item in (payload.get("availableFaceProviders") or [])
            if isinstance(item, dict)
            and str(item.get("value") or "").strip().lower() in FaceVerificationDialog.PROVIDER_LABELS
        )
        if provider not in available_providers:
            available_providers = (provider, *available_providers)
        qr_data_url = str(payload.get("faceQrDataUrl") or "")
        if not isinstance(owner, dict) or "," not in qr_data_url:
            self._registration_failed("UOM人脸认证数据格式异常。")
            return
        try:
            qr_bytes = base64.b64decode(qr_data_url.split(",", 1)[1], validate=True)
        except (ValueError, TypeError):
            self._registration_failed("UOM人脸认证二维码解析失败。")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(qr_bytes):
            self._registration_failed("UOM人脸认证二维码无法显示。")
            return
        self._registration_owner = dict(owner)
        self._registration_face_provider = provider
        self._registration_available_face_providers = available_providers
        self._registration_face_poll_inflight = False
        self._registration_face_started_polls = 0
        self._registration_face_wait_polls = 0
        provider_label = self._face_provider_label(provider)
        if self.registration_face_dialog is None:
            self.registration_face_dialog = FaceVerificationDialog(
                self,
                pixmap,
                provider=provider,
                available_providers=available_providers,
            )
            self.registration_face_dialog.finished.connect(self._registration_face_dialog_closed)
            self.registration_face_dialog.provider_switch_requested.connect(
                self._switch_registration_face_provider
            )
        else:
            self.registration_face_dialog.set_provider_qr(provider, pixmap, available_providers)
        self.registration_face_dialog.show()
        self.registration_face_dialog.raise_()
        self.registration_face_dialog.activateWindow()
        self._registration_face_polling = True
        self.registration_face_timer.start()
        self._refresh_registration_action_button()
        self._set_registration_state(f"请用{provider_label}扫码完成UOM人脸认证，软件会自动继续。", "warning")
        QTimer.singleShot(600, self._poll_registration_face)

    @staticmethod
    def _face_provider_label(provider: str) -> str:
        return FaceVerificationDialog.PROVIDER_LABELS.get(str(provider or ""), "官方")

    def _switch_registration_face_provider(self, provider: str) -> None:
        normalized = str(provider or "").strip().lower()
        if normalized not in self._registration_available_face_providers:
            self._registration_failed("UOM当前没有开放这个人脸认证渠道。")
            return
        self.registration_face_timer.stop()
        self._registration_face_polling = False
        self._registration_face_poll_inflight = False
        self._registration_face_provider = normalized
        provider_label = self._face_provider_label(normalized)
        self._set_registration_state(f"正在生成UOM{provider_label}人脸认证码…", "working")
        self._request_registration_face_context(normalized)

    def _poll_registration_face(self) -> None:
        if (
            not self._registration_face_polling
            or self._registration_owner is None
            or self._registration_face_poll_inflight
        ):
            return
        generation = self._registration_face_request_generation
        provider = self._registration_face_provider
        self._registration_face_poll_inflight = True

        def checked(result: dict[str, Any]) -> None:
            if (
                generation != self._registration_face_request_generation
                or provider != self._registration_face_provider
                or not self._registration_face_polling
            ):
                return
            self._registration_face_poll_inflight = False
            provider_label = self._face_provider_label(provider)
            if bool(result.get("completed")):
                self.registration_face_timer.stop()
                self._registration_face_polling = False
                self._registration_face_request_generation += 1
                self._registration_face_verified = True
                if self.registration_face_dialog is not None:
                    self.registration_face_dialog.mark_success()
                self._set_registration_state("人脸认证通过，现在开始查询UOM型号并准备登记资料…", "working")
                self._match_registration_uom_model(then_upload=True)
            elif bool(result.get("started")):
                self._registration_face_started_polls += 1
                if self.registration_face_dialog is not None:
                    if provider == "wx" and self._registration_face_started_polls >= 6:
                        self.registration_face_dialog.set_status(
                            "微信已扫码但暂未继续，可直接切换支付宝重新认证。",
                            "warning",
                        )
                        self.registration_face_dialog.emphasize_provider_switch()
                    else:
                        self.registration_face_dialog.set_status(
                            "已扫码，请在手机上继续完成人脸核验…",
                            "working",
                        )
                self._set_registration_state(f"{provider_label}已扫码，请在手机上继续完成人脸核验…", "warning")
            else:
                self._registration_face_wait_polls += 1
                if self.registration_face_dialog is not None:
                    if provider == "wx" and self._registration_face_wait_polls >= 18:
                        self.registration_face_dialog.set_status(
                            "微信认证长时间没有进展，可切换支付宝或关闭后重新生成。",
                            "warning",
                        )
                        self.registration_face_dialog.emphasize_provider_switch()
                    else:
                        self.registration_face_dialog.set_status("等待扫码和人脸认证…", "working")
                self._set_registration_state(f"等待{provider_label}人脸认证完成…", "warning")

        def failed(message: str) -> None:
            if (
                generation != self._registration_face_request_generation
                or provider != self._registration_face_provider
            ):
                return
            self._registration_face_poll_inflight = False
            self._registration_failed(message)

        self.uom_web.poll_face_verification(
            self._registration_owner,
            provider,
            checked,
            failed,
        )

    def _registration_face_dialog_closed(self, result: int) -> None:
        dialog = self.registration_face_dialog
        if dialog is not None:
            dialog.deleteLater()
        self.registration_face_dialog = None
        if result != int(QDialog.DialogCode.Rejected):
            return
        self._registration_face_request_generation += 1
        self.registration_face_timer.stop()
        self._registration_face_polling = False
        self._registration_face_poll_inflight = False
        self._registration_face_verified = False
        self._registration_stage = "face_closed"
        self._registration_failure_kind = ""
        self._registration_face_started_polls = 0
        self._registration_face_wait_polls = 0
        self._set_registration_controls_busy(False)
        self._refresh_registration_action_button()
        self._set_registration_state("人脸认证已关闭，本次没有提交登记资料。", "warning")

    def _upload_registration_photos(self) -> None:
        if not self._registration_face_verified:
            self._registration_failed("尚未完成UOM人脸认证，已拦截照片上传。", stage="face")
            return
        front = self._registration_prepared_photos.get("front")
        serial = self._registration_prepared_photos.get("serial")
        if front is None or serial is None:
            self._registration_failed("待上传登记照片已丢失，请重新选择。", stage="upload_front")
            return

        stage = "upload_serial" if self._registration_front_quote else "upload_front"
        generation = self._begin_registration_operation(stage)
        self._set_registration_controls_busy(True)

        def upload_serial_photo() -> None:
            if generation != self._registration_operation_generation:
                return
            self._registration_stage = "upload_serial"
            self._refresh_registration_action_button()
            self._set_registration_state("正在上传序列号照片…", "working")

            def serial_uploaded(serial_result: dict[str, str]) -> None:
                if generation != self._registration_operation_generation:
                    return
                self._registration_serial_quote = str(serial_result.get("quoteCode") or "")
                self._build_pending_registration(
                    self._registration_front_quote,
                    self._registration_serial_quote,
                )

            self.uom_web.upload_registration_photo(
                serial.base64_data,
                serial.filename,
                serial_uploaded,
                lambda message: self._registration_failed(message, stage="upload_serial")
                if generation == self._registration_operation_generation
                else None,
            )

        if self._registration_front_quote:
            upload_serial_photo()
            return

        self._set_registration_state("正在上传机身照片…", "working")

        def front_uploaded(front_result: dict[str, str]) -> None:
            if generation != self._registration_operation_generation:
                return
            self._registration_front_quote = str(front_result.get("quoteCode") or "")
            upload_serial_photo()

        self.uom_web.upload_registration_photo(
            front.base64_data,
            front.filename,
            front_uploaded,
            lambda message: self._registration_failed(message, stage="upload_front")
            if generation == self._registration_operation_generation
            else None,
        )

    def _build_pending_registration(self, front_quote: str, serial_quote: str) -> None:
        if not self._registration_face_verified:
            self._registration_failed("尚未完成UOM人脸认证，已拦截登记表单组装。", stage="face")
            return
        if self._registration_owner is None or self._registration_uom_model is None:
            self._registration_failed("实名登记账号或机型数据已丢失。", stage="model")
            return
        try:
            form = build_personal_registration_form(
                self._registration_owner,
                self._registration_uom_model,
                serial=self.registration_serial_input.text().strip(),
                production_date=date.today(),
                front_photo_quote=front_quote,
                serial_photo_quote=serial_quote,
            )
        except RegistrationValidationError as exc:
            self._registration_failed(str(exc), stage="ready_submit")
            return
        self._begin_registration_operation("ready_submit")
        self._registration_pending_form = form
        self._set_registration_controls_busy(False)
        self._refresh_registration_action_button()
        self._set_registration_state("登记资料已准备完成，正在打开最终确认…", "success")
        QTimer.singleShot(0, self.submit_prepared_registration)

    def _registration_summary_text(self, form: dict[str, Any]) -> str:
        purposes = set(form.get("shiyyt") or [])
        purpose_text = "娱乐、航拍" if purposes == {"01", "02"} else "、".join(sorted(purposes))
        return (
            f"登记人：{str(form.get('xingm') or '—')}\n"
            f"机型：{str(form.get('chanpmc') or '—')}  /  {str(form.get('chanpxh') or '—')}\n"
            f"序列号：{str(form.get('chanpxlh') or '—')}\n"
            f"空机重量：{str(form.get('kongjzl') or '—')} kg  ·  最大起飞重量：{str(form.get('zuidqfzl') or '—')} kg\n"
            f"用途：{purpose_text}  ·  生产日期：{str(form.get('mfgDate') or '—')}\n"
            f"型号确认：{self._registration_model_match_source or '未记录'}\n"
            "附件：机身照片、序列号照片已上传"
        )

    def submit_prepared_registration(self) -> None:
        form = self._registration_pending_form
        if form is None:
            self._set_registration_state("还没有可提交的完整登记资料。", "error")
            return
        if self._registration_submit_prompt_open:
            return
        self._registration_submit_prompt_open = True
        summary = self._registration_summary_text(form)
        confirmed = confirm_submit(
            self,
            "确认提交实名登记",
            "请核对本架无人机的最终登记资料。确认后会立即提交到UOM官方平台。",
            detail=summary
            + "\n\n本人确认上述信息和照片真实、准确，并同意提交到UOM官方平台。",
            confirm_text="确认提交",
            cancel_text="取消",
        )
        self._registration_submit_prompt_open = False
        if not confirmed:
            self._registration_stage = "ready_submit"
            self._refresh_registration_action_button()
            self._set_registration_state("已取消提交。本次没有向UOM发送登记资料。", "warning")
            return
        generation = self._begin_registration_operation("submitting")
        self._set_registration_controls_busy(True)
        self._set_registration_state("正在向UOM官方提交实名登记…", "working")
        QTimer.singleShot(5000, lambda: self._registration_submit_waiting(generation, long_wait=False))
        QTimer.singleShot(15000, lambda: self._registration_submit_waiting(generation, long_wait=True))

        def completed(result: dict[str, Any]) -> None:
            if generation != self._registration_operation_generation:
                return
            message = str(result.get("message") or "UOM已接受本次登记。")
            if bool(result.get("productNumberUpdatePending", False)):
                message += "\n实名登记已经成功，产品序列号状态正在后台同步，无需等待或重复登记。"
            elif not bool(result.get("productNumberUpdated", True)):
                message += "\n实名登记已经成功，但产品序列号状态同步暂未完成，无需重复登记。"
            self._clear_registration_session_after_success(message)
            information(self, "实名登记成功", message)
            self._notify("UOM实名登记成功", message)

        def failed(message: object) -> None:
            if generation != self._registration_operation_generation:
                return
            error_text = str(message or "UOM官方接口未返回具体原因。")
            kind = self._uom_failure_kind(message)
            outcome_unknown = bool(getattr(message, "outcome_unknown", False)) or kind == "unknown"
            if outcome_unknown:
                self._registration_submit_unknown_checks = 0
                self._pause_registration("submit_unknown", message, notify=False)
                self._set_registration_state(
                    "UOM连接在提交时中断，不能直接重复提交。资料已保留，软件会先核对当前账号是否已经登记成功。",
                    "warning",
                )
                information(
                    self,
                    "正在核对登记结果",
                    "UOM连接暂时中断，本次资料没有丢失。软件会先查询登记结果，避免重复提交。",
                )
                if self.uom_web.is_logged_in and self.uom_web.is_page_ready:
                    QTimer.singleShot(
                        1800,
                        lambda: self._verify_registration_after_unknown_submit()
                        if self._registration_stage == "submit_unknown"
                        else None,
                    )
                return
            self._pause_registration("ready_submit", message, notify=False)
            information(self, "实名登记未完成", error_text)
            self._notify("UOM实名登记未完成", error_text, error=True)

        self.uom_web.submit_personal_registration(form, completed, failed)

    def _registration_submit_waiting(self, generation: int, *, long_wait: bool) -> None:
        if generation != self._registration_operation_generation or self._registration_stage != "submitting":
            return
        if long_wait:
            message = "UOM官方仍在处理，软件没有卡住。请保持页面在线，不要重复提交…"
        else:
            message = "UOM官方响应有点慢，正在继续等待，请不要重复点击…"
        self._set_registration_state(message, "working")

    def _verify_registration_after_unknown_submit(self) -> None:
        form = self._registration_pending_form
        if form is None:
            self._set_registration_state("待核对的登记资料已经不存在，请重新开始。", "error")
            return
        if not self.uom_web.is_logged_in or not self.uom_web.is_page_ready:
            self._pause_registration(
                "submit_unknown",
                UomWebFailure("UOM官网暂未恢复，恢复连接后再核对登记结果。", kind="network"),
                notify=False,
            )
            return
        serial = str(form.get("chanpxlh") or "").strip()
        if not serial:
            self._pause_registration("ready_submit", "待提交资料缺少序列号，请重新识别。")
            return
        generation = self._begin_registration_operation("submit_unknown")
        self._set_registration_controls_busy(True)
        self._set_registration_state("正在核对当前账号是否已经登记成功…", "working")

        def checked(rows: list[dict[str, Any]]) -> None:
            if generation != self._registration_operation_generation:
                return
            if rows:
                message = "已从当前UOM账号确认这架设备登记成功。"
                self._clear_registration_session_after_success(message)
                information(self, "实名登记成功", message)
                self._notify("UOM实名登记成功", message)
                return
            self._registration_submit_unknown_checks += 1
            self._set_registration_controls_busy(False)
            if self._registration_submit_unknown_checks >= 2:
                self._registration_stage = "ready_submit"
                self._refresh_registration_action_button()
                self._set_registration_state(
                    "两次核对都没有查到该序列号。本次资料仍保留；如需重新提交，请再次确认后操作。",
                    "warning",
                )
            else:
                self._registration_stage = "submit_unknown"
                self._refresh_registration_action_button()
                self._set_registration_state(
                    "当前暂未查到登记结果，可能仍在同步。本次资料已保留，请稍等后再次核对。",
                    "warning",
                )

        def check_failed(message: object) -> None:
            if generation != self._registration_operation_generation:
                return
            self._pause_registration("submit_unknown", message)

        self.uom_web.search_registered_aircraft(serial, checked, check_failed)

    def _clear_registration_session_after_success(self, message: str) -> None:
        self._reset_registration_resolution(keep_status=True)
        for slot in self._registration_photo_preview_generation:
            self._registration_photo_preview_generation[slot] += 1
        self._registration_photo_paths = {"front": None, "serial": None}
        self.registration_front_tile.set_file(None)
        self.registration_serial_tile.set_file(None)
        blocker = QSignalBlocker(self.registration_serial_input)
        self.registration_serial_input.clear()
        del blocker
        self._refresh_registration_action_button()
        self._set_registration_state("实名登记成功，当前资料已清空，可以继续登记下一架。", "success")
        self._show_header_message("这架已经登记好了", "资料已清空，下一架可以直接继续。", "success")

    def _registration_failed(self, message: object, *, stage: str | None = None) -> None:
        self.registration_face_timer.stop()
        self._registration_face_polling = False
        if self.registration_face_dialog is not None:
            self.registration_face_dialog.set_status(str(message or "认证流程失败。"), "error")
            self.registration_face_dialog.switch_button.setEnabled(True)
        self._pause_registration(stage or self._registration_stage or "face", message)

    def query_registration(self) -> None:
        serial = self.lookup_serial_input.text().strip()
        if not serial:
            self._set_lookup_state("请输入飞行器序列号。", "error")
            self.lookup_button.flash_error()
            return
        self.lookup_serial_input.setText(serial)
        self.lookup_button.setEnabled(False)
        self.lookup_button.setText("查询中…")
        self.lookup_qr_button.setEnabled(False)
        self.lookup_request_generation += 1
        request_generation = self.lookup_request_generation
        self.lookup_public_request_generation = -1
        self._clear_lookup_result_actions()
        self._reset_lookup_ownership()
        self.append_log("step", f"正在查询飞行器序列号：{serial}")
        if self.uom_web.is_logged_in:
            self._set_lookup_state("正在核对当前账号登记记录…", "working")
            self.uom_web.search_registered_aircraft(
                serial,
                lambda rows: self._lookup_authenticated_rows(serial, rows, request_generation),
                lambda message: self._start_public_lookup(
                    serial,
                    login_error=message,
                    request_generation=request_generation,
                    ownership_checked=True,
                ),
            )
        else:
            self._set_lookup_state("正在通过UOM官方序列号接口快速查询…", "working")
            self._start_public_lookup(
                serial,
                request_generation=request_generation,
                ownership_checked=True,
            )

    def _lookup_authenticated_rows(
        self,
        serial: str,
        rows: list[dict[str, Any]],
        request_generation: int | None = None,
    ) -> None:
        if request_generation is not None and request_generation != self.lookup_request_generation:
            return
        match = next(
            (
                row
                for row in rows
                if serial.casefold()
                in {
                    str(row.get("chanpxlh") or "").strip().casefold(),
                    str(row.get("uasCode") or "").strip().casefold(),
                }
            ),
            None,
        )
        if match is None:
            self._start_public_lookup(
                serial,
                request_generation=request_generation,
                ownership_checked=True,
            )
            return
        worker = Worker(self._lookup_authenticated_task, match)
        generation = self.lookup_request_generation if request_generation is None else request_generation
        worker.signals.result.connect(lambda result: self._lookup_succeeded_for(generation, result))
        worker.signals.error.connect(lambda message, trace: self._lookup_failed_for(generation, message, trace))
        self._start_worker(worker)

    def choose_registration_code(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择机身实名码照片或PDF",
            "",
            "实名码文件 (*.jpg *.jpeg *.png *.bmp *.webp *.pdf)",
        )
        if not filename:
            self.append_log("info", "已取消导入机身实名码。")
            return

        self.process_registration_code(Path(filename))

    def process_registration_code(self, path: Path) -> None:
        self.lookup_request_generation += 1
        request_generation = self.lookup_request_generation
        self.lookup_public_request_generation = -1
        self._clear_lookup_result_actions()
        self._reset_lookup_ownership()
        self.lookup_button.setEnabled(False)
        self.lookup_qr_button.setEnabled(False)
        self.lookup_qr_button.setText("识别中…")
        self._set_lookup_state("正在识别实名码并读取UOM官方登记详情…", "working")
        self.append_log("step", f"正在识别机身实名码：{path.name}")
        worker = Worker(self._lookup_registration_code_task, path)
        worker.signals.result.connect(lambda result: self._lookup_succeeded_for(request_generation, result))
        worker.signals.error.connect(
            lambda message, trace: self._lookup_failed_for(request_generation, message, trace)
        )
        self._start_worker(worker)

    def _lookup_registration_code_task(self, path: Path) -> dict[str, Any]:
        payload = extract_uom_payload_from_file(path)
        record = fetch_uom_record(payload)
        return {
            "record": record,
            "product": self._lookup_product(record.model_name, record.manufacturer),
            "source": "机身实名码",
            "detail_error": "",
        }

    def _start_public_lookup(
        self,
        serial: str,
        login_error: str = "",
        request_generation: int | None = None,
        ownership_checked: bool = False,
    ) -> None:
        generation = self.lookup_request_generation if request_generation is None else request_generation
        if generation != self.lookup_request_generation:
            return
        if self.lookup_public_request_generation == generation:
            return
        self.lookup_public_request_generation = generation
        if login_error:
            self.file_logger.warning("登录态查询不可用，已降级到公开序列号接口 | %s", login_error)
        worker = Worker(self._lookup_public_task, serial, ownership_checked)
        worker.signals.result.connect(lambda result: self._lookup_succeeded_for(generation, result))
        worker.signals.error.connect(lambda message, trace: self._lookup_failed_for(generation, message, trace))
        self._start_worker(worker)

    def _lookup_succeeded_for(self, request_generation: int, result: dict[str, Any]) -> None:
        if request_generation != self.lookup_request_generation:
            return
        self._lookup_succeeded(result)

    def _lookup_failed_for(self, request_generation: int, message: str, trace: str) -> None:
        if request_generation != self.lookup_request_generation:
            return
        self._lookup_failed(message, trace)

    def _lookup_product(self, model_name: str, manufacturer: str) -> DjiProductInfo | None:
        identity = f"{manufacturer} {model_name}".lower()
        if "dji" not in identity and "大疆" not in identity:
            return None
        try:
            return fetch_dji_product(model_name)
        except Exception as exc:
            self.file_logger.warning("大疆官方机型资料查询失败 | model=%s | error=%s", model_name, exc)
            return None

    def _lookup_authenticated_task(self, row: dict[str, Any]) -> dict[str, Any]:
        record = record_from_uom_row(row)
        detail_error = ""
        if not is_complete_phone_number(record.phone_number):
            try:
                detail = fetch_uom_record(record.qr_payload)
                if is_complete_phone_number(detail.phone_number):
                    record.phone_number = detail.phone_number
                if detail.empty_weight:
                    record.empty_weight = detail.empty_weight
            except Exception as exc:
                detail_error = str(exc)
        return {
            "record": record,
            "product": self._lookup_product(record.model_name, record.manufacturer),
            "source": "当前账号登记",
            "detail_error": detail_error,
            "account_row": row,
            "ownership_checked": True,
        }

    def _lookup_public_task(self, serial: str, ownership_checked: bool = False) -> dict[str, Any]:
        record = fetch_uom_record_by_serial(serial, timeout=8)
        return {
            "record": record,
            "product": self._lookup_product(record.model_name, record.manufacturer),
            "source": "UOM公开查询",
            "detail_error": "",
            "ownership_checked": ownership_checked,
        }

    def _lookup_succeeded(self, result: dict[str, Any]) -> None:
        record = result["record"]
        self._reset_lookup_ownership()
        self._lookup_record = record
        self.lookup_copy_button.setEnabled(True)
        self.lookup_owned_actions.show()
        self.lookup_print_button.setEnabled(True)
        for key, label in self.lookup_values.items():
            label.setText(str(getattr(record, key, "") or "—"))
        complete_phone = is_complete_phone_number(record.phone_number)
        source = str(result.get("source") or "UOM查询")
        self.lookup_source.setText(source)
        if complete_phone:
            if source == "机身实名码":
                self._set_lookup_state("识别成功，已显示UOM实名码详情中的联系电话。", "success")
            else:
                self._set_lookup_state("查询成功，已显示当前账号可访问的完整实名信息。", "success")
        else:
            self._set_lookup_state("查询成功；该手机号由UOM官方脱敏，非当前账号记录不会强行解码。", "warning")

        product = result.get("product")
        self.lookup_product_image.setPixmap(QPixmap())
        if isinstance(product, DjiProductInfo):
            product_pixmap = QPixmap()
            if product.image_bytes:
                product_pixmap.loadFromData(product.image_bytes)
            if not product_pixmap.isNull():
                rendered = product_pixmap.scaled(
                    318,
                    158,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.lookup_product_image.setText("")
                self.lookup_product_image.setPixmap(rendered)
            else:
                self.lookup_product_image.setText("已匹配机型，官方图片暂时加载失败")
            self.lookup_product_title.setText(product.title or record.model_name)
            features = [part.strip() for part in product.summary.split("|") if part.strip()]
            lines = [f"• {part}" for part in features]
            if product.specs:
                lines.extend(["", "核心技术参数"])
                lines.extend(f"• {part}" for part in product.specs)
            self.lookup_product_summary.setText("\n".join(lines) or "大疆官网暂无产品参数。")
        else:
            self.lookup_product_image.setText("未匹配到大疆官方机型图片")
            self.lookup_product_title.setText(record.model_name or "未知机型")
            self.lookup_product_summary.setText("实名信息查询不受影响；官方产品资料将保持为空。")

        self.lookup_product_summary.updateGeometry()
        self.product_card.updateGeometry()
        if self.sidebar_pages.currentWidget() is not None:
            self.sidebar_pages.currentWidget().updateGeometry()
        self.sidebar_pages.updateGeometry()
        QTimer.singleShot(0, self._sync_sidebar_page_height)

        if result.get("detail_error"):
            self.file_logger.warning("当前账号记录手机号补全失败 | %s", result["detail_error"])
        self.lookup_button.setEnabled(True)
        self.lookup_button.setText("序列号查询")
        self.lookup_qr_button.setEnabled(True)
        self.lookup_qr_button.setText("导入机身实名码")
        if source == "机身实名码":
            self.lookup_qr_button.flash_success()
        else:
            self.lookup_button.flash_success()
        self.append_log("ok", f"实名信息查询完成：{record.aircraft_serial}")
        account_row = result.get("account_row")
        if isinstance(account_row, dict):
            self._set_lookup_ownership(account_row)
        elif self.uom_web.is_logged_in and not result.get("ownership_checked"):
            identifier = str(record.aircraft_serial or record.uas_code or "").strip()
            if identifier:
                generation = self.lookup_request_generation
                self.uom_web.search_registered_aircraft(
                    identifier,
                    lambda rows: self._lookup_ownership_verified(generation, rows),
                    lambda message: self._lookup_ownership_failed(generation, message),
                )

    def _lookup_failed(self, message: str, trace: str) -> None:
        self._clear_lookup_result_actions()
        self._reset_lookup_ownership()
        self.lookup_button.setEnabled(True)
        self.lookup_button.setText("序列号查询")
        self.lookup_qr_button.setEnabled(True)
        self.lookup_qr_button.setText("导入机身实名码")
        self.lookup_button.flash_error()
        self.lookup_qr_button.flash_error()
        self._set_lookup_state(f"查询失败：{message}", "error")
        self.append_log("warn", f"实名信息查询失败：{message}")
        self.file_logger.error("实名信息查询失败\n%s", trace)

    def _clear_lookup_result_actions(self) -> None:
        self._lookup_record = None
        if hasattr(self, "lookup_copy_button"):
            self.lookup_copy_button.setEnabled(False)

    def _reset_lookup_ownership(self) -> None:
        self._lookup_account_row = None
        if hasattr(self, "lookup_owned_actions"):
            self.lookup_owned_actions.hide()
            self.lookup_print_button.setText("打印")
            self.lookup_print_button.setEnabled(False)

    def _set_lookup_ownership(self, row: dict[str, Any]) -> None:
        self._lookup_account_row = dict(row)
        self.lookup_owned_actions.show()
        self.lookup_print_button.setEnabled(True)

    def _lookup_ownership_verified(self, generation: int, rows: list[dict[str, Any]]) -> None:
        if generation != self.lookup_request_generation or not rows:
            return
        self._set_lookup_ownership(rows[0])
        self._set_lookup_state("查询成功，已确认属于当前账号。需要注销请切换到“实名/注销”。", "success")
        self.append_log("ok", "当前查询结果属于已登录账号；注销入口位于实名/注销页面。")

    def _lookup_ownership_failed(self, generation: int, message: str) -> None:
        if generation != self.lookup_request_generation:
            return
        self.file_logger.warning("当前账号归属校验失败 | %s", message)

    def copy_lookup_information(self) -> None:
        if self._lookup_record is None:
            self.lookup_copy_button.flash_error()
            return
        fields = (
            ("实名标识", "uas_code"),
            ("所有人", "owner_name"),
            ("手机号", "phone_number"),
            ("机型", "model_name"),
            ("产品型号", "product_model"),
            ("序列号", "aircraft_serial"),
            ("空机重量", "empty_weight"),
            ("登记状态", "status"),
        )
        lines = [
            f"{caption}：{str(getattr(self._lookup_record, key, '') or '—')}"
            for caption, key in fields
        ]
        lines.append(f"信息来源：{self.lookup_source.text() or 'UOM查询'}")
        QApplication.clipboard().setText("\n".join(lines))
        self.lookup_copy_button.flash_success()
        self.append_log("ok", "查询结果信息已复制到剪贴板。")

    def print_lookup_result(self) -> None:
        record = self._lookup_record
        if record is None:
            return
        if not self.settings.printer_name:
            self.lookup_print_button.flash_error()
            information(self, "请先选择打印机", "请在左下角“打印机”中选择Windows打印机后再试。")
            return
        row = self._lookup_row_for_print(record)
        if row is None:
            self.lookup_print_button.flash_error()
            information(
                self,
                "暂时无法打印",
                "UOM本次查询结果缺少可重建二维码的登记编号，请稍后重试或导入机身实名码。",
            )
            return
        self.lookup_print_button.setEnabled(False)
        self.lookup_print_button.setText("处理中")
        self.append_log("step", "正在为当前查询记录生成并打印标签。")
        worker = Worker(self._uom_row_task, row, True)

        def completed(result: dict[str, Any]) -> None:
            labels = result.get("labels")
            if isinstance(labels, ProcessedLabelSet):
                self.show_labels(labels)
            if result.get("print_error"):
                self.lookup_print_button.flash_error()
                self.append_log("error", f"标签已生成，但打印失败：{result['print_error']}")
                information(self, "打印未完成", str(result["print_error"]))
                return
            self.lookup_print_button.flash_success()
            self.append_log("ok", f"当前查询设备的标签已提交：{self._copy_summary()}。")
            self._notify("UOM标签已提交", self._copy_summary())

        def failed(message: str, trace: str) -> None:
            self.lookup_print_button.flash_error()
            self.report_exception("查询结果打印失败", message, trace)

        def finished() -> None:
            self.lookup_print_button.setText("打印")
            self.lookup_print_button.setEnabled(self._lookup_record is not None)

        worker.signals.result.connect(completed)
        worker.signals.error.connect(failed)
        worker.signals.finished.connect(finished)
        self._start_worker(worker)

    def _lookup_row_for_print(self, record: UomRecord) -> dict[str, Any] | None:
        if self._lookup_account_row is not None:
            return dict(self._lookup_account_row)
        if not record.qr_payload:
            return None
        row = dict(record.raw)
        row.update(
            {
                "uasCode": record.uas_code,
                "chanpmc": record.model_name,
                "chanpxlh": record.aircraft_serial,
                "xingm": record.owner_name,
                "shoujhm": record.phone_number,
                "chanpxh": record.product_model,
                "shengccsmc": record.manufacturer,
                "zhuangt": record.status,
                "erwm": record.qr_payload,
            }
        )
        return row

    def start_registration_cancellation(self) -> None:
        identifier = self.cancellation_serial_input.text().strip()
        if not identifier:
            self.cancellation_button.flash_error()
            self._set_cancellation_state("请输入序列号或唯一识别码。", "error")
            return
        if not self.uom_web.is_logged_in:
            self.cancellation_button.flash_error()
            self._set_cancellation_state("请先在右侧登录UOM官网。", "warning")
            information(self, "请登录UOM", "当前登录已失效，请先在右侧UOM官网重新登录。")
            return
        self.registration_cancellation_generation += 1
        generation = self.registration_cancellation_generation
        self.cancellation_serial_input.setEnabled(False)
        self.cancellation_button.setEnabled(False)
        self.cancellation_button.setText("查询中")
        self._set_cancellation_state("正在核对当前账号名下的实名设备…", "working")
        self.uom_web.search_registered_aircraft(
            identifier,
            lambda rows: self._registration_cancellation_rows(generation, identifier, rows),
            lambda message: self._registration_cancellation_lookup_failed(generation, message),
        )

    def _registration_cancellation_rows(
        self,
        generation: int,
        identifier: str,
        rows: list[dict[str, Any]],
    ) -> None:
        if generation != self.registration_cancellation_generation:
            return
        normalized = identifier.casefold()
        row = next(
            (
                dict(candidate)
                for candidate in rows
                if normalized
                in {
                    str(candidate.get("chanpxlh") or "").strip().casefold(),
                    str(candidate.get("uasCode") or "").strip().casefold(),
                }
            ),
            None,
        )
        if row is None:
            self._finish_registration_cancellation_controls(clear_input=True)
            self.cancellation_button.flash_error()
            self._set_cancellation_state("这个机器不是你的，无法注销。", "error")
            information(self, "无法注销", "这个机器不是你的，无法注销。")
            return
        self._confirm_registration_cancellation(row)

    def _registration_cancellation_lookup_failed(self, generation: int, message: str) -> None:
        if generation != self.registration_cancellation_generation:
            return
        self._finish_registration_cancellation_controls(clear_input=True)
        self.cancellation_button.flash_error()
        self._set_cancellation_state(f"账号设备查询失败：{message}", "error")
        information(self, "注销查询失败", message)

    def _finish_registration_cancellation_controls(self, *, clear_input: bool = False) -> None:
        self.cancellation_serial_input.setEnabled(True)
        self.cancellation_button.setText("注销")
        self.cancellation_button.setEnabled(True)
        if clear_input:
            self.cancellation_serial_input.clear()

    def _confirm_registration_cancellation(self, row: dict[str, Any]) -> None:
        aircraft_name = str(row.get("chanpmc") or row.get("chanpxh") or "未标注机型")
        serial = str(row.get("chanpxlh") or "未提供")
        uas_code = str(row.get("uasCode") or "未提供")
        confirmed = confirm_danger(
            self,
            "确认注销实名",
            "即将直接提交以下设备的实名注销：\n\n"
            f"机型：{aircraft_name}\n"
            f"序列号：{serial}\n"
            f"实名标识：{uas_code}\n"
            "注销原因：所有权变更（出售、转让或赠予等）\n\n"
            "确认后会立即提交到UOM，成功后无法在软件内撤回。",
        )
        if not confirmed:
            self._finish_registration_cancellation_controls()
            self.cancellation_button.flash_success()
            self._set_cancellation_state("已取消，本次没有提交注销。", "warning")
            self.append_log("info", "已取消本次实名注销。")
            return
        self.cancellation_button.setText("注销中")
        self._set_cancellation_state("正在向UOM官方提交实名注销…", "working")

        def completed(result: dict[str, str]) -> None:
            message = str(result.get("message") or "注销成功")
            self._finish_registration_cancellation_controls(clear_input=True)
            self._set_cancellation_state(f"注销成功：{serial}", "success")
            self.append_log("ok", f"实名注销成功：{serial}（转让）")
            information(self, "注销成功", f"{aircraft_name}\n{serial}\n\n{message}")

        def failed(message: str) -> None:
            self._finish_registration_cancellation_controls(clear_input=True)
            self.cancellation_button.flash_error()
            self._set_cancellation_state(f"注销失败：{message}", "error")
            self.append_log("warn", f"实名注销失败：{message}")
            information(self, "注销未完成", message)

        self.uom_web.cancel_registered_aircraft(row, completed, failed)

    def toggle_sidebar(self) -> None:
        if self.sidebar_width_animation.state() == QAbstractAnimation.Running:
            collapsed = not self._sidebar_animation_target
        else:
            collapsed = not self.sidebar_panel.isHidden()
        self._set_sidebar_collapsed(collapsed, announce=True, animate=True)

    def _set_sidebar_collapsed(self, collapsed: bool, *, announce: bool, animate: bool = False) -> None:
        self._sidebar_animation_target = collapsed
        if animate:
            self._animate_sidebar(collapsed, announce=announce)
            return
        self.sidebar_width_animation.stop()
        self._discard_sidebar_animation_overlay()
        self.sidebar_panel.setFixedWidth(self._active_sidebar_width())
        self.sidebar_panel.setVisible(not collapsed)
        self._apply_sidebar_state(collapsed, announce=announce)

    def _prepare_sidebar_animation_overlay(self, start_opacity: float) -> None:
        if self._sidebar_animation_overlay is not None:
            if self._sidebar_animation_effect is not None:
                self._sidebar_animation_effect.setOpacity(start_opacity)
            return

        if self.sidebar_panel.isVisible():
            snapshot = self.sidebar_panel.grab()
            if not snapshot.isNull():
                self._sidebar_snapshot = snapshot
        elif self._sidebar_snapshot.isNull():
            snapshot = self.sidebar_panel.grab()
            if not snapshot.isNull():
                self._sidebar_snapshot = snapshot

        overlay = QLabel(self.centralWidget(), objectName="SidebarAnimationOverlay")
        overlay.setFixedSize(self.sidebar_panel.size())
        overlay.move(self.sidebar_panel.mapTo(self.centralWidget(), QPoint(0, 0)))
        overlay.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        if not self._sidebar_snapshot.isNull():
            overlay.setPixmap(self._sidebar_snapshot)
        effect = QGraphicsOpacityEffect(overlay)
        effect.setOpacity(start_opacity)
        overlay.setGraphicsEffect(effect)
        overlay.show()
        overlay.raise_()
        self._sidebar_animation_overlay = overlay
        self._sidebar_animation_effect = effect

    def _discard_sidebar_animation_overlay(self) -> None:
        overlay = self._sidebar_animation_overlay
        if overlay is None:
            return
        overlay.hide()
        overlay.deleteLater()
        self._sidebar_animation_overlay = None
        self._sidebar_animation_effect = None

    def _animate_sidebar(self, collapsed: bool, *, announce: bool) -> None:
        self.sidebar_width_animation.stop()
        self._discard_sidebar_animation_overlay()
        if collapsed:
            self._prepare_sidebar_animation_overlay(1.0)
            self.sidebar_panel.hide()
            # Release the sidebar width immediately. The floating snapshot
            # fades over the expanding UOM page instead of delaying the layout.
            self.body_layout.setContentsMargins(0, 0, 0, 0)
            self.body_layout.setSpacing(0)
            start_opacity = 1.0
            end_opacity = 0.0
        else:
            self.body_layout.setContentsMargins(16, 16, 16, 16)
            self.body_layout.setSpacing(14)
            self.sidebar_panel.show()
            self._prepare_sidebar_animation_overlay(0.0)
            start_opacity = 0.0
            end_opacity = 1.0

        self._sidebar_animation_announce = announce
        self._update_sidebar_chrome(collapsed)
        self.sidebar_width_animation.setStartValue(start_opacity)
        self.sidebar_width_animation.setEndValue(end_opacity)
        self.sidebar_width_animation.setDuration(110)
        self.sidebar_width_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.sidebar_width_animation.start()

    def _sidebar_animation_frame(self, value: object) -> None:
        if self._sidebar_animation_effect is not None:
            self._sidebar_animation_effect.setOpacity(max(0.0, min(1.0, float(value))))

    def _sidebar_animation_finished(self) -> None:
        collapsed = self._sidebar_animation_target
        self.sidebar_panel.setFixedWidth(self._active_sidebar_width())
        self._discard_sidebar_animation_overlay()
        self.sidebar_panel.setVisible(not collapsed)
        self._apply_sidebar_state(collapsed, announce=getattr(self, "_sidebar_animation_announce", False))

    def _update_sidebar_chrome(self, collapsed: bool) -> None:
        expected_text = "展开" if collapsed else "收起"
        expected_tooltip = (
            "展开标签预览、自动化控制和打印机设置"
            if collapsed
            else "折叠左侧控制栏，让UOM网页占满内容区"
        )
        changed = (
            self.sidebar_toggle_button.text() != expected_text
            or bool(self.sidebar_toggle_button.property("collapsed")) != collapsed
            or bool(self.web_card.property("fullscreen")) != collapsed
        )
        self.sidebar_toggle_button.setText(expected_text)
        self.sidebar_toggle_button.setToolTip(expected_tooltip)
        self.sidebar_toggle_button.setProperty("collapsed", collapsed)
        self.web_card.setProperty("fullscreen", collapsed)
        if changed:
            for widget in (self.web_card, self.sidebar_toggle_button):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def _apply_sidebar_state(self, collapsed: bool, *, announce: bool) -> None:
        if collapsed:
            self.body_layout.setContentsMargins(0, 0, 0, 0)
            self.body_layout.setSpacing(0)
        else:
            self.body_layout.setContentsMargins(16, 16, 16, 16)
            self.body_layout.setSpacing(14)
        self._update_sidebar_chrome(collapsed)
        if self.settings.sidebar_collapsed != collapsed:
            self.settings.sidebar_collapsed = collapsed
            self.store.save(self.settings)
        if announce:
            message = "左栏已折叠，UOM网页已占满内容区，自动监听保持运行。" if collapsed else "左栏已展开，自动监听保持运行。"
            self.append_log("info", message)

    def _build_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = resource_path("assets/app-icon.png")
        self.tray_icon.setIcon(QIcon(str(icon_path)) if icon_path.exists() else self.windowIcon())
        self.tray_icon.setToolTip("UOM自动打印")
        tray_menu = QMenu(self)
        show_action = QAction("打开主界面", self)
        show_action.triggered.connect(self.restore_from_floating)
        self.float_action = QAction("显示悬浮窗", self)
        self.float_action.triggered.connect(self.toggle_floating)
        self.tray_monitor_action = QAction("开启监听", self)
        self.tray_monitor_action.triggered.connect(self.toggle_monitor)
        exit_action = QAction("强制退出程序", self)
        exit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(show_action)
        tray_menu.addAction(self.float_action)
        tray_menu.addSeparator()
        tray_menu.addAction(self.tray_monitor_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_from_floating()

    def _notify(self, title: str, message: str, error: bool = False) -> None:
        if not self.tray_icon.isVisible():
            return
        icon = QSystemTrayIcon.MessageIcon.Critical if error else QSystemTrayIcon.MessageIcon.Information
        self.tray_icon.showMessage(title, message, icon, 5000)

    def quit_application(self) -> None:
        self._commit_paper_selection()
        self.force_quit = True
        self.close()
        QApplication.quit()

    def _start_worker(self, worker: Worker) -> None:
        """Keep the Python worker alive until queued UI result signals are delivered."""
        self.active_workers.add(worker)

        def release() -> None:
            QTimer.singleShot(0, lambda: self.active_workers.discard(worker))

        worker.signals.finished.connect(release)
        self.thread_pool.start(worker)

    def append_log(self, level: str, message: str) -> None:
        icons = {"ok": "✓", "error": "✕", "step": "→", "info": "·", "warn": "!"}
        file_levels = {"ok": logging.INFO, "error": logging.ERROR, "step": logging.INFO, "info": logging.INFO, "warn": logging.WARNING}
        self.file_logger.log(file_levels.get(level, logging.INFO), "界面流程 | %s", message)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{timestamp}] {icons.get(level, '·')} {message}")
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
        self.status_detail.setText(message)
        self._update_floating_status(level, message)
        if level == "error":
            self._notify("UOM自动打印报错", message, error=True)

    def _refresh_status(self) -> None:
        self.mode_chip.setText("UOM官网")
        self.auto_print.setChecked(self.settings.auto_print)
        self.manual_auto.setChecked(self.settings.manual_import_auto_print)

    def _refresh_printers(self, announce: bool = False) -> None:
        try:
            printers = list_printers()
        except Exception as exc:
            printers = []
            self.file_logger.exception("刷新Windows打印机列表失败")
            if announce:
                self.append_log("error", f"刷新打印机失败：{exc}")
        if announce and printers:
            self.append_log("ok", f"已刷新打印机列表，共发现{len(printers)}台。")

    def open_printer_dialog(self) -> None:
        self.append_log("info", "已打开打印机选择。")
        dialog = PrinterDialog(self.settings.printer_name, self)
        dialog.printer_selected.connect(self._save_selected_printer)
        dialog.exec()

    def _save_selected_printer(self, printer: str) -> None:
        self.settings.printer_name = printer.strip()
        self.store.save(self.settings)
        self.printer_menu_button.flash_success()
        self.append_log("ok", f"当前打印机已保存：{self.settings.printer_name}")

    def _paper_size_changed(self, width_mm: float, height_mm: float) -> None:
        if not self._paper_selection_editing:
            self.paper_selector.set_current_paper(
                self.settings.paper_width_mm,
                self.settings.paper_height_mm,
                self.settings.layout_template_name,
                self.settings.layout_preset_file,
            )
            return
        template = self.paper_selector.current_template() or default_layout_template(width_mm, height_mm)
        self._show_header_message(
            "新的标签格式待确认",
            f"已选择“{template.name}”，点击“确认”或界面其他位置即可保存。",
            "working",
        )

    def _toggle_paper_selection_editing(self) -> None:
        if self._paper_selection_editing:
            self._commit_paper_selection(flash_button=True)
            return
        self._set_paper_selection_editing(True)

    def _commit_paper_selection(self, *, flash_button: bool = False) -> bool:
        if not self._paper_selection_editing:
            return False
        width_mm, height_mm = self.paper_selector.current_paper()
        self._apply_paper_selection(width_mm, height_mm)
        self._set_paper_selection_editing(False)
        if flash_button:
            self.paper_change_button.flash_success()
        return True

    def _set_paper_selection_editing(self, editing: bool) -> None:
        self._paper_selection_editing = bool(editing)
        self.paper_selector.setEnabled(self._paper_selection_editing)
        self.paper_change_button.setText("确认" if self._paper_selection_editing else "修改")
        self.paper_change_button.setProperty("mode", "confirm" if self._paper_selection_editing else "edit")
        self.paper_change_button.setToolTip(
            "选择需要的标签格式；点击确认、其他位置或其他功能都会自动保存"
            if self._paper_selection_editing
            else "点击修改后选择标签格式，点确认或界面其他位置即可保存"
        )
        self.paper_change_button.style().unpolish(self.paper_change_button)
        self.paper_change_button.style().polish(self.paper_change_button)
        if self._paper_selection_editing:
            self._show_header_message(
                "标签格式可以修改了",
                "选择预设后可点“确认”，也可直接点击界面其他位置自动保存。",
                "working",
            )

    def _apply_paper_selection(self, width_mm: float, height_mm: float) -> None:
        selected_template = self.paper_selector.current_template()
        template = selected_template or default_layout_template(width_mm, height_mm)
        selected_path = self.paper_selector.current_preset_path()
        selected_file = selected_path.name if selected_path is not None else ""
        if (
            abs(self.settings.paper_width_mm - width_mm) < 0.01
            and abs(self.settings.paper_height_mm - height_mm) < 0.01
            and self.settings.custom_layout_enabled
            and self.settings.layout_template_name == template.name
            and self.settings.layout_preset_file == selected_file
        ):
            return
        save_layout_template(template, layout_template_path())
        self.settings.paper_width_mm = width_mm
        self.settings.paper_height_mm = height_mm
        self.settings.layout_template_name = template.name
        self.settings.layout_preset_file = selected_file
        self.settings.custom_layout_enabled = True
        self.store.save(self.settings)
        self._schedule_layout_rerender(template)
        is_personal = self.paper_selector.current_preset_path() is not None
        preset_note = f"，已应用个人预设“{template.name}”" if is_personal else ""
        self.append_log("ok", f"标签纸已切换为 {width_mm:g} × {height_mm:g} mm{preset_note}，标签1和标签2共用这个尺寸。")
        self._show_header_message(
            "个人预设已选中" if is_personal else "纸张大小记住了",
            f"“{template.name}”已经确认保存，下次打开仍会使用。"
            if is_personal
            else "标签格式已经确认保存，下次打开仍会使用这个尺寸。",
            "success",
        )

    def open_layout_editor(self) -> None:
        self._commit_paper_selection()
        self.edit_layout_button.flash_success()
        if self.layout_editor_page is not None:
            self.main_stack.setCurrentWidget(self.layout_editor_page)
            return
        page = LayoutEditorPage(self.settings, self.store, self.main_stack)
        page.preview_template_changed.connect(self._schedule_layout_rerender)
        page.close_requested.connect(self._close_layout_editor)
        self.layout_editor_page = page
        self.main_stack.addWidget(page)
        self.main_stack.setCurrentWidget(page)

    def _close_layout_editor(self) -> None:
        page = self.layout_editor_page
        saved_template = load_layout_template(layout_template_path())
        self._schedule_layout_rerender(saved_template)
        self.main_stack.setCurrentWidget(self.main_page)
        self.paper_selector.refresh_presets(self.settings.layout_template_name, self.settings.layout_preset_file)
        self.paper_selector.set_current_paper(
            self.settings.paper_width_mm,
            self.settings.paper_height_mm,
            self.settings.layout_template_name,
            self.settings.layout_preset_file,
        )
        if page is not None:
            preset_saved = page.preset_saved
            preset_applied = page.preset_applied
            preset_name = page.saved_preset_name
            self.main_stack.removeWidget(page)
            page.deleteLater()
            if preset_saved:
                self._show_header_message(
                    "当前预设已更新" if preset_applied else "个人预设已保存",
                    (
                        f"“{preset_name}”的修改已经保存并继续生效。"
                        if preset_applied
                        else f"“{preset_name}”已加入纸张选择；当前仍使用“{self.settings.layout_template_name}”。"
                    ),
                    "success",
                )
        self.layout_editor_page = None

    def _schedule_layout_rerender(self, template) -> None:
        self._pending_layout_template = template
        self.layout_rerender_timer.start()

    def _flush_layout_rerender(self) -> None:
        template = self._pending_layout_template
        self._pending_layout_template = None
        if template is not None:
            self._rerender_current_labels(template)

    def _rerender_current_labels(self, template) -> None:
        if self.current_labels is None:
            return
        record = self.current_labels.record
        if not record.qr_payload:
            return
        try:
            qr_image = qr_image_from_payload(record.qr_payload)
            qr_label = render_qr_label(qr_image, record, self.settings.label_dpi, layout=template)
            info_label = render_info_label(qr_image, record, self.settings.label_dpi, layout=template)
            current = self.current_labels.qr_label
            updated = save_label_set_outputs(
                qr_label,
                info_label,
                record,
                current.source_pdf,
                None,
                current.source,
                persist_output=False,
            )
            self.show_labels(updated)
        except Exception as exc:
            self.file_logger.exception("切换标签模板后重新渲染失败")
            self.append_log("error", f"标签预览同步失败：{exc}")

    def open_settings(self) -> None:
        self._commit_paper_selection()
        self.append_log("info", "已打开设置。")
        dialog = SettingsDialog(self.settings, self.store, self)
        dialog.settings_saved.connect(self.apply_settings)
        dialog.exec()

    def show_about(self) -> None:
        self.append_log("info", "已打开关于软件。")
        about(
            self,
            "关于 UOM自动打印",
            "<h2>UOM自动打印</h2>"
            "<p>UOM实名登记实时读取、多尺寸安全排版与Windows自动打印。</p>"
            "<p><b>鸽鸽XD x Codex 开发</b></p>"
            f"<p>版本 v{__version__}</p>",
        )

    def apply_settings(self, settings: AppSettings) -> None:
        self._set_paper_selection_editing(False)
        was_monitoring = self.monitoring
        self.settings = settings
        self.qr_copies.blockSignals(True)
        self.info_copies.blockSignals(True)
        self.qr_copies.setValue(max(1, settings.qr_label_copies))
        self.info_copies.setValue(max(1, settings.info_label_copies))
        self.qr_copies.blockSignals(False)
        self.info_copies.blockSignals(False)
        self.copy_summary.setText(self._copy_summary())
        self.paper_selector.refresh_presets(settings.layout_template_name, settings.layout_preset_file)
        self.paper_selector.set_current_paper(
            settings.paper_width_mm,
            settings.paper_height_mm,
            settings.layout_template_name,
            settings.layout_preset_file,
        )
        self._refresh_status()
        self._refresh_printers()
        self._set_sidebar_collapsed(settings.sidebar_collapsed, announce=False)
        if was_monitoring:
            self.monitoring = True
            self.monitor_button.setText("停止监听")
            self.monitor_button.setProperty("active", True)
            self.monitor_button.style().unpolish(self.monitor_button)
            self.monitor_button.style().polish(self.monitor_button)
            self.status_chip.setText("正在监听")
            self._set_status_chip("success")
            self.append_log("ok", "设置已保存，自动监听保持运行。")
        else:
            self.append_log("ok", "设置已保存。")
        self.file_logger.info(
            "设置更新 | poll=%ss | printer=%s | auto_monitor=%s | auto_print=%s | output=%s",
            settings.poll_seconds,
            settings.printer_name or "未选择",
            settings.auto_monitor,
            settings.auto_print,
            settings.output_directory or "桌面默认目录",
        )

    def toggle_monitor(self) -> None:
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self) -> None:
        if self.monitoring:
            self.append_log("info", "自动监听已在运行。")
            return
        if self.wine_compat_mode:
            information(
                self,
                "离线界面测试",
                "Wine中已停用UOM网页组件以避免黑屏。请把安装包复制到真实Windows系统测试自动监听。",
            )
            self.append_log("warn", "离线界面测试模式无法开启UOM监听。")
            return
        self.uom_web.ensure_loaded()
        if not self.uom_web.is_logged_in:
            information(self, "请登录UOM", "请先在右侧UOM官网完成登录，然后再开启监听。")
            return
        if self.settings.uom_auto_open_registration:
            self.uom_web.open_registration_page()

        self.settings.auto_print = self.auto_print.isChecked()
        self.store.save(self.settings)
        self.monitoring = True
        self.monitor_button.setText("停止监听")
        self.monitor_button.setProperty("active", True)
        self.monitor_button.style().unpolish(self.monitor_button)
        self.monitor_button.style().polish(self.monitor_button)
        self.tray_monitor_action.setText("停止监听")
        self.status_chip.setText("正在监听")
        self._set_status_chip("success")
        self.append_log("ok", "已开始持续监听UOM实名登记，只有点击“停止监听”才会停止。")
        self._show_header_message("我盯着呢，你放心去实名", "只要你不点停止，我就一直守着新登记。", "success")
        self._notify("UOM自动打印", "当前正在持续监听UOM实名登记。")
        self.poll_source()
        if self.settings.floating_on_monitor:
            QTimer.singleShot(500, self.show_floating)

    def stop_monitor(self) -> None:
        if not self.monitoring:
            return
        self.monitoring = False
        self.monitor_timer.stop()
        self.monitor_button.setText("开启监听")
        self.monitor_button.setProperty("active", False)
        self.monitor_button.style().unpolish(self.monitor_button)
        self.monitor_button.style().polish(self.monitor_button)
        self.tray_monitor_action.setText("开启监听")
        self.status_chip.setText("未监听")
        self._set_status_chip("idle")
        self.append_log("info", "已停止自动监听。")
        self._show_header_message("好，先歇会儿", "监听停了，软件还在，想开工再叫我。", "idle")

    def _show_web_source(self, source: str) -> None:
        normalized = "dji" if source == "dji" and self.dji_view is not None else "uom"
        self._active_web_source = normalized
        if self.web_content_stack is not None:
            # The right-hand official workspace always stays on UOM. DJI's
            # unavoidable login/slider UI is shown in a narrow overlay on the
            # left so the registration page never disappears behind it.
            if self.uom_view is not None:
                self.web_content_stack.setCurrentWidget(self.uom_view)
        if normalized == "dji":
            if self._dji_sidebar_restore_collapsed is None:
                self._dji_sidebar_restore_collapsed = self.sidebar_panel.isHidden()
            if self.sidebar_panel.isHidden():
                self._set_sidebar_collapsed(False, announce=False)
            if self.dji_sidebar_overlay is not None:
                self.dji_sidebar_overlay.setGeometry(self.sidebar_panel.rect())
                self.dji_sidebar_overlay.show()
                self.dji_sidebar_overlay.raise_()
            self.dji_verification_bar.show()
        else:
            if self.dji_sidebar_overlay is not None:
                self.dji_sidebar_overlay.hide()
            if self._dji_sidebar_restore_collapsed:
                self._set_sidebar_collapsed(True, announce=False)
            self._dji_sidebar_restore_collapsed = None
        self.web_title_label.setText("UOM 官方平台")

    def _dji_sidebar_load_started(self) -> None:
        if self.dji_sidebar_progress is not None:
            self.dji_sidebar_progress.setValue(2)
            self.dji_sidebar_progress.show()

    def _dji_sidebar_load_progress(self, value: int) -> None:
        if self.dji_sidebar_progress is not None:
            self.dji_sidebar_progress.setValue(max(0, min(100, int(value))))

    def _dji_sidebar_load_finished(self, _ok: bool) -> None:
        if self.dji_sidebar_progress is not None:
            self.dji_sidebar_progress.setValue(100)
            QTimer.singleShot(180, self.dji_sidebar_progress.hide)

    def _set_dji_inline_verification(
        self,
        text: str,
        state: str,
        *,
        query_active: bool = True,
    ) -> None:
        self._dji_inline_verification_active = True
        self.dji_verification_status.setText(str(text or "正在等待大疆官方验证…"))
        self.dji_verification_status.setProperty("state", state)
        self.dji_verification_status.style().unpolish(self.dji_verification_status)
        self.dji_verification_status.style().polish(self.dji_verification_status)
        self.dji_verification_cancel_button.setText("取消识别" if query_active else "关闭提示")
        self.dji_verification_cancel_button.setToolTip(
            "取消本次精准机型查询" if query_active else "关闭这条提示"
        )
        if self._active_web_source == "dji":
            self.dji_verification_bar.show()

    def _hide_dji_inline_verification(self) -> None:
        self._dji_inline_verification_active = False
        self.dji_verification_bar.hide()
        if self.dji_sidebar_overlay is not None:
            self.dji_sidebar_overlay.hide()
        if self._dji_sidebar_restore_collapsed:
            self._set_sidebar_collapsed(True, announce=False)
        self._dji_sidebar_restore_collapsed = None
        self._active_web_source = "uom"

    def _cancel_dji_inline_verification(self) -> None:
        if self.dji_web is not None and self.dji_web.query_active:
            self.dji_web.cancel_query()
            self._dji_query_failed("已取消本次大疆官方验证。")
        self._hide_dji_inline_verification()

    def open_dji_login(self) -> None:
        if self.dji_web is None:
            information(self, "DJI官网登录", "离线界面测试不加载DJI官网，请在Windows正式版中使用这个入口。")
            return
        self._show_web_source("dji")
        self.dji_web.ensure_loaded()
        if self.dji_web.query_active:
            self._dji_inline_verification_active = True
            self.dji_verification_bar.show()
            self._set_registration_state("大疆官方验证仍在进行，已在左侧打开官方验证区。", "working")
        elif self.dji_web.is_logged_in:
            self._set_registration_state("已在左侧打开DJI官网；填写序列号和照片后点击识别并认证。", "success")
        else:
            self._set_registration_state("请在左侧完成DJI官网登录；登录状态会自动同步。", "warning")

    def _dji_login_state_changed(self, logged_in: bool, label: str) -> None:
        del label
        self.dji_login_status.setText("大疆查询：已登录" if logged_in else "大疆查询：未登录")
        self.dji_login_status.setProperty("loggedIn", bool(logged_in))
        self.dji_login_status.style().unpolish(self.dji_login_status)
        self.dji_login_status.style().polish(self.dji_login_status)
        self.dji_login_status.setToolTip(
            "DJI官网会话正常"
            if logged_in
            else "DJI官网尚未登录"
        )
        self._refresh_official_web_toggle_visibility()

    def _refresh_official_web_toggle_visibility(self) -> None:
        if self.wine_compat_mode:
            self.official_web_toggle_button.hide()
            return
        dji_ready = bool(self.dji_web is not None and self.dji_web.is_logged_in)
        should_show = self._official_web_collapsed or (self.uom_web.is_logged_in and dji_ready)
        self.official_web_toggle_button.setVisible(should_show)

    def toggle_official_web(self) -> None:
        self._set_official_web_collapsed(not self._official_web_collapsed, announce=True)

    def _set_official_web_collapsed(self, collapsed: bool, *, announce: bool) -> None:
        if self.wine_compat_mode:
            return
        normalized = bool(collapsed)
        state_changed = normalized != self._official_web_collapsed
        if normalized and state_changed:
            self._official_web_expanded_geometry = QRect(self.geometry())
            self._official_web_expanded_maximized = self.isMaximized()
            self._official_web_expanded_fullscreen = self.isFullScreen()
        if normalized and self.sidebar_panel.isHidden():
            self._set_sidebar_collapsed(False, announce=False)
        self._official_web_collapsed = normalized
        try:
            self.uom_web.page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
        except (AttributeError, RuntimeError):
            pass
        self.web_card.setVisible(not normalized)
        self.header_bubble.setVisible(not normalized)
        self.compact_header_bubble_container.setVisible(normalized)
        if state_changed:
            self._apply_official_web_window_mode(normalized)
        self.official_web_toggle_button.setText("展开官网" if normalized else "收起官网")
        self.official_web_toggle_button.setToolTip(
            "恢复显示原来的官方网页，不会刷新或重新登录"
            if normalized
            else "隐藏右侧官方网页；登录态和自动处理继续保留"
        )
        self._refresh_official_web_toggle_visibility()
        if announce:
            if normalized:
                self._show_header_message(
                    "官网先收起来了",
                    "页面和登录状态都还在，查询、监听和实名流程不会中断。",
                    "success",
                )
                self.append_log("info", "右侧官方网页已收起，网页登录态和后台流程保持运行。")
            else:
                self.append_log("info", "右侧官方网页已恢复显示，没有重新加载页面。")

    def _apply_official_web_window_mode(self, collapsed: bool) -> None:
        if collapsed:
            self.showNormal()
            available = self.screen().availableGeometry() if self.screen() is not None else QRect(0, 0, 1920, 1080)
            compact_width = self.COMPACT_WINDOW_WIDTH
            compact_height = max(760, min(self.height(), available.height()))
            compact_x = max(available.left(), min(self.x(), available.right() - compact_width + 1))
            compact_y = max(available.top(), min(self.y(), available.bottom() - compact_height + 1))
            self.sidebar_panel.setFixedWidth(self.COMPACT_SIDEBAR_WIDTH)
            self.setMinimumSize(compact_width, 760)
            self.setMaximumWidth(compact_width)
            self.setGeometry(compact_x, compact_y, compact_width, compact_height)
            return

        self.sidebar_panel.setFixedWidth(self.SIDEBAR_WIDTH)
        self.setMaximumWidth(16777215)
        self.setMinimumSize(1180, 760)
        previous_geometry = self._official_web_expanded_geometry
        if previous_geometry is not None:
            self.setGeometry(previous_geometry)
        if self._official_web_expanded_fullscreen:
            self.showFullScreen()
        elif self._official_web_expanded_maximized:
            self.showMaximized()

    def _active_sidebar_width(self) -> int:
        return self.COMPACT_SIDEBAR_WIDTH if self._official_web_collapsed else self.SIDEBAR_WIDTH

    def _refresh_active_web(self) -> None:
        if self._active_web_source == "dji" and self.dji_web is not None:
            self.dji_web.reload()
            self.refresh_uom_button.flash_success()
            self._set_registration_state("正在刷新大疆官方查询页…", "working")
            return
        self.refresh_uom_page()

    def go_uom_home(self) -> None:
        if self.wine_compat_mode:
            self.append_log("info", "离线界面测试模式未加载UOM网页。")
            return
        self._show_web_source("uom")
        self.append_log("info", "正在打开UOM首页，自动监听保持运行。")
        self.uom_web.go_home()

    def open_uom_registration(self) -> None:
        if self.wine_compat_mode:
            self.append_log("info", "实名登记网页请在真实Windows系统中测试。")
            return
        self.append_log("info", "正在打开UOM实名登记页。")
        self.uom_web.open_registration_page()

    def refresh_uom_page(self) -> None:
        if self.wine_compat_mode:
            self.append_log("ok", "离线界面测试正常，UOM网页组件未启动。")
            return
        if self.uom_refreshing:
            self.append_log("info", "UOM页面正在刷新，请稍候。")
            return
        self.uom_refreshing = True
        self.uom_refresh_generation += 1
        generation = self.uom_refresh_generation
        self.refresh_uom_button.setEnabled(False)
        self.refresh_uom_button.setText("刷新中…")
        self.append_log("step", "正在刷新UOM页面，自动监听不会停止。")
        self._show_header_message("网页洗把脸，马上回来", "放心，刷新网页不会把自动监听弄丢。", "working")
        self.uom_web.reload()
        QTimer.singleShot(20000, lambda: self._uom_refresh_timed_out(generation))

    def _uom_refresh_timed_out(self, generation: int) -> None:
        if generation != self.uom_refresh_generation or not self.uom_refreshing:
            return
        self.uom_refresh_generation += 1
        self.uom_refreshing = False
        self.refresh_uom_button.setEnabled(True)
        self.refresh_uom_button.setText("重试")
        self.refresh_uom_button.flash_error()
        self.uom_state.setText("UOM：连接异常")
        self.uom_state.setProperty("state", "warning")
        self.uom_state.style().unpolish(self.uom_state)
        self.uom_state.style().polish(self.uom_state)
        self.append_log("warn", "UOM刷新等待超时，刷新按钮已恢复，可以直接重试。")
        self._show_header_message("UOM刷新超时", "按钮已经恢复，登录和本次资料都没有清空。", "warning")

    def _web_load_started(self) -> None:
        self.web_load_generation += 1
        self.web_progress.setValue(2)
        self.web_progress.show()

    def _web_load_progress(self, progress: int) -> None:
        self.web_progress.setValue(max(2, min(100, progress)))
        self.web_progress.show()

    def _web_load_finished(self, _ok: bool) -> None:
        self.web_progress.setValue(100)
        generation = self.web_load_generation

        def hide_if_current() -> None:
            if generation == self.web_load_generation:
                self.web_progress.hide()

        QTimer.singleShot(360, hide_if_current)

    def _uom_page_ready(self, ok: bool) -> None:
        self._uom_page_healthy = bool(ok)
        was_manual_refresh = self.uom_refreshing
        if was_manual_refresh:
            self.uom_refresh_generation += 1
        self.uom_refreshing = False
        self.refresh_uom_button.setEnabled(True)
        self.refresh_uom_button.setText("刷新" if ok else "重试")
        if ok:
            self.uom_state.setText("UOM：已登录" if self.uom_web.is_logged_in else "UOM：确认中")
            self.uom_state.setProperty("state", "success" if self.uom_web.is_logged_in else "working")
            self.uom_state.style().unpolish(self.uom_state)
            self.uom_state.style().polish(self.uom_state)
            if was_manual_refresh:
                self.append_log("ok", "UOM页面已刷新，自动监听保持运行。")
                self.refresh_uom_button.flash_success()
            if self.dji_web is not None and not self._dji_lazy_load_scheduled:
                self._dji_lazy_load_scheduled = True
                QTimer.singleShot(1800, self._load_dji_after_uom)
        else:
            self.uom_state.setText("UOM：连接异常")
            self.uom_state.setProperty("state", "warning")
            self.uom_state.style().unpolish(self.uom_state)
            self.uom_state.style().polish(self.uom_state)
            self.append_log("warn", "UOM页面加载失败，正在有限自动重试；不会清除登录态和本次资料。")
            self.refresh_uom_button.flash_error()
            self._show_header_message(
                "UOM这会儿有点卡",
                "软件正在自动重试，当前登录态和实名资料不会被清空。",
                "warning",
            )
            active_stage = self._registration_stage
            if active_stage not in {"idle", "dji"} and self._registration_failure_kind != "network":
                if active_stage == "submitting":
                    failure = UomWebFailure(
                        "提交时UOM页面连接中断，需要先核对登记结果。",
                        kind="unknown",
                        outcome_unknown=True,
                    )
                    self._pause_registration("submit_unknown", failure, notify=False)
                else:
                    self._pause_registration(
                        active_stage,
                        UomWebFailure("UOM页面连接中断，请恢复后再试。", kind="network"),
                        notify=False,
                    )

    def _load_dji_after_uom(self) -> None:
        self._dji_lazy_load_scheduled = False
        if self.dji_web is None or not self._uom_page_healthy:
            return
        self.dji_web.ensure_loaded()

    def _schedule_next_poll(self) -> None:
        if not self.monitoring:
            return
        if self.uom_poll_failure_streak:
            delay = min(60, 5 * (2 ** min(self.uom_poll_failure_streak - 1, 3))) + random.randint(0, 3)
            minimum = maximum = delay
        else:
            minimum = DEFAULT_POLL_MIN_SECONDS
            maximum = DEFAULT_POLL_MAX_SECONDS
            delay = random.randint(minimum, maximum)
        self.file_logger.debug("下次UOM检查已安排 | delay=%ss | range=%s-%ss", delay, minimum, maximum)
        self.monitor_timer.start(delay * 1000)

    def _finish_poll_cycle(self) -> None:
        self.poll_running = False
        requested_latest = not self.latest_button.isEnabled()
        self._set_sidebar_action_enabled(self.latest_button, True)
        self.latest_button.setText("读取最新并打印")
        if requested_latest:
            self.latest_button.flash_success()
        self._schedule_next_poll()

    def poll_source(self) -> None:
        if self.poll_running:
            return
        self.settings.auto_print = self.auto_print.isChecked()
        self._poll_uom()

    def _poll_uom(self, force_latest: bool = False, force_print: bool = False) -> bool:
        if self.poll_running:
            if force_latest:
                self.append_log("warn", "已有UOM读取任务在运行，请稍候再试。")
            return False
        if not self.uom_web.is_page_ready or not self.uom_web.is_logged_in:
            if force_latest:
                self.append_log("warn", "UOM官网尚未连接完成，请恢复登录后再读取。")
            elif self.monitoring:
                self._schedule_next_poll()
            return False
        self.poll_running = True
        self.uom_web.fetch_registered_aircraft(
            lambda rows: self._uom_list_result(rows, force_latest, force_print),
            self._uom_poll_failed,
            page_size=100,
        )
        return True

    def _uom_poll_failed(self, message: str) -> None:
        requested_latest = not self.latest_button.isEnabled()
        self.uom_poll_failure_streak += 1
        if self._uom_failure_kind(message) in {"network", "unknown", "session"}:
            self.append_log("warn", f"UOM暂时无法读取，已延长重试间隔：{message}")
        else:
            self.report_exception("UOM登记检查失败", message)
        self._finish_poll_cycle()
        if requested_latest:
            self.latest_button.flash_error()

    @staticmethod
    def _uom_row_key(row: dict[str, Any]) -> str:
        direct = str(row.get("id") or row.get("uasCode") or "").strip()
        if direct:
            return direct
        compact = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(compact.encode("utf-8")).hexdigest()

    def _uom_list_result(self, rows: list[dict[str, Any]], force_latest: bool, force_print: bool) -> None:
        self.uom_poll_failure_streak = 0
        if force_latest:
            if not rows:
                self.append_log("warn", "实名登记列表中暂时没有可读取记录。")
                self._finish_poll_cycle()
                return
            row = rows[0]
            key = self._uom_row_key(row)
            self.uom_queue = [(row, key, force_print)]
            self.uom_labels = []
            self.append_log("step", "正在读取列表中的最新实名登记记录。")
            self._process_next_uom_row()
            return

        seen = self.history.uom_seen_ids(self.uom_web.account_key)
        if "__baseline__" not in seen:
            for row in rows:
                self.history.record_uom(self.uom_web.account_key, self._uom_row_key(row), "baseline")
            self.history.record_uom(self.uom_web.account_key, "__baseline__", "baseline")
            self.append_log("ok", f"已建立UOM登记基线（当前{len(rows)}条），不会打印历史设备。")
            self._finish_poll_cycle()
            return

        new_rows = [(row, self._uom_row_key(row), self.settings.auto_print) for row in rows if self._uom_row_key(row) not in seen]
        self.uom_queue = list(reversed(new_rows))
        self.uom_labels = []
        if not self.uom_queue:
            self._finish_poll_cycle()
            return
        self.append_log("step", f"发现{len(self.uom_queue)}条新增实名登记，开始生成标签。")
        self._process_next_uom_row()

    def _process_next_uom_row(self) -> None:
        if not self.uom_queue:
            if self.uom_labels:
                self.append_log("ok", f"本次已完成{len(self.uom_labels)}条新增登记。")
            self._finish_poll_cycle()
            return
        row, row_key, should_print = self.uom_queue.pop(0)
        worker = Worker(self._uom_row_task, row, should_print)

        def processed(result: dict) -> None:
            self.history.record_uom(self.uom_web.account_key, row_key, "processed", result.get("print_error", ""))
            labels = result.get("labels")
            if labels:
                self.uom_labels.append(labels)
                self.show_labels(labels)
            if result.get("print_error"):
                self.append_log("error", f"标签已生成，但自动打印失败：{result['print_error']}")
            elif result.get("printed"):
                self.append_log("ok", f"两套标签已显示，{self._copy_summary()}。")
                self._notify("UOM标签已打印", self._copy_summary())
            self._process_next_uom_row()

        def failed(message: str, trace: str) -> None:
            self.history.record_uom(self.uom_web.account_key, row_key, "error", message)
            self.report_exception("UOM登记处理失败", message, trace)
            self._process_next_uom_row()

        worker.signals.result.connect(processed)
        worker.signals.error.connect(failed)
        self._start_worker(worker)

    def _uom_row_task(self, row: dict[str, Any], should_print: bool) -> dict:
        pipeline = self.pipeline()
        labels = pipeline.process_uom_row(row)
        print_error = ""
        printed = False
        if should_print:
            try:
                pipeline.submit_print(labels)
                printed = True
            except Exception as exc:
                print_error = str(exc)
                self.file_logger.exception("UOM标签已生成，但自动打印失败")
        return {"labels": labels, "print_error": print_error, "printed": printed}

    def read_latest_and_print(self) -> None:
        if not self.uom_web.is_logged_in:
            information(self, "请登录UOM", "请先在右侧UOM官网完成登录。")
            self.append_log("warn", "读取最新登记前需要先登录UOM。")
            return
        self._set_sidebar_action_enabled(self.latest_button, False)
        self.latest_button.setText("读取中…")
        self.append_log("step", "正在读取最新UOM登记并准备打印。")
        if not self._poll_uom(force_latest=True, force_print=True):
            self._set_sidebar_action_enabled(self.latest_button, True)
            self.latest_button.setText("读取最新并打印")

    def _uom_login_state_changed(self, logged_in: bool, label: str) -> None:
        del label
        self.uom_state.setText("UOM：已登录" if logged_in else "UOM：未登录")
        self.uom_state.setProperty("state", "success" if logged_in else "idle")
        self.uom_state.style().unpolish(self.uom_state)
        self.uom_state.style().polish(self.uom_state)
        if not logged_in:
            self._reset_lookup_ownership()
            active_stage = self._registration_stage
            if active_stage == "submitting":
                self._pause_registration(
                    "submit_unknown",
                    UomWebFailure(
                        "提交期间UOM登录会话中断，需要恢复登录后核对登记结果。",
                        kind="unknown",
                        outcome_unknown=True,
                    ),
                    notify=False,
                )
            elif active_stage not in {"idle", "dji", "submit_unknown", "ready_submit"}:
                self._registration_face_request_generation += 1
                self.registration_face_timer.stop()
                self._registration_face_polling = False
                self._registration_face_poll_inflight = False
                self._registration_owner = None
                self._registration_face_verified = False
                self._registration_uom_model = None
                self._registration_front_quote = ""
                self._registration_serial_quote = ""
                self._registration_pending_form = None
                self.registration_model_chip.setText("DJI已确认")
                self._pause_registration(
                    "face",
                    UomWebFailure("UOM登录会话已失效，请重新登录后再认证。", kind="session"),
                    notify=False,
                )
        elif (
            self._registration_dji_result is not None
            and self._registration_owner is None
            and all(self._registration_photo_paths.values())
            and self._registration_stage not in {"submit_unknown", "ready_submit", "submitting"}
        ):
            # Login only resumes the official face gate.  UOM model lookup and
            # all registration business data remain blocked until face code 4.
            QTimer.singleShot(350, self.prepare_uom_registration)
        elif logged_in and self._registration_stage == "submit_unknown":
            QTimer.singleShot(700, self._verify_registration_after_unknown_submit)
        if logged_in and self.sidebar_pages.currentIndex() == 2:
            QTimer.singleShot(350, self._maybe_start_first_model_catalog_update)
        if not logged_in and self.monitoring:
            self.append_log("warn", "UOM页面暂时未识别到登录状态，自动监听仍保持开启并会继续重试。")
        elif logged_in and self.monitoring:
            self.append_log("ok", "UOM登录状态已恢复，自动监听正常运行。")
        self._refresh_registration_action_button()
        self._refresh_official_web_toggle_visibility()

    def _set_status_chip(self, state: str) -> None:
        self.status_chip.setProperty("state", state)
        self.status_chip.style().unpolish(self.status_chip)
        self.status_chip.style().polish(self.status_chip)

    def _update_floating_status(self, level: str, message: str) -> None:
        mappings = (
            ("开始持续监听", "监听中", "等待UOM新增实名登记", "success"),
            ("已建立UOM登记基线", "监听中", "基线已建立，等待新增登记", "success"),
            ("发现", "发现新登记", message, "working"),
            ("读取PDF", "正在读取", message, "working"),
            ("读取最新UOM", "正在读取", "正在拉取UOM最新登记", "working"),
            ("正在读取列表", "正在读取", message, "working"),
            ("已提取并解码", "信息已识别", message, "working"),
            ("实名信息识别成功", "正在排版", "登记信息完整，正在生成标签", "working"),
            ("高容错二维码", "正在生成", "二维码已生成，正在套用标签模板", "working"),
            ("已生成", "标签已生成", "标签预览已按当前纸张模板更新", "success"),
            ("提交Windows", "正在打印", message, "working"),
            ("正在提交到打印机", "正在打印", message, "working"),
            ("打印任务已提交", "打印完成", "任务已进入Windows打印队列", "success"),
            ("本次已完成", "处理完成", message, "success"),
            ("已停止自动监听", "监听已停止", "软件仍在后台运行", "idle"),
        )
        for keyword, title, detail, state in mappings:
            if keyword in message:
                self.floating_window.set_status(title, detail, state)
                return
        if level == "error":
            self.floating_window.set_status("处理失败", message, "error")
        elif level == "warn":
            self.floating_window.set_status("需要注意", message, "warning")

    def show_floating(self) -> None:
        self._commit_paper_selection()
        self.append_log("info", "悬浮状态窗已显示。")
        if self.monitoring:
            self.floating_window.set_status("监听中", "等新登记，也可以拖个实名码给我", "success")
        else:
            self.floating_window.set_status("待命", "拖个实名码给我", "idle")
        self.floating_window.show_near_corner(self._saved_floating_position())
        self._sync_floating_controls()

    def hide_floating(self) -> None:
        self.floating_window.hide()
        self._sync_floating_controls()

    def toggle_floating(self) -> None:
        if self.floating_window.isVisible():
            self.hide_floating()
        else:
            self.show_floating()

    def _sync_floating_controls(self) -> None:
        visible = self.floating_window.isVisible()
        if hasattr(self, "float_action"):
            self.float_action.setText("关闭悬浮窗" if visible else "显示悬浮窗")
        if hasattr(self, "floating_button"):
            self.floating_button.setText("关闭悬浮窗" if visible else "悬浮窗")

    def _saved_floating_position(self) -> tuple[int, int] | None:
        if self.settings.floating_x is None or self.settings.floating_y is None:
            return None
        return int(self.settings.floating_x), int(self.settings.floating_y)

    def _save_floating_position(self, x: int, y: int) -> None:
        self.settings.floating_x = int(x)
        self.settings.floating_y = int(y)
        self.store.save(self.settings)

    def restore_from_floating(self) -> None:
        self.floating_window.hide()
        self._sync_floating_controls()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _floating_file_dropped(self, filename: str) -> None:
        path = Path(filename)
        if not self.import_button.isEnabled():
            self.append_log("warn", "上一个导入任务还在处理，请稍等。")
            self.floating_window.set_status("我正忙着", "上一个码还没处理完", "warning")
            return
        self.append_log("step", f"悬浮窗收到文件：{path.name}")
        self.process_manual(path)

    def choose_import_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择UOM实名码",
            "",
            "UOM实名码 (*.pdf *.jpg *.jpeg *.png *.bmp *.webp)",
        )
        if filename:
            self.process_manual(Path(filename))
        else:
            self.append_log("info", "已取消手动导入。")

    def choose_pdf(self) -> None:
        """Compatibility alias retained for integrations using the old slot."""
        self.choose_import_file()

    def process_manual(self, path: Path) -> None:
        should_print = self.manual_auto.isChecked()
        self.settings.manual_import_auto_print = should_print
        self.append_log("step", f"手动导入：{path.name}")
        is_pdf = path.suffix.lower() == ".pdf"
        title = "PDF收到，正在重建标准二维码" if is_pdf else "图片收到，正在重建二维码"
        detail = (
            "只提取里面的UOM链接，再画一枚比例标准、清晰的新码。"
            if is_pdf
            else "我只取里面的UOM链接，再给你画一枚清晰的新码。"
        )
        self._show_header_message(title, detail, "working")
        self._set_sidebar_action_enabled(self.import_button, False)
        self.import_button.setText("处理中…")
        worker = Worker(self._manual_task, path, should_print)
        worker.signals.result.connect(self._manual_result)
        worker.signals.error.connect(self._manual_failed)
        worker.signals.finished.connect(self._manual_finished)
        self._start_worker(worker)

    def _manual_task(self, path: Path, should_print: bool) -> dict:
        pipeline = self.pipeline()
        result = pipeline.process_import(path, source="manual")
        print_error = ""
        printed = False
        if should_print:
            try:
                pipeline.submit_print(result)
                printed = True
            except Exception as exc:
                print_error = str(exc)
                self.file_logger.exception("手动导入标签已生成，但自动打印失败")
        return {"labels": result, "print_error": print_error, "printed": printed}

    def _manual_result(self, result: dict) -> None:
        self.show_labels(result["labels"])
        self.import_button.flash_success()
        if result.get("print_error"):
            self.append_log("error", f"标签已生成，但自动打印失败：{result['print_error']}")
        elif result.get("printed"):
            self.append_log("ok", f"导入的两套标签已显示，{self._copy_summary()}。")
            self.floating_window.set_status("打印完成", "任务已进入打印队列", "success")
            self._notify("UOM标签已打印", self._copy_summary())
        else:
            self.append_log("ok", "导入的两套标签已生成并显示。")
            self.floating_window.set_status("处理完成", "标签预览已经更新", "success")

    def _manual_failed(self, message: str, trace: str) -> None:
        self.import_button.flash_error()
        self.report_exception("手动导入处理失败", message, trace)
        critical(self, "实名码识别失败", message)

    def _manual_finished(self) -> None:
        self._set_sidebar_action_enabled(self.import_button, True)
        self.import_button.setText("导入实名码")

    def _show_preview_label(
        self,
        label: ProcessedLabel,
        preview: AspectRatioPreview,
        status: QLabel,
        display_name: str,
    ) -> bool:
        pixmap = QPixmap()
        loaded_path: Path | None = None
        for candidate in (label.print_png, label.preview_png):
            candidate_pixmap = QPixmap(str(candidate))
            if not candidate_pixmap.isNull():
                pixmap = candidate_pixmap
                loaded_path = candidate
                break
        if pixmap.isNull():
            preview.clear_source()
            preview.setText("标签已生成，但预览图加载失败\n请打开标签文件查看")
            self._set_preview_state(preview, "error")
            status.setText("预览失败")
            self.file_logger.error(
                "%s预览图加载失败 | print=%s | preview=%s",
                display_name,
                label.print_png,
                label.preview_png,
            )
            self.append_log("error", f"{display_name}已生成，但界面预览加载失败。")
            return False
        else:
            preview.set_source_pixmap(pixmap)
            self._set_preview_state(preview, "ready")
            status.setText("已生成")
            self.file_logger.info(
                "%s已显示 | loaded=%s | print_png=%s | print_pdf=%s",
                display_name,
                loaded_path,
                label.print_png,
                label.print_pdf,
            )
            return True

    def show_labels(self, labels: ProcessedLabelSet) -> None:
        self.current_labels = labels
        self.current_label = labels.qr_label
        qr_ready = self._show_preview_label(
            labels.qr_label,
            self.qr_preview,
            self.qr_result_status,
            "实名双码标签",
        )
        info_ready = self._show_preview_label(
            labels.info_label,
            self.info_preview,
            self.info_result_status,
            "设备信息标签",
        )
        self._set_sidebar_action_enabled(self.print_button, True)
        if qr_ready and info_ready:
            self._show_header_message(
                "两套码都排好了",
                f"预览已更新，{self._copy_summary()}。",
                "success",
            )
            self.append_log("ok", "两套标签预览已更新，可立即打印。")

    def show_label(self, label: ProcessedLabel | ProcessedLabelSet) -> None:
        """Compatibility entry point; current processing always supplies a label set."""
        if isinstance(label, ProcessedLabelSet):
            self.show_labels(label)
            return
        self.current_label = label
        self.current_labels = None
        self._show_preview_label(label, self.qr_preview, self.qr_result_status, "标签")
        self._set_sidebar_action_enabled(self.print_button, False)

    @staticmethod
    def _set_preview_state(preview: AspectRatioPreview, state: str) -> None:
        preview.setProperty("state", state)
        preview.style().unpolish(preview)
        preview.style().polish(preview)

    def print_current(self) -> None:
        if not self.current_labels:
            self.append_log("warn", "当前没有完整的两套标签可打印。")
            return
        if not self.settings.printer_name:
            self.append_log("warn", "请先选择Windows打印机。")
            return
        self._set_sidebar_action_enabled(self.print_button, False)
        self.print_button.setText("打印中…")
        self.append_log("step", f"正在提交到打印机：{self.settings.printer_name}")
        self._show_header_message("打印机，起来干活了", "标签正在往Windows打印队列里冲。", "working")
        worker = Worker(self.pipeline().submit_print, self.current_labels)
        worker.signals.result.connect(self._print_succeeded)
        worker.signals.error.connect(self._print_failed)
        worker.signals.finished.connect(self._print_finished)
        self._start_worker(worker)

    def _print_succeeded(self, _result: object) -> None:
        self.append_log("ok", f"打印任务已提交到Windows打印队列：{self._copy_summary()}。")
        self.print_button.flash_success()
        joke = random.choice(
            (
                "码已经送进打印机啦，这次机器没摸鱼。",
                "打印任务发车成功，下一站：标签纸。",
                "好了，码要从720W肚子里蹦出来了。",
                "这波丝滑，打印机连反驳的机会都没有。",
            )
        )
        self._show_header_message("打印成功，收工一小步", joke, "success", 5200)
        self._notify("UOM标签已提交", self._copy_summary())

    def _print_failed(self, message: str, trace: str) -> None:
        self.print_button.flash_error()
        self.report_exception("立即打印失败", message, trace)

    def _print_finished(self) -> None:
        self._set_sidebar_action_enabled(self.print_button, self.current_labels is not None)
        self.print_button.setText("立即打印")

    def report_exception(self, context: str, message: str, trace: str = "") -> None:
        self.append_log("error", f"{context}：{message}")
        self._show_header_message("坏了，它开始闹脾气了", f"{context}：{message}", "error", 6500)
        if trace:
            self.file_logger.error("%s | %s\n%s", context, message, trace)

    @staticmethod
    def _open_folder(target: Path) -> None:
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])

    def open_logs(self) -> None:
        self.append_log("info", "已打开运行日志文件夹。")
        self._open_folder(self.log_path.parent if self.log_path else log_dir())

    def open_output(self) -> None:
        self.append_log("info", "已打开标签文件夹。")
        target = output_dir(self.settings.output_directory)
        self._open_folder(target)

    @staticmethod
    def _drag_contains_supported_file(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
        supported = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        return any(Path(url.toLocalFile()).suffix.lower() in supported for url in event.mimeData().urls())

    def _drag_position_over_lookup_card(self, event: QDragEnterEvent | QDragMoveEvent) -> bool:
        if self.sidebar_pages.currentIndex() != 1 or not self.lookup_card.isVisible():
            return False
        main_position = event.position().toPoint()
        card_position = self.lookup_card.mapFromGlobal(self.mapToGlobal(main_position))
        return self.lookup_card.rect().contains(card_position)

    def _drag_position_over_sidebar(self, event: QDragEnterEvent | QDragMoveEvent) -> bool:
        if self.sidebar_pages.currentIndex() != 0 or not self.sidebar_panel.isVisible():
            return False
        main_position = event.position().toPoint()
        sidebar_position = self.sidebar_panel.mapFromGlobal(self.mapToGlobal(main_position))
        return self.sidebar_panel.rect().contains(sidebar_position)

    def _set_lookup_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self._lookup_drop_active == active:
            return
        self._lookup_drop_active = active
        self.lookup_card.setProperty("dropActive", active)
        self.lookup_qr_button.setProperty("dropActive", active)
        if self.lookup_qr_button.isEnabled():
            self.lookup_qr_button.setText("松开即可识别实名码" if active else "导入机身实名码")
        for widget in (self.lookup_card, self.lookup_qr_button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _set_sidebar_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self._sidebar_drop_active == active:
            return
        self._sidebar_drop_active = active
        if active:
            self.sidebar_drop_overlay.setGeometry(self.sidebar_panel.rect())
            self.sidebar_drop_overlay.show()
            self.sidebar_drop_overlay.raise_()
        else:
            self.sidebar_drop_overlay.hide()

    def eventFilter(self, watched, event) -> bool:
        if (
            self._paper_selection_editing
            and event.type() == QEvent.Type.MouseButtonPress
            and not self._paper_selection_control_contains_event(watched, event)
        ):
            self._commit_paper_selection()
        if watched is self.sidebar_panel and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            if hasattr(self, "sidebar_drop_overlay"):
                self.sidebar_drop_overlay.setGeometry(self.sidebar_panel.rect())
            if self.dji_sidebar_overlay is not None:
                self.dji_sidebar_overlay.setGeometry(self.sidebar_panel.rect())
                if self.dji_sidebar_overlay.isVisible():
                    self.dji_sidebar_overlay.raise_()
        return super().eventFilter(watched, event)

    def _paper_selection_control_contains_event(self, watched, event) -> bool:
        point = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else None
        controls = (self.paper_selector, self.paper_change_button, self.paper_selector._popup)
        if point is not None:
            for widget in controls:
                if not widget.isVisible():
                    continue
                top_left = widget.mapToGlobal(widget.rect().topLeft())
                if widget.rect().translated(top_left).contains(point):
                    return True
            return False
        for widget in controls:
            if watched is widget or (isinstance(watched, QWidget) and widget.isAncestorOf(watched)):
                return True
        return False

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._drag_contains_supported_file(event):
            self._set_lookup_drop_active(self._drag_position_over_lookup_card(event))
            self._set_sidebar_drop_active(self._drag_position_over_sidebar(event))
            event.acceptProposedAction()
        else:
            self._set_lookup_drop_active(False)
            self._set_sidebar_drop_active(False)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._drag_contains_supported_file(event):
            self._set_lookup_drop_active(self._drag_position_over_lookup_card(event))
            self._set_sidebar_drop_active(self._drag_position_over_sidebar(event))
            event.acceptProposedAction()
        else:
            self._set_lookup_drop_active(False)
            self._set_sidebar_drop_active(False)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_lookup_drop_active(False)
        self._set_sidebar_drop_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_lookup_drop_active(False)
        self._set_sidebar_drop_active(False)
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            suffix = path.suffix.lower()
            if suffix not in {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
                continue
            if self.sidebar_pages.currentIndex() == 1:
                self.process_registration_code(path)
                event.acceptProposedAction()
                break
            self.process_manual(path)
            event.acceptProposedAction()
            break

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self._minimize_to_floating)

    def _minimize_to_floating(self) -> None:
        self._commit_paper_selection()
        self.hide()
        if self.monitoring:
            self.floating_window.set_status("监听中", "当前正在持续监听UOM实名登记。", "success")
        else:
            self.floating_window.set_status("已最小化", "软件仍在后台运行。", "idle")
        self.floating_window.show_near_corner(self._saved_floating_position())
        self._sync_floating_controls()

    def _close_to_floating(self) -> None:
        self.hide()
        if self.monitoring:
            self.floating_window.set_status("监听中", "主界面已收起，实名监听仍在继续。", "success")
            message = "主界面已收起为悬浮窗，当前正在持续监听。"
        else:
            self.floating_window.set_status("后台运行中", "点击悬浮窗可重新打开主界面。", "idle")
            message = "主界面已收起为悬浮窗；如需彻底关闭，请使用托盘菜单。"
        self.floating_window.show_near_corner(self._saved_floating_position())
        self._sync_floating_controls()
        self._notify("UOM自动打印", message)

    def closeEvent(self, event) -> None:
        self._commit_paper_selection()
        if not self.force_quit:
            event.ignore()
            self.append_log("info", "已通过关闭按钮收起为悬浮窗；程序和自动监听保持运行。")
            self._close_to_floating()
            return
        self.monitoring = False
        self.monitor_timer.stop()
        self.registration_face_timer.stop()
        self._hide_dji_inline_verification()
        if self.registration_face_dialog is not None:
            self.registration_face_dialog.close()
            self.registration_face_dialog = None
        self.floating_window.close()
        self.tray_icon.hide()
        application = QApplication.instance()
        if application is not None and self._application_event_filter_installed:
            application.removeEventFilter(self)
            self._application_event_filter_installed = False
        if self.uom_view is not None:
            self.uom_view.setPage(QWebEnginePage(self.uom_view))
        if self.dji_view is not None:
            self.dji_view.setPage(QWebEnginePage(self.dji_view))
        if self.dji_web is not None:
            self.dji_web.shutdown()
        self.uom_web.shutdown()
        super().closeEvent(event)
