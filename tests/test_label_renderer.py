import qrcode
import zxingcpp
from PIL import Image
from pathlib import Path

from uom_printer.label_renderer import (
    mm_to_px,
    info_label_lines,
    render_info_label,
    render_label,
    render_qr_label,
    persist_label_set_outputs,
    save_label_outputs,
    save_label_set_outputs,
)
from uom_printer.models import UomRecord
from uom_printer.uom_service import qr_image_from_payload


PAYLOAD = "https://uom.caac.gov.cn/#/uav-regist-show/00000000-0000-4000-8000-000000000001"


def make_qr() -> Image.Image:
    return qrcode.make(PAYLOAD).convert("RGB")


def test_label_keeps_physical_ratio_and_long_model() -> None:
    record = UomRecord(
        uas_code="UAS-DEMO-0001",
        model_name="DJI Mavic 3 Pro Cine Premium Combo",
        aircraft_serial="1581FDEMO00000000002",
        owner_name="演示用户",
    )
    label = render_label(make_qr(), record, dpi=300)
    assert label.size == (mm_to_px(60, 300), mm_to_px(40, 300))


def test_both_templates_keep_sixty_by_forty_size() -> None:
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Mavic 3 Pro Cine Premium Combo",
        "1581FDEMO00000000002",
        "演示用户",
        phone_number="13800000000",
        empty_weight="895 g",
    )
    expected = (mm_to_px(60, 300), mm_to_px(40, 300))
    assert render_qr_label(make_qr(), record, dpi=300).size == expected
    assert render_info_label(make_qr(), record, dpi=300).size == expected


def test_info_template_uses_large_value_lines_without_small_captions() -> None:
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Avata 360",
        "1581FDEMO00000000003",
        "演示用户",
        phone_number="13800000000",
        empty_weight="455 g",
    )
    assert info_label_lines(record) == (
        "演示用户",
        "13800000000",
        "DJI Avata 360",
        "1581FDEMO00000000003",
        "空机重量 455 g",
    )


def test_both_qr_codes_decode_at_203_dpi() -> None:
    record = UomRecord("UAS-DEMO-0001", "DJI Matrice 350 RTK", "1581FDEMO00000000002", "演示用户")
    label = render_label(make_qr(), record, dpi=600).resize((480, 320), Image.Resampling.LANCZOS)
    for crop in (label.crop((0, 0, 240, 320)), label.crop((240, 0, 480, 320))):
        result = zxingcpp.read_barcode(crop, formats=zxingcpp.BarcodeFormat.QRCode)
        assert result is not None
        assert result.text == PAYLOAD


def test_uom_generated_qr_decodes_at_203_dpi() -> None:
    record = UomRecord("UAS-DEMO-0001", "DJI Avata 360", "1581FDEMO00000000002", "演示用户")
    label = render_label(qr_image_from_payload(PAYLOAD), record, dpi=600).resize(
        (480, 320), Image.Resampling.LANCZOS
    )
    for crop in (label.crop((0, 0, 240, 320)), label.crop((240, 0, 480, 320))):
        result = zxingcpp.read_barcode(crop, formats=zxingcpp.BarcodeFormat.QRCode)
        assert result is not None
        assert result.text == PAYLOAD


def test_info_template_qr_decodes_at_203_dpi() -> None:
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Matrice 350 RTK",
        "1581FDEMO00000000002",
        "演示用户",
        phone_number="13800000000",
        empty_weight="6.47 kg",
    )
    label = render_info_label(qr_image_from_payload(PAYLOAD), record, dpi=600).resize(
        (480, 320), Image.Resampling.LANCZOS
    )
    result = zxingcpp.read_barcode(label.crop((0, 0, 220, 320)), formats=zxingcpp.BarcodeFormat.QRCode)
    assert result is not None
    assert result.text == PAYLOAD


def test_info_template_aligns_visible_qr_with_text_and_uses_full_width_bottom_serial() -> None:
    record = UomRecord(
        "UAS-DEMO001",
        "DJI Avata 360",
        "1581FDEMO00000000003",
        "演示用户",
        phone_number="13800000000",
        empty_weight="455 g",
    )
    dpi = 300
    label = render_info_label(qr_image_from_payload(PAYLOAD), record, dpi=dpi)
    mask = label.convert("L").point(lambda value: 255 if value < 150 else 0)
    middle_bottom = mm_to_px(31.0, dpi)
    left_box = mask.crop((0, 0, mm_to_px(27.5, dpi), middle_bottom)).getbbox()
    right_box = mask.crop((mm_to_px(28.8, dpi), 0, label.width, middle_bottom)).getbbox()
    assert left_box is not None and right_box is not None
    assert abs(left_box[1] - right_box[1]) <= 3
    assert abs(left_box[3] - right_box[3]) <= 3

    split_y = mm_to_px(31.0, dpi)
    upper_box = mask.crop((0, 0, label.width, split_y)).getbbox()
    bottom_box = mask.crop((0, split_y, label.width, label.height)).getbbox()
    assert upper_box is not None
    assert bottom_box is not None
    assert abs(bottom_box[0] - upper_box[0]) <= 2
    assert abs(bottom_box[2] - upper_box[2]) <= 2
    serial_top = split_y + bottom_box[1]
    serial_bottom = split_y + bottom_box[3]
    assert abs((serial_top - upper_box[3]) - (label.height - serial_bottom)) <= 2


