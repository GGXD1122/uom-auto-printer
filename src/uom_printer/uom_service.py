from __future__ import annotations

import json
import re
import urllib.request
import urllib.parse
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path

import qrcode
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from qrcode.constants import ERROR_CORRECT_H

from .models import UomRecord
from .paths import resource_path


UOM_ID_PATTERN = re.compile(r"/uav-regist-show/([0-9a-fA-F-]{36})")
UOM_QR_BORDER_MODULES = 9


class UomProcessingError(RuntimeError):
    pass


def is_complete_phone_number(value: object) -> bool:
    """Return true only for a usable, unmasked phone number."""
    raw = str(value or "").strip()
    if not raw or any(marker in raw for marker in ("*", "＊", "•")):
        return False
    digits = re.sub(r"\D", "", raw)
    return len(digits) >= 7


def format_weight(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        kilograms = Decimal(raw)
    except InvalidOperation:
        return raw
    if kilograms <= 0:
        return ""
    if kilograms < 1:
        grams = (kilograms * 1000).quantize(Decimal("1"))
        return f"{grams} g"
    normalized = format(kilograms.normalize(), "f")
    return f"{normalized} kg"


def format_registration_status(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw == "0":
        return "有效登记"
    if any("\u4e00" <= character <= "\u9fff" for character in raw):
        return raw
    return f"未知状态（{raw}）"


def record_from_uom_row(row: dict) -> UomRecord:
    """Convert the allow-listed fields returned by the authenticated UOM list."""
    owner_type = str(row.get("suoyqrlx") or "").strip()
    owner_name = str((row.get("danwmc") if owner_type == "1" else row.get("xingm")) or "").strip()
    if not owner_name:
        owner_name = str(row.get("xingm") or row.get("danwmc") or "").strip()
    record = UomRecord(
        uas_code=str(row.get("uasCode") or "").strip(),
        model_name=str(row.get("chanpmc") or row.get("chanpxh") or "").strip(),
        aircraft_serial=str(row.get("chanpxlh") or "").strip(),
        owner_name=owner_name,
        phone_number=str(row.get("shoujhm") or row.get("mobile") or "").strip(),
        empty_weight=format_weight(row.get("kongjzl")),
        product_model=str(row.get("chanpxh") or "").strip(),
        manufacturer=str(row.get("shengccsmc") or "").strip(),
        status=format_registration_status(row.get("zhuangt")),
        maximum_takeoff_weight=format_weight(row.get("zuidqfzl")),
        registration_time=str(row.get("createTime") or "").strip(),
        owner_type=("单位" if owner_type == "1" else "个人" if owner_type else ""),
        qr_payload=str(row.get("erwm") or "").strip(),
        raw={key: row.get(key) for key in (
            "id", "uasCode", "chanpxlh", "chanpmc", "chanpxh", "shengccsmc",
            "xingm", "danwmc", "suoyqrlx", "shoujhm", "kongjzl", "zuidqfzl",
            "createTime", "zhuangt", "erwm",
        )},
    )
    missing = [
        name
        for name, value in (
            ("二维码内容", record.qr_payload),
            ("实名登记标识", record.uas_code),
            ("机型", record.model_name),
            ("飞行器序列号", record.aircraft_serial),
            ("所有人", record.owner_name),
        )
        if not value
    ]
    if missing:
        raise UomProcessingError("UOM登记记录缺少：" + "、".join(missing))
    return record


def qr_image_from_payload(payload: str) -> Image.Image:
    if not payload.strip():
        raise UomProcessingError("二维码内容为空")
    generator = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=12,
        # The official PDF includes a visibly wider quiet zone than qrcode's
        # four-module default. Match that geometry so labels generated from
        # the authenticated UOM list have the same QR footprint as PDF imports.
        border=UOM_QR_BORDER_MODULES,
    )
    generator.add_data(payload)
    generator.make(fit=True)
    image = generator.make_image(fill_color="black", back_color="white").convert("RGB")
    logo_path = resource_path("assets/uom-qr-logo.png")
    if logo_path.exists():
        logo_size = max(24, round(image.width * 0.22))
        logo = Image.open(logo_path).convert("RGB").resize(
            (logo_size, logo_size), Image.Resampling.LANCZOS
        )
        left = (image.width - logo_size) // 2
        top = (image.height - logo_size) // 2
        image.paste(logo, (left, top))
    return image


def decode_qr_image(image: Image.Image) -> str:
    import zxingcpp

    source = ImageOps.exif_transpose(image).convert("RGB")
    longest = max(source.size)
    if longest > 4200:
        ratio = 4200 / longest
        source = source.resize(
            (max(1, round(source.width * ratio)), max(1, round(source.height * ratio))),
            Image.Resampling.LANCZOS,
        )

    candidates: list[Image.Image] = [source]
    gray = ImageOps.grayscale(source)
    candidates.append(ImageOps.autocontrast(gray, cutoff=1))
    candidates.append(
        ImageEnhance.Contrast(source.filter(ImageFilter.UnsharpMask(radius=1.4, percent=170, threshold=2))).enhance(1.35)
    )
    for threshold in (105, 135, 165, 195):
        candidates.append(gray.point(lambda value, limit=threshold: 255 if value >= limit else 0))

    if max(source.size) < 1800:
        scale = min(3.0, 2200 / max(source.size))
        if scale > 1.15:
            candidates.append(
                source.resize(
                    (round(source.width * scale), round(source.height * scale)),
                    Image.Resampling.LANCZOS,
                )
            )

    binarizers = (
        zxingcpp.Binarizer.LocalAverage,
        zxingcpp.Binarizer.GlobalHistogram,
    )
    for candidate in candidates:
        for binarizer in binarizers:
            result = zxingcpp.read_barcode(
                candidate,
                formats=zxingcpp.BarcodeFormat.QRCode,
                try_rotate=True,
                try_downscale=True,
                binarizer=binarizer,
            )
            if result and result.text:
                return result.text

    # Phone photos often leave the code small inside a large frame. Scan four
    # overlapping tiles at native detail before giving up.
    if source.width >= 1400 or source.height >= 1400:
        overlap_x = round(source.width * 0.16)
        overlap_y = round(source.height * 0.16)
        mid_x = source.width // 2
        mid_y = source.height // 2
        boxes = (
            (0, 0, min(source.width, mid_x + overlap_x), min(source.height, mid_y + overlap_y)),
            (max(0, mid_x - overlap_x), 0, source.width, min(source.height, mid_y + overlap_y)),
            (0, max(0, mid_y - overlap_y), min(source.width, mid_x + overlap_x), source.height),
            (max(0, mid_x - overlap_x), max(0, mid_y - overlap_y), source.width, source.height),
        )
        for box in boxes:
            tile = ImageOps.autocontrast(ImageOps.grayscale(source.crop(box)), cutoff=1)
            result = zxingcpp.read_barcode(
                tile,
                formats=zxingcpp.BarcodeFormat.QRCode,
                try_rotate=True,
                try_downscale=False,
                binarizer=zxingcpp.Binarizer.LocalAverage,
            )
            if result and result.text:
                return result.text
    raise UomProcessingError(
        "未能识别二维码：二维码可能不清晰、被遮挡、严重变形或反光，请重新拍摄或导出清晰原图"
    )


def extract_qr_from_pdf(pdf_path: Path) -> tuple[Image.Image, str]:
    import fitz
    import zxingcpp

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise UomProcessingError(f"PDF无法打开：{exc}") from exc

    with document:
        for page in document:
            for image_info in page.get_images(full=True):
                try:
                    data = document.extract_image(image_info[0])
                    image = Image.open(BytesIO(data["image"])).convert("RGB")
                    return image, decode_qr_image(image)
                except (UomProcessingError, OSError, KeyError):
                    continue

        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page_image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            result = zxingcpp.read_barcode(page_image, formats=zxingcpp.BarcodeFormat.QRCode)
            if result and result.text:
                position = result.position
                corners = (position.top_left, position.top_right, position.bottom_right, position.bottom_left)
                x_values = [point.x for point in corners]
                y_values = [point.y for point in corners]
                x1, x2 = min(x_values), max(x_values)
                y1, y2 = min(y_values), max(y_values)
                pad = max(x2 - x1, y2 - y1) // 10
                qr = page_image.crop(
                    (max(0, x1 - pad), max(0, y1 - pad), min(page_image.width, x2 + pad), min(page_image.height, y2 + pad))
                )
                return qr, result.text

    raise UomProcessingError(
        "PDF中未找到可识别的二维码：二维码可能不清晰、被遮挡、严重变形或页面内容已损坏"
    )


def extract_uom_payload_from_file(file_path: Path) -> str:
    """Decode an existing UOM registration QR from a PDF or image file."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise UomProcessingError("实名码文件不存在")

    if path.suffix.lower() == ".pdf":
        _image, payload = extract_qr_from_pdf(path)
    else:
        try:
            with Image.open(path) as source:
                payload = decode_qr_image(source.convert("RGB"))
        except UomProcessingError:
            raise
        except Exception as exc:
            raise UomProcessingError(f"实名码图片无法打开：{exc}") from exc

    if not UOM_ID_PATTERN.search(payload):
        raise UomProcessingError("不支持的二维码：识别到的内容不是UOM实名登记码")
    return payload


def fetch_uom_record(payload: str, timeout: int = 15) -> UomRecord:
    match = UOM_ID_PATTERN.search(payload)
    if not match:
        raise UomProcessingError("二维码内容不是UOM实名登记链接")
    api_url = f"https://uom.caac.gov.cn/api/home/anon/uavRegistShow/new/{match.group(1)}"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 "
                "Chrome/126.0 Mobile Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except Exception as exc:
        raise UomProcessingError(f"UOM数据接口请求失败：{exc}") from exc

    raw = data.get("uomUavRegist") or {}
    if data.get("code") != 0 or not raw:
        raise UomProcessingError(data.get("msg") or "UOM接口未返回登记数据")

    normalized = dict(raw)
    normalized["erwm"] = payload
    return record_from_uom_row(normalized)


def fetch_uom_record_by_serial(serial: str, timeout: int = 15) -> UomRecord:
    """Query the official public serial-number endpoint.

    The public endpoint intentionally masks phone numbers.  Callers may replace
    that value only when the same aircraft is found in the current authenticated
    account and its QR UUID detail is available.
    """
    normalized_serial = str(serial or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", normalized_serial):
        raise UomProcessingError("请输入正确的飞行器序列号")
    encoded = urllib.parse.quote(normalized_serial, safe="")
    api_url = f"https://uom.caac.gov.cn/api/home/anon/uavRegistShow/sn/{encoded}"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 "
                "Chrome/126.0 Mobile Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except Exception as exc:
        raise UomProcessingError(f"UOM序列号查询失败：{exc}") from exc

    raw = data.get("uomUavRegist") or {}
    if data.get("code") != 0 or not raw or not raw.get("uasCode"):
        raise UomProcessingError(data.get("msg") or "未查询到该序列号的实名登记信息")
    registration_id = str(raw.get("id") or "").strip()
    qr_payload = ""
    if re.fullmatch(r"[0-9a-fA-F-]{36}", registration_id):
        # The public endpoint returns the official registration UUID but not
        # the QR URL. Rebuild that same UOM URL so a successful lookup can use
        # the normal label rendering and printing path.
        qr_payload = f"https://uom.caac.gov.cn/#/uav-regist-show/{registration_id}"
    return UomRecord(
        uas_code=str(raw.get("uasCode") or "").strip(),
        model_name=str(raw.get("chanpmc") or raw.get("chanpxh") or "").strip(),
        aircraft_serial=str(raw.get("chanpxlh") or normalized_serial).strip(),
        owner_name=str(raw.get("xingm") or raw.get("danwmc") or "").strip(),
        phone_number=str(raw.get("shoujhm") or raw.get("mobile") or "").strip(),
        empty_weight=format_weight(raw.get("kongjzl")),
        product_model=str(raw.get("chanpxh") or "").strip(),
        manufacturer=str(raw.get("shengccsmc") or "").strip(),
        status=format_registration_status(raw.get("zhuangt")),
        maximum_takeoff_weight=format_weight(raw.get("zuidqfzl")),
        registration_time=str(raw.get("createTime") or "").strip(),
        owner_type=("单位" if str(raw.get("suoyqrlx") or "").strip() == "1" else "个人" if raw.get("suoyqrlx") is not None else ""),
        qr_payload=qr_payload,
        raw=dict(raw),
    )
