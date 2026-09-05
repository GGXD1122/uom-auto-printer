from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .layout_template import DEFAULT_PAPER_HEIGHT_MM, DEFAULT_PAPER_WIDTH_MM, LayoutTemplate, element_text
from .models import ProcessedLabel, ProcessedLabelSet, UomRecord
from .paths import preview_dir


LABEL_WIDTH_MM = DEFAULT_PAPER_WIDTH_MM
LABEL_HEIGHT_MM = DEFAULT_PAPER_HEIGHT_MM
SERIAL_REGION_WIDTH_MM = 42.2
SERIAL_REGION_HEIGHT_MM = 4.0
INFO_RIGHT_SAFE_MM = 4.0
MM_PER_INCH = 25.4


def safe_path_part(value: str, fallback: str, max_length: int = 64) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in str(value or ""))
    cleaned = " ".join(cleaned.strip(" ._").split()) or fallback
    return cleaned[:max_length].rstrip(" ._") or fallback


def label_output_folder_name(record: UomRecord) -> str:
    """Return a Windows-safe per-aircraft folder name with the requested fields."""
    return "_".join(
        (
            safe_path_part(record.owner_name, "未知姓名", 28),
            safe_path_part(record.phone_number, "未提供电话", 24),
            safe_path_part(record.model_name, "未知机型", 56),
            safe_path_part(record.aircraft_serial, "未知序列号", 48),
        )
    )


def mm_to_px(mm: float, dpi: int) -> int:
    return round(mm / MM_PER_INCH * dpi)


def set_physical_metadata(image: Image.Image, width_mm: float, height_mm: float, dpi: int) -> Image.Image:
    image.info["paper_width_mm"] = float(width_mm)
    image.info["paper_height_mm"] = float(height_mm)
    image.info["dpi"] = (int(dpi), int(dpi))
    return image


def find_font(size_px: int) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size_px)
    return ImageFont.load_default(size=size_px)


