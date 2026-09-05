from pathlib import Path

from uom_printer.models import ProcessedLabel, ProcessedLabelSet, UomRecord
from uom_printer.pipeline import ProcessingPipeline
from uom_printer.settings import AppSettings
from uom_printer.uom_service import UomProcessingError


PAYLOAD = "https://uom.caac.gov.cn/#/uav-regist-show/00000000-0000-4000-8000-000000000001"


def test_unsupported_import_format_has_clear_prompt(tmp_path: Path) -> None:
    source = tmp_path / "not-a-registration-code.txt"
    source.write_text("demo", encoding="utf-8")
    try:
        ProcessingPipeline(AppSettings()).process_import(source)
    except UomProcessingError as exc:
        message = str(exc)
        assert "不支持的文件格式" in message
        assert "PDF" in message
        assert "JPG" in message
        assert "PNG" in message
    else:
        raise AssertionError("unsupported import format should be rejected")


def test_submit_print_uses_independent_template_copy_counts(tmp_path: Path, monkeypatch) -> None:
    record = UomRecord("UAS-DEMO-0001", "DJI Test", "SERIAL001", "演示用户")
    qr_path = tmp_path / "qr.png"
    info_path = tmp_path / "info.png"
    qr_label = ProcessedLabel(tmp_path / "source.pdf", qr_path, tmp_path / "qr.pdf", qr_path, record)
    info_label = ProcessedLabel(tmp_path / "source.pdf", info_path, tmp_path / "info.pdf", info_path, record)
    labels = ProcessedLabelSet(qr_label, info_label)
    output_folder = tmp_path / "output"
    settings = AppSettings(
        printer_name="Deli DL-720W",
        qr_label_copies=2,
        info_label_copies=1,
        output_directory=str(output_folder),
    )
    calls: list[tuple[Path, str, int]] = []
    persisted: list[Path] = []

    def persist(current: ProcessedLabelSet, destination: Path) -> ProcessedLabelSet:
        persisted.append(destination)
        return current

    monkeypatch.setattr("uom_printer.pipeline.persist_label_set_outputs", persist)
    monkeypatch.setattr("uom_printer.pipeline.print_label", lambda path, printer, copies: calls.append((path, printer, copies)))

    ProcessingPipeline(settings).submit_print(labels)

    assert persisted == [output_folder]
    assert calls == [
        (qr_path, "Deli DL-720W", 2),
        (info_path, "Deli DL-720W", 1),
    ]


