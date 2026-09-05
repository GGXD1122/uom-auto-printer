from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .widgets import FeedbackButton, PhotoDropTile


class ModelCandidateCard(QFrame):
    """Clickable candidate surface so blank card space selects in one press."""

    clicked = Signal()

    def __init__(self, parent=None, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class RegistrationPanel(QWidget):
    """Self-contained UI surface for the registration/cancellation workflow."""

    identify_requested = Signal()
    cancellation_requested = Signal()
    photo_clicked = Signal(str)
    photo_dropped = Signal(str, str)
    model_candidate_confirmed = Signal()
    model_catalog_update_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, objectName="SidebarPage")
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        registration_card = QFrame(objectName="RegistrationCard")
        self.registration_card = registration_card
        # When the candidate list expands, this card must keep the height of
        # its complete photo/button/status layout. The sidebar can scroll; it
        # must never reclaim space by squeezing the photo tiles under the next
        # button.
        registration_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        registration_card_layout = QVBoxLayout(registration_card)
        registration_card_layout.setSizeConstraint(QLayout.SetMinimumSize)
        registration_card_layout.setContentsMargins(14, 13, 14, 14)
        registration_card_layout.setSpacing(9)
        registration_header = QHBoxLayout()
        registration_header.addWidget(QLabel("实名登记准备", objectName="SectionTitle"))
        registration_header.addStretch()
        self.registration_reset_button = FeedbackButton(
            "重置",
            objectName="GhostSmall",
            elevated=False,
        )
        self.registration_reset_button.setFixedSize(58, 28)
        self.registration_reset_button.setEnabled(False)
        self.registration_reset_button.setToolTip("清空本次实名流程，不影响登录、型号库和软件设置")
        self.registration_reset_button.clicked.connect(self.reset_requested.emit)
        registration_header.addWidget(self.registration_reset_button)
        registration_card_layout.addLayout(registration_header)
        intro = QLabel(
            "填写序列号和两张机器照片。大疆登录/滑块和UOM官方人脸由你本人完成，其余字段自动准备。",
            objectName="StatusDetail",
        )
        intro.setWordWrap(True)
        registration_card_layout.addWidget(intro)
        self.registration_serial_input = QLineEdit()
        self.registration_serial_input.setPlaceholderText("输入飞行器产品序列号")
        self.registration_serial_input.setClearButtonEnabled(True)
        registration_card_layout.addWidget(self.registration_serial_input)

        photo_row = QHBoxLayout()
        photo_row.setSpacing(8)
        photo_row.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.registration_front_tile = PhotoDropTile("机身照片", "拖入或点击选择")
        self.registration_serial_tile = PhotoDropTile("序列号照片", "拖入或点击选择")
        self.registration_front_tile.clicked.connect(lambda: self.photo_clicked.emit("front"))
        self.registration_serial_tile.clicked.connect(lambda: self.photo_clicked.emit("serial"))
        self.registration_front_tile.fileDropped.connect(
            lambda path: self.photo_dropped.emit("front", path)
        )
        self.registration_serial_tile.fileDropped.connect(
            lambda path: self.photo_dropped.emit("serial", path)
        )
        photo_row.addWidget(self.registration_front_tile)
        photo_row.addWidget(self.registration_serial_tile)
        registration_card_layout.addLayout(photo_row)

        self.registration_identify_button = FeedbackButton("识别并认证", objectName="Accent")
        self.registration_identify_button.setEnabled(False)
        self.registration_identify_button.setProperty("workflowState", "waiting")
        self.registration_identify_button.setToolTip("填写序列号并放入两张照片后开始")
        self.registration_identify_button.clicked.connect(self.identify_requested.emit)
        registration_card_layout.addWidget(self.registration_identify_button)
        self.registration_state = QLabel("等待填写序列号和选择照片", objectName="RegistrationState")
        self.registration_state.setProperty("state", "idle")
        self.registration_state.setWordWrap(True)
        registration_card_layout.addWidget(self.registration_state)
        layout.addWidget(registration_card)
        self.sync_registration_card_height()

        # The registration flow has one primary action. Keep this alias for
        # callers that still use the old name while the UI exposes no second
        # button or competing submission card.
        self.registration_prepare_button = self.registration_identify_button

        self.registration_model_card = QFrame(objectName="RegistrationCard")
        self.registration_model_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        model_layout = QVBoxLayout(self.registration_model_card)
        self.registration_model_layout = model_layout
        model_layout.setSizeConstraint(QLayout.SetMinimumSize)
        model_layout.setContentsMargins(14, 13, 14, 14)
        model_layout.setSpacing(8)
        model_header = QHBoxLayout()
        model_header.addWidget(QLabel("精准机型", objectName="SectionTitle"))
        model_header.addStretch()
        self.registration_model_chip = QLabel("待识别", objectName="ModeChip")
        model_header.addWidget(self.registration_model_chip)
        self.registration_model_update_button = FeedbackButton(
            "更新",
            objectName="ModelCatalogUpdate",
            elevated=False,
        )
        self.registration_model_update_button.setFixedSize(58, 30)
        self.registration_model_update_button.setToolTip("重新拉取UOM全部大疆型号和大疆官网公开产品目录")
        self.registration_model_update_button.clicked.connect(self.model_catalog_update_requested.emit)
        model_header.addWidget(self.registration_model_update_button)
        model_layout.addLayout(model_header)
        self.registration_model_catalog_status = QLabel(
            "本地型号库尚未更新，首次使用会从官方拉取。",
            objectName="ModelCatalogStatus",
        )
        self.registration_model_catalog_status.setProperty("state", "empty")
        self.registration_model_catalog_status.setWordWrap(True)
        model_layout.addWidget(self.registration_model_catalog_status)
        self.registration_model_title = QLabel("尚未读取大疆官方机型", objectName="ProductTitle")
        self.registration_model_title.setWordWrap(True)
        model_layout.addWidget(self.registration_model_title)
        self.registration_model_detail = QLabel("大疆型号先保存在本地，人脸认证通过后才查询UOM型号。", objectName="ProductSummary")
        self.registration_model_detail.setWordWrap(True)
        model_layout.addWidget(self.registration_model_detail)

        self.registration_model_candidates_frame = QFrame(objectName="ModelCandidateList")
        self.registration_model_candidates_frame.setMinimumWidth(0)
        # Keep the list at its natural content height. Calculating and forcing
        # a minimum height before the Windows sidebar has its final width can
        # leave a large blank area until the first option is selected.
        self.registration_model_candidates_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        candidate_layout = QVBoxLayout(self.registration_model_candidates_frame)
        self.registration_model_candidates_box = candidate_layout
        candidate_layout.setSizeConstraint(QLayout.SetMinimumSize)
        candidate_layout.setContentsMargins(10, 9, 10, 9)
        candidate_layout.setSpacing(8)
        self.registration_model_candidates_hint = QLabel(
            "UOM找到多个同名型号，请选择对应的型号代码：",
            objectName="ModelCandidateHint",
        )
        self.registration_model_candidates_hint.setWordWrap(True)
        candidate_layout.addWidget(self.registration_model_candidates_hint)
        self.registration_model_search = QLineEdit(objectName="ModelCandidateSearch")
        self.registration_model_search.setPlaceholderText("搜索全部本地UOM型号或型号代码")
        self.registration_model_search.setClearButtonEnabled(True)
        self.registration_model_search.textChanged.connect(self._filter_model_candidates)
        candidate_layout.addWidget(self.registration_model_search)
        self.registration_model_candidates_layout = QVBoxLayout()
        self.registration_model_candidates_layout.setSpacing(6)
        candidate_layout.addLayout(self.registration_model_candidates_layout)
        candidate_action_frame = QWidget()
        candidate_action_frame.setMinimumHeight(48)
        candidate_action_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        candidate_action_row = QHBoxLayout(candidate_action_frame)
        candidate_action_row.setContentsMargins(0, 2, 0, 6)
        candidate_action_row.addStretch()
        self.registration_model_confirm_button = FeedbackButton(
            "选好了",
            objectName="ModelCandidateConfirm",
            elevated=False,
        )
        self.registration_model_confirm_button.setFixedWidth(104)
        self.registration_model_confirm_button.setMinimumHeight(40)
        self.registration_model_confirm_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        self.registration_model_confirm_button.setEnabled(False)
        self.registration_model_confirm_button.clicked.connect(self.model_candidate_confirmed.emit)
        candidate_action_row.addWidget(self.registration_model_confirm_button)
        candidate_layout.addWidget(candidate_action_frame, 0, Qt.AlignTop)
        self.registration_model_candidates_frame.hide()
        model_layout.addWidget(self.registration_model_candidates_frame, 0, Qt.AlignTop)
        self._model_candidates: list[dict[str, Any]] = []
        self._all_model_candidates: list[dict[str, Any]] = []
        self._initial_model_candidates: list[dict[str, Any]] = []
        self._model_candidate_buttons: list[QRadioButton] = []
        self._model_candidate_cards: list[QFrame] = []
        self._model_candidate_meta_labels: list[QLabel] = []
        self._model_candidate_group = QButtonGroup(self)
        self._model_candidate_group.setExclusive(True)
        self._model_candidate_group.buttonToggled.connect(self._model_candidate_toggled)
        layout.addWidget(self.registration_model_card, 0, Qt.AlignTop)

        cancellation_card = QFrame(objectName="RegistrationCard")
        self.registration_cancellation_card = cancellation_card
        cancellation_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        cancellation_layout = QVBoxLayout(cancellation_card)
        cancellation_layout.setSizeConstraint(QLayout.SetMinimumSize)
        cancellation_layout.setContentsMargins(14, 13, 14, 14)
        cancellation_layout.setSpacing(8)
        cancellation_layout.addWidget(QLabel("实名注销", objectName="SectionTitle"))
        cancellation_text = QLabel(
            "输入序列号或唯一识别码。软件只允许注销当前UOM账号名下的设备。",
            objectName="StatusDetail",
        )
        cancellation_text.setWordWrap(True)
        cancellation_layout.addWidget(cancellation_text)
        cancellation_row = QHBoxLayout()
        cancellation_row.setSpacing(8)
        self.cancellation_serial_input = QLineEdit()
        self.cancellation_serial_input.setPlaceholderText("序列号或唯一识别码")
        self.cancellation_serial_input.setClearButtonEnabled(True)
        self.cancellation_serial_input.returnPressed.connect(self.cancellation_requested.emit)
        cancellation_row.addWidget(self.cancellation_serial_input, 1)
        self.cancellation_button = FeedbackButton("注销", objectName="LookupCancel", elevated=False)
        self.cancellation_button.setFixedSize(72, 34)
        self.cancellation_button.clicked.connect(self.cancellation_requested.emit)
        cancellation_row.addWidget(self.cancellation_button)
        cancellation_layout.addLayout(cancellation_row)
        self.cancellation_state = QLabel("等待输入需要注销的设备编号", objectName="RegistrationState")
        self.cancellation_state.setProperty("state", "idle")
        self.cancellation_state.setWordWrap(True)
        cancellation_layout.addWidget(self.cancellation_state)
        layout.addWidget(cancellation_card)

        layout.addStretch()

    def sync_registration_card_height(self) -> None:
        """Prevent the expanded model list from squeezing the photo card."""

        card_layout = self.registration_card.layout()
        if card_layout is not None:
            card_layout.invalidate()
            card_layout.activate()
        preferred_height = max(1, self.registration_card.sizeHint().height())
        if self.registration_card.minimumHeight() != preferred_height:
            self.registration_card.setMinimumHeight(preferred_height)
        self.registration_card.updateGeometry()
        if self.layout() is not None:
            self.layout().invalidate()
            self.layout().activate()
        self.updateGeometry()

    def set_model_catalog_status(self, text: str, state: str, *, busy: bool = False) -> None:
        self.registration_model_catalog_status.setText(str(text or ""))
        self.registration_model_catalog_status.setProperty("state", str(state or "empty"))
        self.registration_model_catalog_status.style().unpolish(self.registration_model_catalog_status)
        self.registration_model_catalog_status.style().polish(self.registration_model_catalog_status)
        self.registration_model_catalog_status.update()
        self.registration_model_update_button.setEnabled(not busy)
        self.registration_model_update_button.setText("更新中" if busy else "更新")

    def show_model_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        all_models: list[dict[str, Any]] | None = None,
        match_type: str = "",
    ) -> None:
        self.clear_model_candidates()
        self._initial_model_candidates = [
            dict(candidate) for candidate in candidates if isinstance(candidate, dict)
        ]
        complete = all_models if all_models is not None else candidates
        self._all_model_candidates = [
            dict(candidate) for candidate in complete if isinstance(candidate, dict)
        ]
        self.registration_model_search.blockSignals(True)
        self.registration_model_search.clear()
        self.registration_model_search.blockSignals(False)
        reason = "未找到唯一精确结果" if match_type == "manual_fallback" else "找到同名或相近结果"
        self.registration_model_candidates_hint.setText(
            f"{reason}，请核对后选择。可搜索全部 {len(self._all_model_candidates)} 个本地UOM型号。"
        )
        self._render_model_candidates(self._initial_model_candidates)
        self.registration_model_candidates_frame.setVisible(bool(self._all_model_candidates))
        if self._all_model_candidates:
            self._activate_candidate_layout()

    def _render_model_candidates(self, candidates: list[dict[str, Any]]) -> None:
        self._clear_candidate_cards()
        self._model_candidates = [dict(candidate) for candidate in candidates[:12]]
        for index, candidate in enumerate(self._model_candidates):
            code = str(candidate.get("chanpxh") or "未标注型号代码").strip()
            name = str(candidate.get("chanpmc") or "未标注机型").strip()
            empty_weight = str(candidate.get("kongjzl") or "—").strip()
            maximum_weight = str(candidate.get("zuidqfzl") or "—").strip()
            option_card = ModelCandidateCard(objectName="ModelCandidateOptionCard")
            option_card.setMinimumWidth(0)
            option_card.setFixedHeight(88)
            option_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            option_layout = QVBoxLayout(option_card)
            option_layout.setContentsMargins(9, 7, 9, 7)
            option_layout.setSpacing(2)
            option = QRadioButton(name, objectName="ModelCandidateOption")
            option.setMinimumWidth(0)
            option.setFixedHeight(24)
            option.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            option.setToolTip(
                f"{name}\n"
                f"型号代码：{code}\n空机重量：{empty_weight} kg\n最大起飞重量：{maximum_weight} kg"
            )
            code_label = QLabel(f"型号代码：{code}", objectName="ModelCandidateCode")
            code_label.setMinimumWidth(0)
            code_label.setFixedHeight(18)
            code_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            code_label.setToolTip(code)
            code_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            detail = QLabel(
                f"空机 {empty_weight} kg  ·  最大 {maximum_weight} kg",
                objectName="ModelCandidateMeta",
            )
            detail.setWordWrap(False)
            detail.setMinimumWidth(0)
            detail.setFixedHeight(20)
            detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            detail.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            option_layout.addWidget(option)
            option_layout.addWidget(code_label)
            option_layout.addWidget(detail)
            option_card.clicked.connect(option.click)
            self._model_candidate_group.addButton(option, index)
            self._model_candidate_buttons.append(option)
            self._model_candidate_cards.append(option_card)
            self._model_candidate_meta_labels.append(detail)
            self.registration_model_candidates_layout.addWidget(option_card, 0, Qt.AlignTop)
        self.registration_model_confirm_button.setEnabled(False)
        self._activate_candidate_layout()

    def _filter_model_candidates(self, text: str) -> None:
        query = "".join(str(text or "").casefold().split())
        if not query:
            matches = self._initial_model_candidates
        else:
            matches = [
                model
                for model in self._all_model_candidates
                if query
                in "".join(
                    f"{model.get('chanpmc', '')}{model.get('chanpxh', '')}".casefold().split()
                )
            ]
        self._render_model_candidates(matches)
        if query and not matches:
            self.registration_model_candidates_hint.setText(
                f"本地 {len(self._all_model_candidates)} 个UOM型号中没有匹配“{text}”的结果。"
            )
        elif query:
            shown = min(12, len(matches))
            suffix = "，请继续缩小关键词" if len(matches) > shown else ""
            self.registration_model_candidates_hint.setText(
                f"找到 {len(matches)} 个结果，当前显示 {shown} 个{suffix}。"
            )

    def _activate_candidate_layout(self) -> None:
        self.registration_model_candidates_box.invalidate()
        self.registration_model_candidates_box.activate()
        self.registration_model_candidates_frame.updateGeometry()
        self.registration_model_layout.invalidate()
        self.registration_model_layout.activate()
        self.registration_model_card.updateGeometry()
        if self.layout() is not None:
            self.layout().invalidate()
            self.layout().activate()
        self.updateGeometry()

    def _clear_candidate_cards(self) -> None:
        for button in self._model_candidate_buttons:
            self._model_candidate_group.removeButton(button)
        for card in self._model_candidate_cards:
            card.setParent(None)
            card.deleteLater()
        self._model_candidate_buttons.clear()
        self._model_candidate_cards.clear()
        self._model_candidate_meta_labels.clear()
        self._model_candidates.clear()
        self.registration_model_confirm_button.setEnabled(False)

    def clear_model_candidates(self) -> None:
        self._clear_candidate_cards()
        self._all_model_candidates.clear()
        self._initial_model_candidates.clear()
        if hasattr(self, "registration_model_search"):
            self.registration_model_search.blockSignals(True)
            self.registration_model_search.clear()
            self.registration_model_search.blockSignals(False)
        self.registration_model_candidates_frame.hide()
        self.registration_model_layout.invalidate()
        self.registration_model_card.updateGeometry()
        self.updateGeometry()

    def selected_model_candidate(self) -> dict[str, Any] | None:
        selected_index = self._model_candidate_group.checkedId()
        if 0 <= selected_index < len(self._model_candidates):
            return dict(self._model_candidates[selected_index])
        return None

    def _model_candidate_toggled(self, button: QRadioButton, checked: bool) -> None:
        try:
            card = self._model_candidate_cards[self._model_candidate_buttons.index(button)]
        except (ValueError, IndexError):
            card = None
        if card is not None:
            card.setProperty("selected", bool(checked))
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()
        if checked:
            self.registration_model_confirm_button.setEnabled(True)
