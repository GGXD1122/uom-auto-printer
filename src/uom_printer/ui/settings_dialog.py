from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..diagnostics import get_logger
from ..paths import output_dir
from ..printing import list_printers
from ..settings import (
    AppSettings,
    DEFAULT_POLL_MAX_SECONDS,
    DEFAULT_POLL_MIN_SECONDS,
    SettingsStore,
)
from .widgets import ToggleSwitch, WheelSafeComboBox


class SettingsDialog(QDialog):
    settings_saved = Signal(object)

    def __init__(self, settings: AppSettings, store: SettingsStore, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.store = store
        self.file_logger = get_logger()
        self.setWindowTitle("设置")
        self.resize(640, 430)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._uom_tab(), "UOM监听")
        self.tabs.addTab(self._print_tab(), "打印与文件")
        self.tabs.addTab(self._automation_tab(), "自动化")
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _uom_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(14)
        note = QLabel(
            "软件使用主界面右侧的 UOM 官方网页完成登录，并通过当前网页会话只读检查实名登记列表。首次监听只建立基线，之后仅处理新增登记。",
            objectName="InfoNote",
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        privacy = QLabel(
            "登录 Cookie 与 localStorage 仅保存在本机独立浏览器目录。软件不会把 Token、Cookie 或身份证号写入配置和日志；登录短暂失效或页面刷新时会保持监听并自动重试。",
            objectName="Subtitle",
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        self.open_registration = ToggleSwitch("开始监听时自动打开实名登记页面")
        self.open_registration.setChecked(self.settings.uom_auto_open_registration)
        layout.addWidget(self.open_registration)
        layout.addStretch()
        return tab

    def _print_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(16, 18, 16, 16)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(14)
        self.printer = WheelSafeComboBox()
        printers = list_printers()
        self.printer.addItems(printers)
        if self.settings.printer_name and self.settings.printer_name not in printers:
            self.printer.addItem(self.settings.printer_name)
        self.printer.setCurrentText(self.settings.printer_name)
        self.output_path = QLineEdit(self.settings.output_directory)
        self.output_path.setPlaceholderText(str(output_dir()))
        choose_output = QPushButton("选择")
        choose_output.setToolTip("更改标签文件保存目录")
        choose_output.clicked.connect(self._choose_output_directory)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_path, 1)
        output_row.addWidget(choose_output)

        form.addRow("打印机", self.printer)
        form.addRow("保存目录", output_row)
        return tab

    def _automation_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        interval_note = QLabel("默认每 3–10 秒随机检查一次，无需手动设置。", objectName="InfoNote")
        interval_note.setWordWrap(True)
        self.auto_monitor = ToggleSwitch("软件启动后自动开始监听")
        self.auto_monitor.setChecked(self.settings.auto_monitor)
        self.auto_print = ToggleSwitch("新增实名登记识别成功后自动打印")
        self.auto_print.setChecked(self.settings.auto_print)
        self.manual_auto = ToggleSwitch("手动导入后直接打印")
        self.manual_auto.setChecked(self.settings.manual_import_auto_print)
        self.floating_on_monitor = ToggleSwitch("开始监听后自动收起为悬浮状态窗")
        self.floating_on_monitor.setChecked(self.settings.floating_on_monitor)
        form.addRow("检查间隔", interval_note)
        form.addRow("", self.auto_monitor)
        form.addRow("", self.auto_print)
        form.addRow("", self.manual_auto)
        form.addRow("", self.floating_on_monitor)
        return tab

    def _choose_output_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择标签保存文件夹",
            self.output_path.text().strip() or str(output_dir()),
        )
        if directory:
            self.output_path.setText(directory)

    def _values(self) -> AppSettings:
        value = AppSettings(**{name: getattr(self.settings, name) for name in self.settings.__dataclass_fields__})
        value.printer_name = self.printer.currentText().strip()
        value.output_directory = self.output_path.text().strip()
        value.poll_jitter_min_seconds = DEFAULT_POLL_MIN_SECONDS
        value.poll_jitter_max_seconds = DEFAULT_POLL_MAX_SECONDS
        value.poll_seconds = (DEFAULT_POLL_MIN_SECONDS + DEFAULT_POLL_MAX_SECONDS + 1) // 2
        value.auto_monitor = self.auto_monitor.isChecked()
        value.auto_print = self.auto_print.isChecked()
        value.manual_import_auto_print = self.manual_auto.isChecked()
        value.floating_on_monitor = self.floating_on_monitor.isChecked()
        value.uom_auto_open_registration = self.open_registration.isChecked()
        return value

    def save(self) -> None:
        values = self._values()
        self.store.save(values)
        self.settings_saved.emit(values)
        self.file_logger.info(
            "用户保存设置 | printer=%s | output=%s | interval=%s-%ss",
            values.printer_name or "未选择",
            values.output_directory or "桌面默认目录",
            values.poll_jitter_min_seconds,
            values.poll_jitter_max_seconds,
        )
        self.accept()
