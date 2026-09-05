from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
except ImportError:  # pragma: no cover - the packaged application includes pillow-heif
    register_heif_opener = None


MAX_REGISTRATION_PHOTO_BYTES = 3 * 1024 * 1024
MIN_REGISTRATION_PHOTO_EDGE = 320
DEFAULT_REGISTRATION_PURPOSES = ("01", "02")

_MODEL_META_FIELDS = {
    "auditState",
    "auditTime",
    "auditUser",
    "id",
    "createBy",
    "createTime",
    "createUser",
    "updateBy",
    "updateTime",
    "updateUser",
    "deleteFlag",
    "deleted",
    "dataState",
    "extInfo",
    "pagination",
    "limit",
    "offset",
    "pageNum",
    "pageSize",
    "params",
    "remark",
    "resultKey",
    "searchKey",
    "shenqr",
    "shenqsj",
    "sortKey",
    "sortType",
    "tenantName",
    "unitcode",
    "chanpyt",
    "chanpytqtsm",
}
_ARRAY_FIELDS = ("tongxfs", "bianmfs", "caozfs", "fuzsblx", "shiyyt", "dongllx")


class RegistrationValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedRegistrationPhoto:
    data: bytes
    filename: str
    width: int
    height: int

    @property
    def base64_data(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


def _read_source_bytes(source: str | Path | bytes | bytearray) -> tuple[bytes, str]:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), "registration-photo"
    path = Path(source)
    return path.read_bytes(), path.stem or "registration-photo"


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    output = io.BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        subsampling=0 if quality >= 82 else 2,
    )
    return output.getvalue()


def prepare_registration_photo(
    source: str | Path | bytes | bytearray,
    *,
    filename: str | None = None,
    max_bytes: int = MAX_REGISTRATION_PHOTO_BYTES,
    max_dimension: int = 4096,
) -> PreparedRegistrationPhoto:
    """Convert HEIC/PNG/JPEG input into a clear, correctly oriented UOM JPEG."""
    if register_heif_opener is not None:
        register_heif_opener()

    raw, default_stem = _read_source_bytes(source)
    if not raw:
        raise RegistrationValidationError("登记照片文件为空。")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            image = _flatten_to_rgb(ImageOps.exif_transpose(opened))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if register_heif_opener is None:
            raise RegistrationValidationError(
                "无法识别登记照片；HEIC照片需要完整安装HEIC解码组件。"
            ) from exc
        raise RegistrationValidationError("无法识别登记照片，请换一张清晰的原图。") from exc

    if min(image.size) < MIN_REGISTRATION_PHOTO_EDGE:
        raise RegistrationValidationError("登记照片分辨率太低，请使用更清晰的原图。")

    longest = max(image.size)
    if longest > max_dimension:
        scale = max_dimension / longest
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )

    encoded = b""
    for quality in (94, 91, 88, 85, 82, 78, 74, 70, 66, 62, 58):
        encoded = _encode_jpeg(image, quality)
        if len(encoded) <= max_bytes:
            break

    while len(encoded) > max_bytes and min(image.size) > 900:
        image = image.resize(
            (max(1, round(image.width * 0.88)), max(1, round(image.height * 0.88))),
            Image.Resampling.LANCZOS,
        )
        encoded = _encode_jpeg(image, 72)

    if len(encoded) > max_bytes:
        raise RegistrationValidationError("登记照片压缩后仍超过3MB，请裁剪无关背景后重试。")
    if not encoded.startswith(b"\xff\xd8\xff"):
        raise RegistrationValidationError("登记照片转换失败，请换一张原图重试。")

    safe_stem = Path(filename or default_stem).stem.strip().replace("/", "_").replace("\\", "_")
    safe_stem = safe_stem or "registration-photo"
    return PreparedRegistrationPhoto(
        data=encoded,
        filename=f"{safe_stem}.jpg",
        width=image.width,
        height=image.height,
    )


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            value = parsed
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})