def test_fixed_serial_region_is_independent_from_long_model_name() -> None:
    serial = "1581FDEMO00000000004"
    common = {
        "uas_code": "UAS-DEMO-0001",
        "aircraft_serial": serial,
        "owner_name": "演示用户",
        "phone_number": "13800000000",
        "empty_weight": "1.063 kg",
    }
    short_model = UomRecord(model_name="DJI Avata 360", **common)
    long_model = UomRecord(model_name="DJI Mavic 4 Pro (64GB)", **common)
    dpi = 600
    split_y = mm_to_px(31.0, dpi)

    def serial_box(record: UomRecord) -> tuple[int, int, int, int]:
        label = render_info_label(qr_image_from_payload(PAYLOAD), record, dpi=dpi)
        mask = label.convert("L").point(lambda value: 255 if value < 150 else 0)
        box = mask.crop((0, split_y, label.width, label.height)).getbbox()
        assert box is not None
        return box

    short_box = serial_box(short_model)
    long_box = serial_box(long_model)
    short_width = short_box[2] - short_box[0]
    long_width = long_box[2] - long_box[0]

    assert abs(long_width - short_width) <= 2
    assert long_width <= mm_to_px(42.2, dpi) + 2


def test_long_owner_name_stays_inside_fixed_right_column() -> None:
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Mavic 4 Pro (64GB)",
        "1581FDEMO00000000004",
        "演示飞行器设备服务有限公司",
        phone_number="13800000000",
        empty_weight="1.063 kg",
    )
    dpi = 600
    label = render_info_label(qr_image_from_payload(PAYLOAD), record, dpi=dpi)
    mask = label.convert("L").point(lambda value: 255 if value < 150 else 0)
    info_x = mm_to_px(28.8, dpi)
    right_edge = label.width - mm_to_px(2.0, dpi)
    first_row_bottom = mm_to_px(8.0, dpi)
    name_box = mask.crop((info_x, 0, right_edge, first_row_bottom)).getbbox()

    assert name_box is not None
    assert name_box[2] <= right_edge - info_x


def test_extremely_long_model_stays_inside_right_safe_boundary() -> None:
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Mavic 4 Pro Fly More Combo Creator Edition (512GB) Ultra Long Model Name",
        "1581FDEMO00000000004",
        "演示用户",
        phone_number="13800000000",
        empty_weight="1.063 kg",
    )
    dpi = 600
    label = render_info_label(qr_image_from_payload(PAYLOAD), record, dpi=dpi)
    mask = label.convert("L").point(lambda value: 255 if value < 150 else 0)
    content_box = mask.getbbox()

    assert content_box is not None
    assert content_box[2] <= label.width - mm_to_px(4.0, dpi)


def test_output_filename_only_uses_model_and_serial(tmp_path: Path, monkeypatch) -> None:
    preview_folder = tmp_path / "app-data" / "previews"
    preview_folder.mkdir(parents=True)
    monkeypatch.setattr("uom_printer.label_renderer.preview_dir", lambda: preview_folder)
    record = UomRecord("UAS-DEMO-0001", "DJI Avata 360", "1581FDEMO00000000003", "演示用户")
    label = render_label(make_qr(), record, dpi=300)
    result = save_label_outputs(label, record, tmp_path / "source.pdf", tmp_path, "manual")
    assert result.print_png.name == "DJI Avata 360 1581FDEMO00000000003.png"
    assert result.print_pdf.name == "DJI Avata 360 1581FDEMO00000000003.pdf"
    assert result.preview_png.name == "DJI Avata 360 1581FDEMO00000000003.png"
    assert result.preview_png.parent != tmp_path


def test_label_set_outputs_use_distinct_template_names(tmp_path: Path, monkeypatch) -> None:
    preview_folder = tmp_path / "app-data" / "previews"
    preview_folder.mkdir(parents=True)
    monkeypatch.setattr("uom_printer.label_renderer.preview_dir", lambda: preview_folder)
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Avata 360",
        "1581FDEMO00000000003",
        "演示用户",
        phone_number="13800000000",
        empty_weight="125 g",
    )
    qr = make_qr()
    result = save_label_set_outputs(
        render_qr_label(qr, record, dpi=300),
        render_info_label(qr, record, dpi=300),
        record,
        tmp_path / "source.pdf",
        tmp_path,
        "manual",
    )
    assert result.qr_label.print_png.name.endswith("实名双码.png")
    assert result.info_label.print_png.name.endswith("设备信息.png")
    assert result.qr_label.print_png != result.info_label.print_png
    assert result.qr_label.print_png.name == "实名双码.png"
    assert result.info_label.print_png.name == "设备信息.png"
    assert result.qr_label.print_png.parent.name == (
        "演示用户_13800000000_DJI Avata 360_1581FDEMO00000000003"
    )
    assert result.qr_label.print_png.parent.parent == tmp_path


def test_preview_only_labels_stay_in_cache_until_print_persists_them(tmp_path: Path, monkeypatch) -> None:
    preview_folder = tmp_path / "app-data" / "previews"
    output_folder = tmp_path / "user-output"
    monkeypatch.setattr("uom_printer.label_renderer.preview_dir", lambda: preview_folder)
    record = UomRecord(
        "UAS-DEMO-0001",
        "DJI Avata 360",
        "1581FDEMO00000000003",
        "演示用户",
        phone_number="13800000000",
    )
    qr = make_qr()
    result = save_label_set_outputs(
        render_qr_label(qr, record, dpi=300),
        render_info_label(qr, record, dpi=300),
        record,
        tmp_path / "source.pdf",
        None,
        "manual",
        persist_output=False,
    )

    assert not output_folder.exists()
    assert "pending" in result.qr_label.print_png.parts
    assert result.qr_label.print_png.is_file()
    assert result.info_label.print_pdf.is_file()

    persist_label_set_outputs(result, output_folder)

    assert result.qr_label.print_png.parent.parent == output_folder
    assert result.qr_label.print_png.name == "实名双码.png"
    assert result.info_label.print_pdf.name == "设备信息.pdf"
    assert result.qr_label.print_png.is_file()
    assert result.info_label.print_pdf.is_file()
