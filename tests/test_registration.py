from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from PIL import Image

from uom_printer.registration import (
    MAX_REGISTRATION_PHOTO_BYTES,
    RegistrationValidationError,
    build_personal_registration_form,
    prepare_registration_photo,
)


def _owner() -> dict:
    return {
        "xingm": "演示用户",
        "zhengjlx": "0",
        "zhengjhm": "DEMO-CERT",
        "shoujhm": "DEMO-PHONE",
        "dianzyx": "demo@example.invalid",
        "uid": "demo-uid",
        "eid": "demo-eid",
    }


def _model() -> dict:
    return {
        "id": "demo-model-id",
        "auditUser": "internal-auditor",
        "createUser": "internal-creator",
        "dataState": "0",
        "createTime": "2026-01-01 00:00:00",
        "params": {"private": "metadata"},
        "shengccsmc": "演示厂商",
        "shengccsid": "demo-company-id",
        "chanpxh": "DEMO-MODEL",
        "chanpmc": "演示无人机",
        "chanplb": "1",
        "chanplx": "1",
        "kongjzl": "0.455",
        "zuidqfzl": "0.468",
        "chanpyt": '["01","02"]',
        "tongxfs": '["2","1"]',
        "bianmfs": '["1"]',
        "feixzg": "500",
    }


def test_prepare_registration_photo_rebuilds_a_standard_jpeg() -> None:
    source = io.BytesIO()
    Image.new("RGBA", (1600, 1000), (20, 160, 80, 180)).save(source, format="PNG")

    prepared = prepare_registration_photo(source.getvalue(), filename="演示正面.png")

    assert prepared.filename == "演示正面.jpg"
    assert prepared.data.startswith(b"\xff\xd8\xff")
    assert len(prepared.data) <= MAX_REGISTRATION_PHOTO_BYTES
    assert (prepared.width, prepared.height) == (1600, 1000)
    assert prepared.base64_data


def test_prepare_registration_photo_rejects_an_unreadable_small_image() -> None:
    source = io.BytesIO()
    Image.new("RGB", (200, 180), "white").save(source, format="JPEG")

    with pytest.raises(RegistrationValidationError, match="分辨率太低"):
        prepare_registration_photo(source.getvalue())


def test_build_registration_form_copies_official_model_without_reusing_model_id() -> None:
    form = build_personal_registration_form(
        _owner(),
        _model(),
        serial="DEMO-SERIAL-0001",
        production_date=date.today(),
        front_photo_quote="DEMO-FRONT",
        serial_photo_quote="DEMO-SERIAL-PHOTO",
    )

    assert form["id"] is None
    assert form["chanpxhid"] == "demo-model-id"
    assert form["shengccsid"] == "demo-company-id"
    assert form["numberType"] == "1"
    assert form["chanpsbm"] == ""
    assert form["shiyyt"] == ["01", "02"]
    assert form["tongxfs"] == ["1", "2"]
    assert form["feixzg"] == "500"
    assert "createTime" not in form
    assert "auditUser" not in form
    assert "createUser" not in form
    assert "params" not in form
    assert "chanpyt" not in form


def test_build_registration_form_never_guesses_an_unsupported_purpose() -> None:
    model = _model()
    model["chanpyt"] = '["02"]'

    with pytest.raises(RegistrationValidationError, match="人工核对用途"):
        build_personal_registration_form(
            _owner(),
            model,
            serial="DEMO-SERIAL-0001",
            production_date=date.today(),
            front_photo_quote="DEMO-FRONT",
            serial_photo_quote="DEMO-SERIAL-PHOTO",
        )


def test_registration_form_rejects_future_production_date() -> None:
    with pytest.raises(RegistrationValidationError, match="不能晚于今天"):
        build_personal_registration_form(
            _owner(),
            _model(),
            serial="DEMO-SERIAL-0001",
            production_date=date.today() + timedelta(days=1),
            front_photo_quote="DEMO-FRONT",
            serial_photo_quote="DEMO-SERIAL-PHOTO",
        )
