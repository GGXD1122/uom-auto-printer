from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


PAPER_PRESETS = (
    ("40 × 30 mm", 40.0, 30.0),
    ("40 × 40 mm", 40.0, 40.0),
    ("40 × 60 mm", 40.0, 60.0),
    ("50 × 30 mm", 50.0, 30.0),
    ("50 × 40 mm", 50.0, 40.0),
    ("50 × 50 mm", 50.0, 50.0),
    ("57 × 30 mm", 57.0, 30.0),
    ("57 × 40 mm", 57.0, 40.0),
    ("57 × 50 mm", 57.0, 50.0),
    ("60 × 30 mm", 60.0, 30.0),
    ("60 × 40 mm", 60.0, 40.0),
    ("60 × 50 mm", 60.0, 50.0),
    ("70 × 40 mm", 70.0, 40.0),
    ("70 × 50 mm", 70.0, 50.0),
    ("70 × 60 mm", 70.0, 60.0),
    ("80 × 40 mm", 80.0, 40.0),
    ("80 × 50 mm", 80.0, 50.0),
    ("80 × 60 mm", 80.0, 60.0),
    ("80 × 80 mm", 80.0, 80.0),
)

MIN_SAFE_QR_MM = 18.0
MIN_TEXT_SIZE_MM = 2.2
MIN_ELEMENT_GAP_MM = 0.2
MIN_PAPER_WIDTH_MM = 10.0
MIN_PAPER_HEIGHT_MM = 10.0
MAX_PAPER_WIDTH_MM = 200.0
MAX_PAPER_HEIGHT_MM = 200.0
DEFAULT_PAPER_WIDTH_MM = 60.0
DEFAULT_PAPER_HEIGHT_MM = 40.0


@dataclass(frozen=True, slots=True)
class PresetProfile:
    margin_mm: float
    qr_pair_size_mm: float
    info_qr_size_mm: float
    info_mode: str


# Every shipped size has an reviewed profile.  The profile is deliberately
# explicit: a 60x30 label must never be produced by squeezing the 60x40 layout.
DEFAULT_PRESET_PROFILES: dict[tuple[float, float], PresetProfile] = {
    (40.0, 30.0): PresetProfile(1.2, 18.0, 18.0, "micro"),
    (40.0, 40.0): PresetProfile(1.5, 18.0, 18.0, "narrow"),
    (40.0, 60.0): PresetProfile(1.8, 22.5, 22.0, "portrait"),
    (50.0, 30.0): PresetProfile(1.3, 21.5, 18.0, "micro"),
    (50.0, 40.0): PresetProfile(1.8, 21.8, 20.0, "standard"),
    (50.0, 50.0): PresetProfile(2.0, 22.5, 22.0, "standard"),
    (57.0, 30.0): PresetProfile(1.4, 23.5, 18.0, "micro"),
    (57.0, 40.0): PresetProfile(2.0, 25.2, 21.5, "standard"),
    (57.0, 50.0): PresetProfile(2.0, 25.5, 23.0, "standard"),
    (60.0, 30.0): PresetProfile(1.5, 24.0, 18.0, "micro"),
    (60.0, 40.0): PresetProfile(2.0, 27.0, 22.5, "standard"),
    (60.0, 50.0): PresetProfile(2.1, 27.0, 24.0, "standard"),
    (70.0, 40.0): PresetProfile(2.0, 29.0, 23.0, "standard"),
    (70.0, 50.0): PresetProfile(2.2, 30.0, 25.0, "standard"),
    (70.0, 60.0): PresetProfile(2.3, 30.0, 27.0, "standard"),
    (80.0, 40.0): PresetProfile(2.0, 30.0, 23.0, "standard"),
    (80.0, 50.0): PresetProfile(2.2, 31.0, 26.0, "standard"),
    (80.0, 60.0): PresetProfile(2.4, 32.0, 28.0, "standard"),
    (80.0, 80.0): PresetProfile(2.5, 34.0, 32.0, "standard"),
}


