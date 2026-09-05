from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .history import HistoryStore
from .label_renderer import persist_label_set_outputs, render_info_label, render_qr_label, save_label_set_outputs
from .layout_template import load_layout_template
from .models import ProcessedLabelSet
from .paths import inbox_dir, layout_template_path, output_dir
from .printing import print_label
from .settings import AppSettings
from .uom_service import (
    UomProcessingError,
    extract_uom_payload_from_file,
    fetch_uom_record,
    is_complete_phone_number,
    qr_image_from_payload,
    record_from_uom_row,
)


LogCallback = Callable[[str, str], None]


class ProcessingPipeline:
    def __init__(self, settings: AppSettings, history: HistoryStore | None = None, logger: LogCallback | None = None) -> None:
        self.settings = settings
        self.history = history or HistoryStore()
        self.logger = logger or (lambda level, message: None)

    def log(self, level: str, message: str) -> None:
        self.logger(level, message)

    def _render_and_save(self, qr_image, record, source_path: Path, source: str) -> ProcessedLabelSet:
        layout = load_layout_template(layout_template_path()) if self.settings.custom_layout_enabled else None
        qr_label = render_qr_label(qr_image, record, self.settings.label_dpi, layout=layout)
        info_label = render_info_label(qr_image, record, self.settings.label_dpi, layout=layout)
        result = save_label_set_outputs(
            qr_label,
            info_label,
            record,
            source_path,
            None,
            source,
            persist_output=False,
        )
        self.history.record_job(result.qr_label)
        self.history.record_job(result.info_label)
        size_text = f"{layout.paper_width_mm:g}×{layout.paper_height_mm:g} mm" if layout else "60×40 mm"
        self.log("ok", f"已生成两套{size_text}标签预览，打印时才会保存到输出文件夹")
        return result

    def process_import(self, file_path: Path, source: str = "manual") -> ProcessedLabelSet:
        """Decode the UOM URL and always rebuild one standardized QR image."""
        path = Path(file_path)
        suffix = path.suffix.lower()
        supported_images = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        if suffix == ".pdf":
            self.log("step", f"读取官方PDF：{path.name}")
        elif suffix in supported_images:
            self.log("step", f"识别实名码图片：{path.name}")
        else:
            raise UomProcessingError("不支持的文件格式，请导入UOM PDF或JPG、PNG等图片")

        payload = extract_uom_payload_from_file(path)
        self.log("ok", "已提取UOM登记链接，原PDF或图片中的二维码图案不会参与打印")
        qr_image = qr_image_from_payload(payload)
        self.log("ok", "已重建标准正方形、高容错并带官方中心图标的UOM二维码")

        record = fetch_uom_record(payload)
        self.log("ok", "实名信息识别成功，所需字段完整")
        return self._render_and_save(qr_image, record, path, source)

    def process_pdf(self, pdf_path: Path, source: str = "manual") -> ProcessedLabelSet:
        """Compatibility wrapper for older callers and tests."""
        return self.process_import(pdf_path, source)

    def process_uom_row(self, row: dict) -> ProcessedLabelSet:
        """Build a label directly from an authenticated UOM registration row."""
        self.log("step", "读取最新UOM实名登记记录")
        record = record_from_uom_row(row)
        if not is_complete_phone_number(record.phone_number) or not record.empty_weight:
            try:
                detail = fetch_uom_record(record.qr_payload)
                if is_complete_phone_number(detail.phone_number):
                    record.phone_number = detail.phone_number
                if detail.empty_weight:
                    record.empty_weight = detail.empty_weight
            except Exception as exc:
                self.log("warn", f"完整电话或空机重量补全失败，将使用现有登记数据：{exc}")
        qr_image = qr_image_from_payload(record.qr_payload)
        self.log("ok", "已从UOM登记数据生成高容错二维码")
        snapshot_dir = inbox_dir() / "uom"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        safe_serial = "".join(ch for ch in record.aircraft_serial if ch.isalnum() or ch in "-_") or "record"
        snapshot = snapshot_dir / f"{safe_serial}.json"
        snapshot.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return self._render_and_save(qr_image, record, snapshot, "uom_web")

    def submit_print(self, labels: ProcessedLabelSet) -> ProcessedLabelSet:
        qr_copies = max(1, int(self.settings.qr_label_copies))
        info_copies = max(1, int(self.settings.info_label_copies))
        persist_label_set_outputs(labels, output_dir(self.settings.output_directory))
        self.log("ok", f"打印文件已保存：{labels.qr_label.print_png.parent}")
        self.log(
            "step",
            f"提交Windows打印队列：实名双码×{qr_copies}，设备信息×{info_copies}",
        )
        print_label(labels.qr_label.print_png, self.settings.printer_name, qr_copies)
        print_label(labels.info_label.print_png, self.settings.printer_name, info_copies)
        self.log("ok", f"打印任务已提交，共{qr_copies + info_copies}张")
        return labels