def build_personal_registration_form(
    owner: dict[str, Any],
    model_record: dict[str, Any],
    *,
    serial: str,
    production_date: str | date,
    front_photo_quote: str,
    serial_photo_quote: str,
    purposes: tuple[str, ...] | list[str] = DEFAULT_REGISTRATION_PURPOSES,
) -> dict[str, Any]:
    """Build the same brand-aircraft payload produced by the official UOM form."""
    if not isinstance(owner, dict) or not isinstance(model_record, dict):
        raise RegistrationValidationError("实名登记账号或机型数据格式异常。")

    form = {
        key: value
        for key, value in model_record.items()
        if key not in _MODEL_META_FIELDS and not key.startswith("_")
    }
    form["shengccsid"] = str(model_record.get("shengccsid") or "").strip()
    form["chanpxhid"] = str(model_record.get("id") or model_record.get("chanpxhid") or "").strip()
    for key in ("xingm", "zhengjlx", "zhengjhm", "shoujhm", "dianzyx", "uid", "eid"):
        form[key] = owner.get(key, "")

    allowed_purposes = set(_list_value(model_record.get("chanpyt")))
    requested_purposes = _list_value(purposes)
    if allowed_purposes and not set(requested_purposes).issubset(allowed_purposes):
        raise RegistrationValidationError("该UOM机型不允许默认选择“娱乐、航拍”，请人工核对用途。")

    form.update(
        {
            "id": None,
            "uasCode": None,
            "suoyqrlx": "0",
            "wurjzl": "0",
            "numberType": "1",
            "chanpxlh": str(serial or "").strip(),
            "chanpsbm": "",
            "mfgDate": production_date.isoformat()
            if isinstance(production_date, date)
            else str(production_date or "").strip(),
            "tup1": str(front_photo_quote or "").strip(),
            "tup2": str(serial_photo_quote or "").strip(),
            "shiyyt": requested_purposes,
        }
    )
    for key in _ARRAY_FIELDS:
        if key != "shiyyt":
            form[key] = _list_value(form.get(key))
    return validate_personal_registration_form(form)


def validate_personal_registration_form(form: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(form or {})
    required_fields = (
        "xingm",
        "zhengjlx",
        "zhengjhm",
        "shoujhm",
        "dianzyx",
        "uid",
        "eid",
        "shengccsmc",
        "shengccsid",
        "chanpxh",
        "chanpxhid",
        "chanpmc",
        "chanplb",
        "chanplx",
        "kongjzl",
        "zuidqfzl",
        "chanpxlh",
        "mfgDate",
        "tup1",
        "tup2",
    )
    missing = [key for key in required_fields if not str(normalized.get(key) or "").strip()]
    if missing:
        raise RegistrationValidationError("实名登记表单缺少必填字段：" + "、".join(missing))

    serial = str(normalized["chanpxlh"]).strip()
    if any(character.isspace() for character in serial):
        raise RegistrationValidationError("产品序列号不能包含空格。")

    try:
        empty_weight = float(normalized["kongjzl"])
        maximum_weight = float(normalized["zuidqfzl"])
    except (TypeError, ValueError) as exc:
        raise RegistrationValidationError("空机重量和最大起飞重量必须为数字。") from exc
    if empty_weight <= 0 or maximum_weight <= 0:
        raise RegistrationValidationError("空机重量和最大起飞重量必须大于0。")
    if empty_weight > maximum_weight:
        raise RegistrationValidationError("空机重量必须小于等于最大起飞重量。")

    try:
        production_day = date.fromisoformat(str(normalized["mfgDate"]).strip())
    except ValueError as exc:
        raise RegistrationValidationError("产品生产日期格式应为YYYY-MM-DD。") from exc
    if production_day > date.today():
        raise RegistrationValidationError("产品生产日期不能晚于今天。")

    normalized["suoyqrlx"] = "0"
    normalized["wurjzl"] = "0"
    normalized["numberType"] = "1"
    normalized["chanpsbm"] = ""
    normalized["chanpxlh"] = serial
    normalized["mfgDate"] = production_day.isoformat()
    normalized["shiyyt"] = _list_value(normalized.get("shiyyt")) or list(
        DEFAULT_REGISTRATION_PURPOSES
    )
    for key in _ARRAY_FIELDS:
        if key != "shiyyt":
            normalized[key] = _list_value(normalized.get(key))
    return normalized