def find_condensed_font(size_px: int) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialn.ttf"),
        Path("C:/Windows/Fonts/ARIALN.TTF"),
        Path("/System/Library/Fonts/Supplemental/Arial Narrow.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size_px)
    return find_font(size_px)


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, preferred_size: int, min_size: int = 12) -> ImageFont.ImageFont:
    for size in range(preferred_size, min_size - 1, -2):
        font = find_font(size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
    return find_font(min_size)


def fitted_text_mask(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    preferred_size_px: int,
    *,
    condensed: bool = False,
    allow_upscale: bool = False,
) -> Image.Image:
    """Fit text proportionally inside a fixed pixel region without overflow."""
    font = find_condensed_font(preferred_size_px) if condensed else find_font(preferred_size_px)
    box = draw.textbbox((0, 0), text, font=font)
    text_width = max(1, box[2] - box[0])
    text_height = max(1, box[3] - box[1])
    mask = Image.new("L", (text_width, text_height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((-box[0], -box[1]), text, fill=255, font=font)
    ink_box = mask.getbbox()
    if ink_box:
        mask = mask.crop(ink_box)
    scale = min(max_width / max(1, mask.width), max_height / max(1, mask.height))
    if not allow_upscale:
        scale = min(1.0, scale)
    if abs(scale - 1.0) > 0.001:
        mask = mask.resize(
            (max(1, round(mask.width * scale)), max(1, round(mask.height * scale))),
            Image.Resampling.LANCZOS,
        )
    return mask


def info_label_lines(record: UomRecord) -> tuple[str, str, str, str, str]:
    """Return the five high-contrast lines printed on the information label."""
    weight = record.empty_weight or "未提供"
    return (
        record.owner_name or "未提供",
        record.phone_number or "未提供",
        record.model_name or "未提供",
        record.aircraft_serial or "未提供",
        f"空机重量 {weight}",
    )


def render_custom_layout(
    qr_image: Image.Image,
    record: UomRecord,
    layout: LayoutTemplate,
    template_kind: str,
    dpi: int = 600,
) -> Image.Image:
    width = mm_to_px(layout.paper_width_mm, dpi)
    height = mm_to_px(layout.paper_height_mm, dpi)
    label = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(label)
    for element in layout.elements(template_kind):
        if not element.visible:
            continue
        x = mm_to_px(max(0.0, element.x_mm), dpi)
        y = mm_to_px(max(0.0, element.y_mm), dpi)
        region_w = min(max(1, mm_to_px(element.width_mm, dpi)), width - x)
        region_h = min(max(1, mm_to_px(element.height_mm, dpi)), height - y)
        if region_w <= 0 or region_h <= 0:
            continue
        rotation = int(element.rotation_deg) % 360
        if element.kind == "qr":
            side = min(region_w, region_h)
            qr = qr_image.convert("RGB").resize((side, side), Image.Resampling.NEAREST)
            if rotation:
                qr = qr.rotate(-rotation, expand=True, resample=Image.Resampling.NEAREST)
            label.paste(qr, (x + (region_w - side) // 2, y + (region_h - side) // 2))
            continue
        value = element_text(element, record)
        horizontal_padding = mm_to_px(0.4 if element.source == "uas_code" else 0.2, dpi)
        text_width = max(1, region_w - horizontal_padding * 2)
        fit_width, fit_height = (region_h, text_width) if rotation in (90, 270) else (text_width, region_h)
        mask = fitted_text_mask(
            draw,
            value,
            fit_width,
            fit_height,
            mm_to_px(max(1.8, element.font_size_mm), dpi),
            condensed=element.source in {"aircraft_serial", "uas_code"},
            allow_upscale=False,
        )
        if rotation:
            mask = mask.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
        if element.align == "left":
            text_x = x + horizontal_padding
        elif element.align == "right":
            text_x = x + region_w - horizontal_padding - mask.width
        else:
            text_x = x + (region_w - mask.width) // 2
        text_y = y + (region_h - mask.height) // 2
        ink = Image.new("RGB", mask.size, "black")
        label.paste(ink, (text_x, text_y), mask)
    return set_physical_metadata(label, layout.paper_width_mm, layout.paper_height_mm, dpi)


def render_qr_label(
    qr_image: Image.Image,
    record: UomRecord,
    dpi: int = 600,
    layout: LayoutTemplate | None = None,
) -> Image.Image:
    if layout is not None:
        return render_custom_layout(qr_image, record, layout, "qr", dpi)
    width = mm_to_px(LABEL_WIDTH_MM, dpi)
    height = mm_to_px(LABEL_HEIGHT_MM, dpi)
    label = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(label)

    qr_size = mm_to_px(27.0, dpi)
    gap = mm_to_px(0.4, dpi)
    left_margin = (width - qr_size * 2 - gap) // 2
    top = mm_to_px(2.5, dpi)
    qr = qr_image.convert("RGB").resize((qr_size, qr_size), Image.Resampling.NEAREST)
    qr_positions = (left_margin, left_margin + qr_size + gap)
    for x in qr_positions:
        label.paste(qr, (x, top))

    uas_font = fit_font(draw, record.uas_code, qr_size, mm_to_px(2.55, dpi))
    uas_box = draw.textbbox((0, 0), record.uas_code, font=uas_font)
    uas_width = uas_box[2] - uas_box[0]
    uas_top = top + qr_size - mm_to_px(0.45, dpi)
    uas_y = uas_top - uas_box[1]
    for x in qr_positions:
        draw.text((x + (qr_size - uas_width) // 2, uas_y), record.uas_code, fill="black", font=uas_font)

    return set_physical_metadata(label, LABEL_WIDTH_MM, LABEL_HEIGHT_MM, dpi)


def render_info_label(
    qr_image: Image.Image,
    record: UomRecord,
    dpi: int = 600,
    layout: LayoutTemplate | None = None,
) -> Image.Image:
    if layout is not None:
        return render_custom_layout(qr_image, record, layout, "info", dpi)
    width = mm_to_px(LABEL_WIDTH_MM, dpi)
    height = mm_to_px(LABEL_HEIGHT_MM, dpi)
    label = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(label)

    left_width = mm_to_px(27.5, dpi)
    qr_size = mm_to_px(22.5, dpi)
    qr_x = (left_width - qr_size) // 2
    # The middle block is a strict left/right grid: QR on the left and the
    # four short values on the right. The long serial owns a separate,
    # full-width bottom row.
    qr_y = mm_to_px(2.8, dpi)
    qr = qr_image.convert("RGB").resize((qr_size, qr_size), Image.Resampling.NEAREST)
    label.paste(qr, (qr_x, qr_y))
    dark_mask = qr.convert("L").point(lambda value: 255 if value < 150 else 0)
    dark_box = dark_mask.getbbox()
    visible_qr_top = qr_y + (dark_box[1] if dark_box else 0)

    uas_font = fit_font(draw, record.uas_code, left_width - mm_to_px(2.0, dpi), mm_to_px(2.35, dpi), mm_to_px(1.8, dpi))
    uas_box = draw.textbbox((0, 0), record.uas_code, font=uas_font)
    uas_width = uas_box[2] - uas_box[0]
    uas_top = qr_y + qr_size + mm_to_px(0.25, dpi)
    draw.text(((left_width - uas_width) // 2, uas_top - uas_box[1]), record.uas_code, fill="black", font=uas_font)
    left_block_bottom = uas_top + (uas_box[3] - uas_box[1])

    # Keep the four short values in the right column, then give the long
    # aircraft serial its own full-width bottom row. This remains readable at
    # 203dpi without shrinking the QR code or entering the rounded-corner zone.
    info_x = mm_to_px(28.8, dpi)
    # Every right-column value, including exceptionally long model names,
    # must finish before this fixed safe boundary. fitted_text_mask keeps the
    # glyph aspect ratio and proportionally shrinks anything that is longer.
    info_width = width - info_x - mm_to_px(INFO_RIGHT_SAFE_MM, dpi)
    block_top = visible_qr_top
    preferred_sizes = (3.2, 3.05, 2.9, 2.75)
    values = info_label_lines(record)
    upper_values = (values[0], values[1], values[2], values[4])
    upper_span = max(1, left_block_bottom - block_top)
    row_region_height = max(1, upper_span // 4)
    prepared_rows: list[Image.Image] = []
    for index, value in enumerate(upper_values):
        value_mask = fitted_text_mask(
            draw,
            value,
            info_width,
            row_region_height,
            mm_to_px(preferred_sizes[index], dpi),
        )
        prepared_rows.append(value_mask)

    for index, value_mask in enumerate(prepared_rows):
        available_travel = max(0, upper_span - value_mask.height)
        row_y = block_top + round(index * available_travel / 3)
        value_ink = Image.new("RGB", value_mask.size, "black")
        label.paste(value_ink, (info_x, row_y), value_mask)

    # The serial owns a fixed physical region. Different serial lengths scale
    # proportionally to fill that region without overflow or horizontal
    # distortion. Long model/owner values cannot change this geometry.
    serial = values[3]
    upper_left = qr_x + (dark_box[0] if dark_box else 0)
    serial_region_width = mm_to_px(SERIAL_REGION_WIDTH_MM, dpi)
    serial_region_height = mm_to_px(SERIAL_REGION_HEIGHT_MM, dpi)
    serial_mask = fitted_text_mask(
        draw,
        serial,
        serial_region_width,
        serial_region_height,
        mm_to_px(4.0, dpi),
        condensed=True,
        allow_upscale=True,
    )
    remaining = max(0, height - left_block_bottom - serial_mask.height)
    serial_top = left_block_bottom + remaining // 2
    serial_left = upper_left + (serial_region_width - serial_mask.width) // 2
    serial_ink = Image.new("RGB", serial_mask.size, "black")
    label.paste(serial_ink, (serial_left, serial_top), serial_mask)
    return set_physical_metadata(label, LABEL_WIDTH_MM, LABEL_HEIGHT_MM, dpi)


def render_label(qr_image: Image.Image, record: UomRecord, dpi: int = 600) -> Image.Image:
    """Compatibility alias for the primary double-QR template."""
    return render_qr_label(qr_image, record, dpi)


def save_pdf(label: Image.Image, path: Path) -> None:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    points_per_mm = 72.0 / MM_PER_INCH
    paper_width = float(label.info.get("paper_width_mm", LABEL_WIDTH_MM))
    paper_height = float(label.info.get("paper_height_mm", LABEL_HEIGHT_MM))
    page_size = (paper_width * points_per_mm, paper_height * points_per_mm)
    pdf = canvas.Canvas(str(path), pagesize=page_size)
    pdf.drawImage(ImageReader(label), 0, 0, width=page_size[0], height=page_size[1])
    pdf.showPage()
    pdf.save()


def create_preview(label: Image.Image, path: Path) -> None:
    canvas_width, canvas_height = 1500, 1050
    background = Image.new("RGB", (canvas_width, canvas_height), "#edf1f6")
    display_width = 1260
    paper_width = float(label.info.get("paper_width_mm", LABEL_WIDTH_MM))
    paper_height = float(label.info.get("paper_height_mm", LABEL_HEIGHT_MM))
    display_height = round(display_width * paper_height / paper_width)
    if display_height > 900:
        display_height = 900
        display_width = round(display_height * paper_width / paper_height)
    display = label.resize((display_width, display_height), Image.Resampling.LANCZOS)
    radius = round(display_width * 3.0 / max(1.0, paper_width))
    shadow = Image.new("RGBA", (display_width + 80, display_height + 80), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((30, 30, display_width + 30, display_height + 30), radius, fill=(0, 0, 0, 65))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    x, y = (canvas_width - display_width) // 2, 95
    background.paste(shadow, (x - 40, y - 30), shadow)
    mask = Image.new("L", (display_width, display_height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, display_width - 1, display_height - 1), radius, fill=255)
    background.paste(display, (x, y), mask)
    path.parent.mkdir(parents=True, exist_ok=True)
    background.save(path, quality=96)


def save_label_outputs(
    label: Image.Image,
    record: UomRecord,
    source_pdf: Path,
    destination: Path,
    source: str,
    template_name: str = "",
    *,
    compact_filename: bool = False,
) -> ProcessedLabel:
    destination.mkdir(parents=True, exist_ok=True)

    safe_model = safe_path_part(record.model_name, "未知机型")
    safe_serial = safe_path_part(record.aircraft_serial, "未知序列号")
    stem = "标签" if compact_filename else f"{safe_model} {safe_serial}"
    if template_name:
        safe_template = safe_path_part(template_name, "标签")
        stem = safe_template if compact_filename else f"{stem} {safe_template}"
    print_png = destination / f"{stem}.png"
    print_pdf = destination / f"{stem}.pdf"
    preview_stem = f"{safe_model} {safe_serial}"
    if template_name:
        preview_stem = f"{preview_stem} {safe_path_part(template_name, '标签')}"
    preview_png = preview_dir() / f"{preview_stem}.png"
    dpi_info = label.info.get("dpi", (600, 600))
    if isinstance(dpi_info, tuple):
        save_dpi = (round(float(dpi_info[0])), round(float(dpi_info[1])))
    else:
        dpi_value = round(float(dpi_info or 600))
        save_dpi = (dpi_value, dpi_value)
    label.save(print_png, dpi=save_dpi)
    save_pdf(label, print_pdf)
    create_preview(label, preview_png)
    return ProcessedLabel(
        source_pdf,
        print_png,
        print_pdf,
        preview_png,
        record,
        source=source,
        template_name=template_name,
    )


def save_label_set_outputs(
    qr_label: Image.Image,
    info_label: Image.Image,
    record: UomRecord,
    source_pdf: Path,
    destination: Path | None,
    source: str,
    *,
    persist_output: bool = True,
) -> ProcessedLabelSet:
    folder_name = label_output_folder_name(record)
    if persist_output:
        if destination is None:
            raise ValueError("正式保存标签时必须提供输出目录")
        label_dir = destination if destination.name.casefold() == folder_name.casefold() else destination / folder_name
    else:
        label_dir = preview_dir() / "pending" / folder_name
    primary = save_label_outputs(
        qr_label, record, source_pdf, label_dir, source, "实名双码", compact_filename=True
    )
    info = save_label_outputs(
        info_label, record, source_pdf, label_dir, source, "设备信息", compact_filename=True
    )
    return ProcessedLabelSet(primary, info)


def persist_label_set_outputs(labels: ProcessedLabelSet, destination: Path) -> ProcessedLabelSet:
    """Copy cached full-resolution label files into the user output folder."""
    folder_name = label_output_folder_name(labels.record)
    label_dir = destination if destination.name.casefold() == folder_name.casefold() else destination / folder_name
    label_dir.mkdir(parents=True, exist_ok=True)
    for label in (labels.qr_label, labels.info_label):
        stem = safe_path_part(label.template_name, "标签")
        target_png = label_dir / f"{stem}.png"
        target_pdf = label_dir / f"{stem}.pdf"
        if label.print_png.absolute() != target_png.absolute():
            shutil.copy2(label.print_png, target_png)
        if label.print_pdf.absolute() != target_pdf.absolute():
            shutil.copy2(label.print_pdf, target_pdf)
        label.print_png = target_png
        label.print_pdf = target_pdf
    return labels