DEMO_TEXT_BY_SOURCE = {
    "uas_code": "UAS-DEMO-2026-000001",
    "owner_name": "演示用户",
    "phone_number": "13800000000",
    "model_name": "DJI Air 3S 畅飞套装（DJI RC 2）",
    "aircraft_serial": "1581FDEMO00000000001",
    "empty_weight_label": "空机重量 724 g",
    "maximum_takeoff_weight_label": "最大起飞重量 1420 g",
    "product_model_label": "产品型号 CZ3SCLV",
    "manufacturer_label": "制造商 深圳市大疆创新科技有限公司",
    "registration_time_label": "登记时间 2026-07-25 09:30:00",
    "status_label": "登记状态 正常",
    "owner_type_label": "主体类型 个人",
}


@dataclass(slots=True)
class LayoutElement:
    id: str
    label: str
    kind: str
    source: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    font_size_mm: float = 3.0
    align: str = "center"
    visible: bool = True
    lock_aspect: bool = False
    rotation_deg: int = 0


@dataclass(slots=True)
class LayoutTemplate:
    name: str = "自定义标签"
    paper_width_mm: float = DEFAULT_PAPER_WIDTH_MM
    paper_height_mm: float = DEFAULT_PAPER_HEIGHT_MM
    safe_margin_mm: float = 2.0
    qr_elements: list[LayoutElement] = field(default_factory=list)
    info_elements: list[LayoutElement] = field(default_factory=list)

    def elements(self, template_kind: str) -> list[LayoutElement]:
        return self.info_elements if template_kind == "info" else self.qr_elements


def _adaptive_profile(width_mm: float, height_mm: float) -> PresetProfile:
    margin = max(1.2, min(2.5, min(width_mm, height_mm) * 0.045))
    portrait = height_mm > width_mm * 1.12
    code_h = 2.4
    gap = 0.7
    if portrait:
        maximum_pair = min(
            width_mm - margin * 2,
            (height_mm - margin * 2 - code_h * 2 - gap) / 2,
        )
        pair_size = min(maximum_pair, max(MIN_SAFE_QR_MM, min(30.0, width_mm * 0.58)))
        mode = "portrait"
    else:
        maximum_pair = min(
            (width_mm - margin * 2 - gap) / 2,
            height_mm - margin * 2 - code_h,
        )
        pair_size = min(maximum_pair, max(MIN_SAFE_QR_MM, min(34.0, width_mm * 0.45, height_mm * 0.72)))
        mode = "micro" if height_mm <= 32.0 else ("narrow" if width_mm < 50.0 else "standard")
    info_size = min(
        width_mm - margin * 2,
        max(MIN_SAFE_QR_MM, min(32.0, width_mm * 0.38, height_mm * 0.62)),
    )
    return PresetProfile(margin, max(MIN_SAFE_QR_MM, pair_size), max(MIN_SAFE_QR_MM, info_size), mode)


def _preset_profile(width_mm: float, height_mm: float) -> PresetProfile:
    return DEFAULT_PRESET_PROFILES.get((width_mm, height_mm), _adaptive_profile(width_mm, height_mm))


def _qr_label_elements(width_mm: float, height_mm: float, profile: PresetProfile) -> list[LayoutElement]:
    margin = profile.margin_mm
    gap = 0.6 if profile.info_mode != "portrait" else 0.9
    code_h = 2.3 if height_mm <= 40.0 else 2.6
    qr_size = profile.qr_pair_size_mm
    if profile.info_mode == "portrait":
        block_height = qr_size + code_h
        total_height = block_height * 2 + gap
        x = (width_mm - qr_size) / 2
        first_y = margin + max(0.0, (height_mm - margin * 2 - total_height) / 2)
        positions = ((x, first_y), (x, first_y + block_height + gap))
    else:
        total_width = qr_size * 2 + gap
        first_x = (width_mm - total_width) / 2
        y = margin + max(0.0, (height_mm - margin * 2 - qr_size - code_h) / 2)
        positions = ((first_x, y), (first_x + qr_size + gap, y))
    result: list[LayoutElement] = []
    for index, (x, y) in enumerate(positions, 1):
        result.append(LayoutElement(f"qr_{index}", f"二维码 {index}", "qr", "qr", x, y, qr_size, qr_size, lock_aspect=True))
        result.append(
            LayoutElement(
                f"uas_{index}",
                f"实名登记标识 {index}",
                "text",
                "uas_code",
                x,
                y + qr_size,
                qr_size,
                code_h,
                MIN_TEXT_SIZE_MM,
            )
        )
    return result