def test_preview_generation_does_not_create_user_output_folder(tmp_path: Path, monkeypatch) -> None:
    output_folder = tmp_path / "user-output"
    record = UomRecord("UAS-DEMO-0001", "DJI Test", "SERIAL001", "演示用户", qr_payload=PAYLOAD)
    preview_path = tmp_path / "app-data" / "preview.png"
    labels = ProcessedLabelSet(
        ProcessedLabel(tmp_path / "source.pdf", preview_path, preview_path.with_suffix(".pdf"), preview_path, record),
        ProcessedLabel(tmp_path / "source.pdf", preview_path, preview_path.with_suffix(".pdf"), preview_path, record),
    )
    captured: list[tuple[object, bool]] = []

    monkeypatch.setattr("uom_printer.pipeline.render_qr_label", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("uom_printer.pipeline.render_info_label", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "uom_printer.pipeline.save_label_set_outputs",
        lambda *_args, **kwargs: captured.append((kwargs.get("destination"), kwargs["persist_output"])) or labels,
    )
    pipeline = ProcessingPipeline(AppSettings(output_directory=str(output_folder)))
    monkeypatch.setattr(pipeline.history, "record_job", lambda *_args, **_kwargs: 1)

    pipeline._render_and_save(object(), record, tmp_path / "source.pdf", "manual")

    assert captured == [(None, False)]
    assert not output_folder.exists()


def test_masked_list_phone_is_replaced_by_full_detail_phone(tmp_path: Path, monkeypatch) -> None:
    row = {
        "uasCode": "UAS-DEMO-0001",
        "chanpxlh": "1581FDEMO00000000003",
        "chanpmc": "DJI Avata 360",
        "xingm": "演示用户",
        "shoujhm": "138****0000",
        "kongjzl": "0.455",
        "erwm": PAYLOAD,
    }
    detail = UomRecord(
        "UAS-DEMO-0001",
        "DJI Avata 360",
        "1581FDEMO00000000003",
        "演示用户",
        phone_number="13800000000",
        empty_weight="455 g",
        qr_payload=PAYLOAD,
    )
    monkeypatch.setattr("uom_printer.pipeline.fetch_uom_record", lambda _payload: detail)
    monkeypatch.setattr("uom_printer.pipeline.qr_image_from_payload", lambda _payload: object())
    monkeypatch.setattr("uom_printer.pipeline.inbox_dir", lambda: tmp_path)
    pipeline = ProcessingPipeline(AppSettings())
    monkeypatch.setattr(pipeline, "_render_and_save", lambda _qr, record, _path, _source: record)

    result = pipeline.process_uom_row(row)

    assert result.phone_number == "13800000000"
    assert result.empty_weight == "455 g"


def test_official_pdf_import_decodes_link_then_rebuilds_standard_qr(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "official-uom.pdf"
    rebuilt_qr = object()
    record = UomRecord("UAS-DEMO-0001", "DJI Test", "SERIAL001", "演示用户", qr_payload=PAYLOAD)
    calls: list[tuple[str, object]] = []

    def extract_payload(path: Path) -> str:
        calls.append(("decode", path))
        return PAYLOAD

    def rebuild(payload: str):
        calls.append(("rebuild", payload))
        return rebuilt_qr

    monkeypatch.setattr(
        "uom_printer.pipeline.extract_uom_payload_from_file",
        extract_payload,
    )
    monkeypatch.setattr(
        "uom_printer.pipeline.qr_image_from_payload",
        rebuild,
    )
    monkeypatch.setattr("uom_printer.pipeline.fetch_uom_record", lambda payload: record if payload == PAYLOAD else None)
    pipeline = ProcessingPipeline(AppSettings())
    monkeypatch.setattr(
        pipeline,
        "_render_and_save",
        lambda qr, resolved_record, source_path, source: (qr, resolved_record, source_path, source),
    )

    result = pipeline.process_import(pdf_path)

    assert calls == [("decode", pdf_path), ("rebuild", PAYLOAD)]
    assert result == (rebuilt_qr, record, pdf_path, "manual")


def test_photo_import_decodes_link_then_rebuilds_clean_qr(tmp_path: Path, monkeypatch) -> None:
    photo_path = tmp_path / "phone-photo.jpg"
    rebuilt_qr = object()
    record = UomRecord("UAS-DEMO-0001", "DJI Test", "SERIAL001", "演示用户", qr_payload=PAYLOAD)
    calls: list[tuple[str, object]] = []

    def extract_payload(path: Path) -> str:
        calls.append(("decode", path))
        return PAYLOAD

    def rebuild(payload: str):
        calls.append(("rebuild", payload))
        return rebuilt_qr

    monkeypatch.setattr("uom_printer.pipeline.extract_uom_payload_from_file", extract_payload)
    monkeypatch.setattr("uom_printer.pipeline.qr_image_from_payload", rebuild)
    monkeypatch.setattr("uom_printer.pipeline.fetch_uom_record", lambda payload: record if payload == PAYLOAD else None)
    pipeline = ProcessingPipeline(AppSettings())
    monkeypatch.setattr(
        pipeline,
        "_render_and_save",
        lambda qr, resolved_record, source_path, source: (qr, resolved_record, source_path, source),
    )

    result = pipeline.process_import(photo_path)

    assert calls == [("decode", photo_path), ("rebuild", PAYLOAD)]
    assert result == (rebuilt_qr, record, photo_path, "manual")
