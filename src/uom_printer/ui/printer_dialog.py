from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from .rounded_dialog import warning

from ..diagnostics import get_logger
from ..printing import list_printers
from .widgets import FeedbackButton, WheelSafeComboBox


class PrinterDialog(QDialog):
    printer_selected = Signal(str)

    def __init__(self, current_printer: str, parent=None) -> None:
        super().__init__(parent)
        self.current_printer = current_printer.strip()
        self.file_logger = get_logger()
        self.setWindowTitle("选择打印机")
        self.setMinimumWidth(470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel("打印机", objectName="SectionTitle")
        layout.addWidget(title)
        note = QLabel("选择用于60 × 40 mm标签的Windows打印机。滚轮不会更改选择。", objectName="StatusDetail")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.printer_combo = WheelSafeComboBox()
        layout.addWidget(self.printer_combo)
        self.state_label = QLabel("正在读取打印机列表…", objectName="LookupState")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)

        self.refresh_button = FeedbackButton("刷新打印机列表", objectName="MenuButton")
        self.refresh_button.clicked.connect(self.refresh_printers)
        layout.addWidget(self.refresh_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_printers()

    def refresh_printers(self) -> None:
        selected = self.printer_combo.currentText().strip() or self.current_printer
        try:
            printers = list_printers()
        except Exception as exc:
            printers = []
            self.file_logger.exception("独立打印机选择窗口刷新失败")
            self.state_label.setText(f"读取打印机失败：{exc}")

        self.printer_combo.clear()
        for printer in printers:
            self.printer_combo.addItem(printer, printer)
        if selected and selected not in printers:
            self.printer_combo.addItem(selected, selected)
        if selected:
            self.printer_combo.setCurrentText(selected)

        if printers:
            self.state_label.setText(f"发现 {len(printers)} 台打印机，请选择后保存。")
            self.refresh_button.flash_success()
        elif not self.state_label.text().startswith("读取打印机失败"):
            self.state_label.setText("没有发现Windows打印机，请检查驱动和USB连接。")

    def save(self) -> None:
        printer = str(self.printer_combo.currentData() or self.printer_combo.currentText()).strip()
        if not printer:
            warning(self, "尚未选择打印机", "请先选择一台Windows打印机。")
            return
        self.printer_selected.emit(printer)
        self.accept()