def _text_element(
    element_id: str,
    label: str,
    source: str,
    x: float,
    y: float,
    width: float,
    height: float,
    font_size: float,
    align: str = "left",
    *,
    visible: bool = True,
) -> LayoutElement:
    return LayoutElement(
        element_id,
        label,
        "text",
        source,
        x,
        y,
        width,
        height,
        max(MIN_TEXT_SIZE_MM, font_size),
        align,
        visible,
    )


def _micro_info_elements(width_mm: float, height_mm: float, profile: PresetProfile) -> list[LayoutElement]:
    margin = profile.margin_mm
    gap = 0.35
    qr_size = profile.info_qr_size_mm
    code_h = 2.2
    serial_h = 3.5
    serial_y = height_mm - margin - serial_h
    right_x = margin + qr_size + 0.9
    right_width = width_mm - margin - right_x
    full_width = width_mm - margin * 2
    wide_micro = width_mm >= 50.0

    if wide_micro:
        # 50/57/60 x 30 mm still have enough horizontal room for three clear
        # rows beside the QR.  Keep the phone visible and reserve the entire
        # bottom row for the serial number.
        row_h = 4.4
        total_rows_h = row_h * 3 + gap * 2
        upper_bottom = serial_y - 0.45
        row_y = margin + max(0.0, (upper_bottom - margin - total_rows_h) / 2)
        owner_y = row_y
        phone_y = row_y + row_h + gap
        model_x = right_x
        model_y = row_y + (row_h + gap) * 2
        model_width = right_width
        model_height = row_h
    else:
        # 40 x 30 mm is the tightest supported sheet.  Name and phone share
        # the right column; the long model and serial each receive a full-width
        # row so neither is squeezed into unreadable text.
        row_h = 4.5
        pair_h = row_h * 2 + 0.5
        owner_y = margin + max(0.0, (qr_size - pair_h) / 2)
        phone_y = owner_y + row_h + 0.5
        model_height = 2.8
        model_x = margin
        model_y = serial_y - gap - model_height
        model_width = full_width
    return [
        LayoutElement("info_qr", "二维码", "qr", "qr", margin, margin, qr_size, qr_size, lock_aspect=True),
        _text_element("info_uas", "实名登记标识", "uas_code", margin, margin + qr_size, qr_size, code_h, 2.2, "center"),
        _text_element("owner", "姓名", "owner_name", right_x, owner_y, right_width, row_h, 3.15, "center"),
        _text_element("phone", "电话", "phone_number", right_x, phone_y, right_width, row_h, 2.85, "center"),
        _text_element("weight", "空机重量", "empty_weight_label", right_x, phone_y, right_width, row_h, 2.6, visible=False),
        _text_element("model", "机型", "model_name", model_x, model_y, model_width, model_height, 2.5, "center"),
        _text_element("serial", "序列号", "aircraft_serial", margin, serial_y, full_width, serial_h, 3.05, "center"),
    ]


