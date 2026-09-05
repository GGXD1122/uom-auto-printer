import zxingcpp
import io
import json
from PIL import Image, ImageEnhance, ImageFilter

from uom_printer.uom_service import (
    UomProcessingError,
    decode_qr_image,
    extract_uom_payload_from_file,
    fetch_uom_record_by_serial,
    format_registration_status,
    format_weight,
    is_complete_phone_number,
    qr_image_from_payload,
    record_from_uom_row,
)


PAYLOAD = "https://uom.caac.gov.cn/#/uav-regist-show/00000000-0000-4000-8000-000000000001"


def test_authenticated_uom_row_maps_to_label_record() -> None:
    record = record_from_uom_row(
        {
            "id": "row-id",
            "uasCode": "UAS-DEMO-0001",
            "chanpxlh": "1581FDEMO00000000003",
            "chanpmc": "DJI Avata 360",
            "chanpxh": "DVN3NT",
            "shengccsmc": "深圳市大疆创新科技有限公司",
            "xingm": "演示用户",
            "shoujhm": "13800000000",
            "kongjzl": "0.125",
            "zuidqfzl": "1.4",
            "createTime": "2026-07-24 20:30:00",
            "suoyqrlx": "0",
            "zhuangt": "正常",
            "erwm": PAYLOAD,
        }
    )
    assert record.model_name == "DJI Avata 360"
    assert record.aircraft_serial == "1581FDEMO00000000003"
    assert record.owner_name == "演示用户"
    assert record.phone_number == "13800000000"
    assert record.empty_weight == "125 g"
    assert record.maximum_takeoff_weight == "1.4 kg"
    assert record.registration_time == "2026-07-24 20:30:00"
    assert record.owner_type == "个人"
    assert record.qr_payload == PAYLOAD


def test_generated_high_redundancy_qr_decodes() -> None:
    image = qr_image_from_payload(PAYLOAD)
    result = zxingcpp.read_barcode(image, formats=zxingcpp.BarcodeFormat.QRCode)
    assert result is not None
    assert result.text == PAYLOAD

    dark = image.convert("L").point(lambda value: 255 if value < 100 else 0)
    dark_box = dark.getbbox()
    assert dark_box is not None
    dark_ratio = (dark_box[2] - dark_box[0]) / image.width
    # UOM's PDF QR occupies roughly 72% of its square; keeping the generated
    # path in this range prevents it from printing larger than PDF imports.
    assert 0.70 <= dark_ratio <= 0.75


def test_existing_registration_qr_image_decodes_for_lookup(tmp_path) -> None:
    image_path = tmp_path / "registration-code.png"
    qr_image_from_payload(PAYLOAD).save(image_path)
    assert extract_uom_payload_from_file(image_path) == PAYLOAD


def test_phone_photo_registration_qr_decodes_with_rotation_blur_and_low_contrast() -> None:
    qr = qr_image_from_payload(PAYLOAD).resize((460, 460), Image.Resampling.LANCZOS)
    photographed = qr.rotate(
        11,
        expand=True,
        fillcolor=(238, 236, 230),
        resample=Image.Resampling.BICUBIC,
    )
    canvas = Image.new("RGB", (1800, 1300), (210, 207, 198))
    canvas.paste(photographed, (1130, 640))
    canvas = ImageEnhance.Contrast(canvas).enhance(0.72).filter(ImageFilter.GaussianBlur(0.65))
    assert decode_qr_image(canvas) == PAYLOAD


def test_non_uom_qr_is_rejected_for_registration_lookup(tmp_path) -> None:
    import qrcode

    image_path = tmp_path / "ordinary-code.png"
    qrcode.make("https://example.com/not-uom").save(image_path)
    try:
        extract_uom_payload_from_file(image_path)
    except UomProcessingError as exc:
        assert "不支持的二维码" in str(exc)
        assert "不是UOM实名登记码" in str(exc)
    else:
        raise AssertionError("ordinary QR code should be rejected")


def test_unreadable_or_occluded_qr_has_clear_recovery_hint(tmp_path) -> None:
    image_path = tmp_path / "unreadable-code.png"
    Image.new("RGB", (900, 900), "white").save(image_path)
    try:
        extract_uom_payload_from_file(image_path)
    except UomProcessingError as exc:
        message = str(exc)
        assert "不清晰" in message
        assert "被遮挡" in message
    else:
        raise AssertionError("unreadable QR image should be rejected")


def test_weight_formats_uom_kilograms() -> None:
    assert format_weight("0.135") == "135 g"
    assert format_weight("1.063") == "1.063 kg"
    assert format_weight("") == ""


def test_registration_status_is_human_readable() -> None:
    assert format_registration_status("0") == "有效登记"
    assert format_registration_status("正常") == "正常"
    assert format_registration_status("9") == "未知状态（9）"


def test_masked_phone_number_requires_detail_lookup() -> None:
    assert not is_complete_phone_number("138****0000")
    assert not is_complete_phone_number("")
    assert is_complete_phone_number("13800000000")


def test_public_serial_lookup_keeps_official_masked_phone(monkeypatch) -> None:
    payload = {
        "code": 0,
        "msg": "操作成功",
        "uomUavRegist": {
            "id": "00000000-0000-0000-0000-000000000001",
            "uasCode": "UAS-DEMO-0001",
            "chanpmc": "DJI Avata 360",
            "chanpxh": "DVN3NT",
            "chanpxlh": "1581FDEMO00000000003",
            "shengccsmc": "深圳市大疆创新科技有限公司",
            "xingm": "演示用户",
            "shoujhm": "138****0000",
            "kongjzl": "0.455",
            "zhuangt": "正常",
        },
    }

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(
        "uom_printer.uom_service.urllib.request.urlopen",
        lambda _request, timeout=15: Response(json.dumps(payload).encode("utf-8")),
    )
    record = fetch_uom_record_by_serial("1581FDEMO00000000003")
    assert record.phone_number == "138****0000"
    assert record.empty_weight == "455 g"
    assert record.model_name == "DJI Avata 360"
    assert record.qr_payload == (
        "https://uom.caac.gov.cn/#/uav-regist-show/"
        "00000000-0000-0000-0000-000000000001"
    )
