from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class RoundedMessageDialog(QDialog):
    """A frameless modal message card whose outer corners are truly rounded."""

    ICONS = {"info": "i", "warning": "!", "error": "×", "about": "i", "success": "✓"}
    ACTION_STYLES = {
        "primary": "RoundedDialogConfirm",
        "secondary": "RoundedDialogCancel",
        "success": "RoundedDialogSuccessConfirm",
        "danger": "RoundedDialogDangerConfirm",
        "danger-secondary": "RoundedDialogDangerSecondary",
    }

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        kind: str = "info",
        confirm_text: str = "知道了",
        cancel_text: str | None = None,
        destructive: bool = False,
        detail: str | None = None,
        action_specs: tuple[tuple[str, str, str], ...] | None = None,
        default_action: str = "confirm",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RoundedMessageDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumWidth(420)
        self.setMaximumWidth(580)
        self._drag_offset: QPoint | None = None
        self.selected_action = "cancel"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        card = QFrame(objectName="RoundedDialogCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(15, 23, 42, 52))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(15)

        header = QHBoxLayout()
        header.setSpacing(11)
        icon = QLabel(self.ICONS.get(kind, "i"), objectName="RoundedDialogIcon")
        icon.setProperty("kind", kind)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(38, 38)
        header.addWidget(icon, 0, Qt.AlignTop)
        title_label = QLabel(title, objectName="RoundedDialogTitle")
        title_label.setWordWrap(True)
        header.addWidget(title_label, 1, Qt.AlignVCenter)
        close_button = QPushButton("×", objectName="RoundedDialogClose")
        close_button.setFixedSize(30, 30)
        close_button.setToolTip("关闭")
        close_button.clicked.connect(self.reject)
        header.addWidget(close_button, 0, Qt.AlignTop)
        layout.addLayout(header)

        message_label = QLabel(message, objectName="RoundedDialogMessage")
        message_label.setTextFormat(Qt.AutoText)
        message_label.setWordWrap(True)
        message_label.setOpenExternalLinks(False)
        message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(message_label)

        if detail:
            detail_label = QLabel(detail, objectName="RoundedDialogDetail")
            detail_label.setProperty("kind", kind)
            detail_label.setWordWrap(True)
            detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(detail_label)

        actions = QHBoxLayout()
        actions.setSpacing(9)
        actions.addStretch()
        specs = action_specs
        if specs is None:
            generated: list[tuple[str, str, str]] = []
            if cancel_text:
                generated.append(("cancel", cancel_text, "secondary"))
            generated.append(("confirm", confirm_text, "danger" if destructive else "primary"))
            specs = tuple(generated)
        for key, text, style in specs:
            button = QPushButton(text, objectName=self.ACTION_STYLES.get(style, "RoundedDialogCancel"))
            button.setMinimumWidth(96)
            button.setMinimumHeight(36)
            button.clicked.connect(lambda _checked=False, action=key: self._select_action(action))
            if key == default_action:
                button.setDefault(True)
                button.setAutoDefault(True)
            actions.addWidget(button)
        layout.addLayout(actions)

    def _select_action(self, action: str) -> None:
        self.selected_action = action
        self.accept()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            center = parent.frameGeometry().center()
        else:
            screen = QApplication.screenAt(self.cursor().pos()) or QApplication.primaryScreen()
            center = screen.availableGeometry().center() if screen is not None else QPoint(600, 400)
        self.move(center - self.rect().center())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class FaceVerificationDialog(QDialog):
    """Focused UOM official face QR that closes itself after verification."""

    provider_switch_requested = Signal(str)
    PROVIDER_LABELS = {"wx": "微信", "zfb": "支付宝"}

    def __init__(
        self,
        parent: QWidget | None,
        qr_pixmap: QPixmap,
        *,
        provider: str = "wx",
        available_providers: tuple[str, ...] = ("wx",),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FaceVerificationDialog")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModal)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(390)
        normalized = tuple(item for item in available_providers if item in self.PROVIDER_LABELS)
        self._available_providers = normalized or ("wx",)
        self._provider = provider if provider in self._available_providers else self._available_providers[0]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        card = QFrame(objectName="FaceVerificationCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(15, 23, 42, 58))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.title_label = QLabel(objectName="FaceVerificationTitle")
        header.addWidget(self.title_label)
        header.addStretch()
        close_button = QPushButton("×", objectName="RoundedDialogClose")
        close_button.setFixedSize(30, 30)
        close_button.setToolTip("关闭本次认证，稍后可重新打开")
        close_button.clicked.connect(self.reject)
        header.addWidget(close_button)
        layout.addLayout(header)

        self.detail_label = QLabel(objectName="FaceVerificationDetail")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.qr_label = QLabel(objectName="FaceVerificationQr")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedSize(278, 278)
        layout.addWidget(self.qr_label, 0, Qt.AlignHCenter)
        self.set_qr(qr_pixmap)

        self.status_label = QLabel("等待扫码和人脸认证…", objectName="FaceVerificationStatus")
        self.status_label.setProperty("state", "working")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.switch_button = QPushButton(objectName="FaceProviderSwitch")
        self.switch_button.setMinimumHeight(36)
        self.switch_button.clicked.connect(self._request_provider_switch)
        layout.addWidget(self.switch_button)
        self._sync_provider_text()

    @property
    def provider(self) -> str:
        return self._provider

    def _provider_label(self, provider: str | None = None) -> str:
        return self.PROVIDER_LABELS.get(provider or self._provider, "官方")

    def _next_provider(self) -> str | None:
        candidates = [item for item in self._available_providers if item != self._provider]
        return candidates[0] if candidates else None

    def _sync_provider_text(self) -> None:
        label = self._provider_label()
        self.setWindowTitle(f"UOM{label}人脸认证")
        self.title_label.setText(f"{label}人脸认证")
        self.detail_label.setText(f"请用{label}扫码，按UOM官方提示完成人脸认证。")
        next_provider = self._next_provider()
        self.switch_button.setVisible(next_provider is not None)
        if next_provider is not None:
            self.switch_button.setText(f"切换{self._provider_label(next_provider)}")
            self.switch_button.setToolTip(f"重新生成UOM官方{self._provider_label(next_provider)}认证码")

    def _request_provider_switch(self) -> None:
        next_provider = self._next_provider()
        if next_provider is None:
            return
        self.switch_button.setEnabled(False)
        self.set_status(f"正在生成{self._provider_label(next_provider)}认证码…", "working")
        self.provider_switch_requested.emit(next_provider)

    def set_provider_qr(
        self,
        provider: str,
        pixmap: QPixmap,
        available_providers: tuple[str, ...],
    ) -> None:
        normalized = tuple(item for item in available_providers if item in self.PROVIDER_LABELS)
        self._available_providers = normalized or (provider if provider in self.PROVIDER_LABELS else "wx",)
        self._provider = provider if provider in self._available_providers else self._available_providers[0]
        self.set_qr(pixmap)
        self.switch_button.setEnabled(True)
        self.switch_button.setProperty("recommended", False)
        self.switch_button.style().unpolish(self.switch_button)
        self.switch_button.style().polish(self.switch_button)
        self._sync_provider_text()
        self.set_status("等待扫码和人脸认证…", "working")

    def set_qr(self, pixmap: QPixmap) -> None:
        self.qr_label.setPixmap(pixmap.scaled(258, 258, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_status(self, text: str, state: str) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def emphasize_provider_switch(self) -> None:
        if not self.switch_button.isVisible():
            return
        self.switch_button.setProperty("recommended", True)
        self.switch_button.style().unpolish(self.switch_button)
        self.switch_button.style().polish(self.switch_button)

    def mark_success(self) -> None:
        self.switch_button.setEnabled(False)
        self.set_status(f"✓  {self._provider_label()}认证成功，正在继续准备登记资料…", "success")
        QTimer.singleShot(650, self.accept)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            center = parent.frameGeometry().center()
        else:
            screen = QApplication.primaryScreen()
            center = screen.availableGeometry().center() if screen is not None else QPoint(600, 400)
        self.move(center - self.rect().center())


def show_message(parent: QWidget | None, title: str, message: str, *, kind: str = "info") -> int:
    return RoundedMessageDialog(parent, title, message, kind=kind).exec()


def information(parent: QWidget | None, title: str, message: str) -> int:
    return show_message(parent, title, message, kind="info")


def warning(parent: QWidget | None, title: str, message: str) -> int:
    return show_message(parent, title, message, kind="warning")


def critical(parent: QWidget | None, title: str, message: str) -> int:
    return show_message(parent, title, message, kind="error")


def about(parent: QWidget | None, title: str, message: str) -> int:
    return show_message(parent, title, message, kind="about")


def confirm_danger(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    confirm_text: str = "确认注销",
    cancel_text: str = "先不注销",
    detail: str | None = None,
) -> bool:
    dialog = RoundedMessageDialog(
        parent,
        title,
        message,
        kind="warning",
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        destructive=True,
        detail=detail,
    )
    dialog.exec()
    return dialog.selected_action == "confirm"


def confirm_submit(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    confirm_text: str = "确认提交",
    cancel_text: str = "取消",
    detail: str | None = None,
) -> bool:
    dialog = RoundedMessageDialog(
        parent,
        title,
        message,
        kind="success",
        detail=detail,
        action_specs=(
            ("cancel", cancel_text, "secondary"),
            ("confirm", confirm_text, "success"),
        ),
        default_action="confirm",
    )
    dialog.exec()
    return dialog.selected_action == "confirm"


def choose(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    detail: str | None = None,
    kind: str = "warning",
    actions: tuple[tuple[str, str, str], ...],
    default_action: str,
) -> str:
    dialog = RoundedMessageDialog(
        parent,
        title,
        message,
        kind=kind,
        detail=detail,
        action_specs=actions,
        default_action=default_action,
    )
    dialog.exec()
    return dialog.selected_action