def _narrow_info_elements(width_mm: float, height_mm: float, profile: PresetProfile) -> list[LayoutElement]:
    margin = profile.margin_mm
    gap = 0.45
    qr_size = profile.info_qr_size_mm
    code_h = 2.4
    serial_h = 4.2
    model_h = 3.6
    serial_y = height_mm - margin - serial_h
    model_y = serial_y - gap - model_h
    upper_bottom = model_y - gap
    block_h = qr_size + code_h
    block_y = margin + max(0.0, (upper_bottom - margin - block_h) / 2)
    right_x = margin + qr_size + 0.9
    right_width = width_mm - margin - right_x
    row_h = 4.0
    row_start = block_y + max(0.0, (block_h - row_h * 2 - gap) / 2)
    full_width = width_mm - margin * 2
    return [
        LayoutElement("info_qr", "二维码", "qr", "qr", margin, block_y, qr_size, qr_size, lock_aspect=True),
        _text_element("info_uas", "实名登记标识", "uas_code", margin, block_y + qr_size, qr_size, code_h, 2.2, "center"),
        _text_element("owner", "姓名", "owner_name", right_x, row_start, right_width, row_h, 3.1, "center"),
        _text_element("phone", "电话", "phone_number", right_x, row_start + row_h + gap, right_width, row_h, 2.65, "center"),
        _text_element("weight", "空机重量", "empty_weight_label", right_x, row_start + (row_h + gap) * 2, right_width, row_h, 2.5, visible=False),
        _text_element("model", "机型", "model_name", margin, model_y, full_width, model_h, 2.8, "center"),
        _text_element("serial", "序列号", "aircraft_serial", margin, serial_y, full_width, serial_h, 3.35, "center"),
    ]


def _standard_info_elements(width_mm: float, height_mm: float, profile: PresetProfile) -> list[LayoutElement]:
    margin = profile.margin_mm
    gap = max(0.6, min(1.1, width_mm * 0.014))
    qr_size = profile.info_qr_size_mm
    code_h = 2.5 if height_mm <= 40.0 else 2.8
    serial_h = max(4.2, min(5.0, height_mm * 0.105))
    serial_y = height_mm - margin - serial_h
    block_h = qr_size + code_h
    upper_bottom = serial_y - gap
    block_y = margin + max(0.0, (upper_bottom - margin - block_h) / 2)
    right_x = margin + qr_size + max(1.1, gap)
    right_width = width_mm - margin - right_x
    row_gap = 0.45
    content_h = min(block_h, 19.4)
    row_h = (content_h - row_gap * 3) / 4
    row_y = block_y + (block_h - content_h) / 2
    return [
        LayoutElement("info_qr", "二维码", "qr", "qr", margin, block_y, qr_size, qr_size, lock_aspect=True),
        _text_element("info_uas", "实名登记标识", "uas_code", margin, block_y + qr_size, qr_size, code_h, 2.2, "center"),
        _text_element("owner", "姓名", "owner_name", right_x, row_y, right_width, row_h, 3.35),
        _text_element("phone", "电话", "phone_number", right_x, row_y + (row_h + row_gap), right_width, row_h, 3.0),
        _text_element("model", "机型", "model_name", right_x, row_y + (row_h + row_gap) * 2, right_width, row_h, 2.9),
        _text_element("weight", "空机重量", "empty_weight_label", right_x, row_y + (row_h + row_gap) * 3, right_width, row_h, 2.8),
        _text_element("serial", "序列号", "aircraft_serial", margin, serial_y, width_mm - margin * 2, serial_h, 3.7, "center"),
    ]


def _portrait_info_elements(width_mm: float, height_mm: float, profile: PresetProfile) -> list[LayoutElement]:
    margin = profile.margin_mm
    gap = 0.55
    qr_size = profile.info_qr_size_mm
    code_h = 2.5
    qr_x = (width_mm - qr_size) / 2
    content_top = margin + qr_size + code_h + 0.9
    content_bottom = height_mm - margin
    row_count = 5
    row_h = min(4.8, max(3.6, (content_bottom - content_top - gap * (row_count - 1)) / row_count))
    used_height = row_h * row_count + gap * (row_count - 1)
    row_y = content_top + max(0.0, (content_bottom - content_top - used_height) / 2)
    full_width = width_mm - margin * 2
    specs = (
        ("owner", "姓名", "owner_name", 3.3),
        ("phone", "电话", "phone_number", 3.0),
        ("model", "机型", "model_name", 2.85),
        ("weight", "空机重量", "empty_weight_label", 2.75),
        ("serial", "序列号", "aircraft_serial", 3.4),
    )
    result = [
        LayoutElement("info_qr", "二维码", "qr", "qr", qr_x, margin, qr_size, qr_size, lock_aspect=True),
        _text_element("info_uas", "实名登记标识", "uas_code", qr_x, margin + qr_size, qr_size, code_h, 2.2, "center"),
    ]
    for index, (element_id, label, source, font_size) in enumerate(specs):
        result.append(
            _text_element(
                element_id,
                label,
                source,
                margin,
                row_y + index * (row_h + gap),
                full_width,
                row_h,
                font_size,
                "center",
            )
        )
    return result


def default_layout_template(
    width_mm: float = DEFAULT_PAPER_WIDTH_MM,
    height_mm: float = DEFAULT_PAPER_HEIGHT_MM,
) -> LayoutTemplate:
    width_mm = max(MIN_PAPER_WIDTH_MM, min(MAX_PAPER_WIDTH_MM, float(width_mm)))
    height_mm = max(MIN_PAPER_HEIGHT_MM, min(MAX_PAPER_HEIGHT_MM, float(height_mm)))
    profile = _preset_profile(width_mm, height_mm)
    qr_elements = _qr_label_elements(width_mm, height_mm, profile)
    if profile.info_mode == "micro":
        info_elements = _micro_info_elements(width_mm, height_mm, profile)
    elif profile.info_mode == "narrow":
        info_elements = _narrow_info_elements(width_mm, height_mm, profile)
    elif profile.info_mode == "portrait":
        info_elements = _portrait_info_elements(width_mm, height_mm, profile)
    else:
        info_elements = _standard_info_elements(width_mm, height_mm, profile)
    return LayoutTemplate(
        name=f"{width_mm:g}×{height_mm:g} 安全预设",
        paper_width_mm=width_mm,
        paper_height_mm=height_mm,
        safe_margin_mm=profile.margin_mm,
        qr_elements=qr_elements,
        info_elements=info_elements,
    )


def _element_from_dict(raw: dict) -> LayoutElement:
    allowed = LayoutElement.__dataclass_fields__.keys()
    return LayoutElement(**{key: raw[key] for key in allowed if key in raw})


def load_layout_template(path: Path) -> LayoutTemplate:
    if not path.is_file():
        return default_layout_template()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return LayoutTemplate(
            name=str(raw.get("name") or "自定义标签"),
            paper_width_mm=max(MIN_PAPER_WIDTH_MM, min(MAX_PAPER_WIDTH_MM, float(raw.get("paper_width_mm", DEFAULT_PAPER_WIDTH_MM)))),
            paper_height_mm=max(MIN_PAPER_HEIGHT_MM, min(MAX_PAPER_HEIGHT_MM, float(raw.get("paper_height_mm", DEFAULT_PAPER_HEIGHT_MM)))),
            safe_margin_mm=max(0.0, min(8.0, float(raw.get("safe_margin_mm", 2.0)))),
            qr_elements=[_element_from_dict(item) for item in raw.get("qr_elements", [])],
            info_elements=[_element_from_dict(item) for item in raw.get("info_elements", [])],
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default_layout_template()


def save_layout_template(template: LayoutTemplate, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(template), ensure_ascii=False, indent=2), encoding="utf-8")


def scale_layout(template: LayoutTemplate, width_mm: float, height_mm: float) -> None:
    old_width = max(1.0, template.paper_width_mm)
    old_height = max(1.0, template.paper_height_mm)
    sx, sy = width_mm / old_width, height_mm / old_height
    for element in template.qr_elements + template.info_elements:
        element.x_mm *= sx
        element.y_mm *= sy
        if element.lock_aspect:
            scale = min(sx, sy)
            element.width_mm *= scale
            element.height_mm *= scale
        else:
            element.width_mm *= sx
            element.height_mm *= sy
        element.font_size_mm *= min(sx, sy)
    template.paper_width_mm = width_mm
    template.paper_height_mm = height_mm


def rotate_layout(template: LayoutTemplate, clockwise: bool = True) -> None:
    old_width = template.paper_width_mm
    old_height = template.paper_height_mm
    for element in template.qr_elements + template.info_elements:
        old_x, old_y = element.x_mm, element.y_mm
        old_element_width, old_element_height = element.width_mm, element.height_mm
        if clockwise:
            element.x_mm = old_height - old_y - old_element_height
            element.y_mm = old_x
            element.rotation_deg = (int(element.rotation_deg) + 90) % 360
        else:
            element.x_mm = old_y
            element.y_mm = old_width - old_x - old_element_width
            element.rotation_deg = (int(element.rotation_deg) - 90) % 360
        element.width_mm = old_element_height
        element.height_mm = old_element_width
    template.paper_width_mm = old_height
    template.paper_height_mm = old_width


def element_preview_text(element: LayoutElement) -> str:
    """Return privacy-safe, realistic-length content for the visual editor."""
    return DEMO_TEXT_BY_SOURCE.get(element.source, element.label)


def layout_issues(template: LayoutTemplate) -> list[str]:
    """Audit visible elements against the printable safe area and each other."""
    issues: list[str] = []
    margin = template.safe_margin_mm
    safe_left = margin
    safe_top = margin
    safe_right = template.paper_width_mm - margin
    safe_bottom = template.paper_height_mm - margin
    for kind in ("qr", "info"):
        visible = [element for element in template.elements(kind) if element.visible]
        for element in visible:
            right = element.x_mm + element.width_mm
            bottom = element.y_mm + element.height_mm
            if (
                element.x_mm < safe_left - 0.01
                or element.y_mm < safe_top - 0.01
                or right > safe_right + 0.01
                or bottom > safe_bottom + 0.01
            ):
                issues.append(f"{kind}:{element.id} 超出安全区")
            if element.kind == "qr" and min(element.width_mm, element.height_mm) < MIN_SAFE_QR_MM - 0.01:
                issues.append(f"{kind}:{element.id} 小于 {MIN_SAFE_QR_MM:g} mm")
            if element.kind == "text" and element.font_size_mm < MIN_TEXT_SIZE_MM - 0.01:
                issues.append(f"{kind}:{element.id} 字号过小")
        for index, first in enumerate(visible):
            first_right = first.x_mm + first.width_mm
            first_bottom = first.y_mm + first.height_mm
            for second in visible[index + 1 :]:
                overlap_width = min(first_right, second.x_mm + second.width_mm) - max(first.x_mm, second.x_mm)
                overlap_height = min(first_bottom, second.y_mm + second.height_mm) - max(first.y_mm, second.y_mm)
                if overlap_width > 0.02 and overlap_height > 0.02:
                    issues.append(f"{kind}:{first.id} 与 {second.id} 重叠")
    return issues


def element_text(element: LayoutElement, record) -> str:
    labelled_sources = {
        "empty_weight_label": ("空机重量", "empty_weight"),
        "maximum_takeoff_weight_label": ("最大起飞重量", "maximum_takeoff_weight"),
        "product_model_label": ("产品型号", "product_model"),
        "manufacturer_label": ("制造商", "manufacturer"),
        "registration_time_label": ("登记时间", "registration_time"),
        "status_label": ("登记状态", "status"),
        "owner_type_label": ("主体类型", "owner_type"),
    }
    if element.source in labelled_sources:
        label, attribute = labelled_sources[element.source]
        return f"{label} {getattr(record, attribute, '') or '未提供'}"
    return str(getattr(record, element.source, "") or "未提供")
