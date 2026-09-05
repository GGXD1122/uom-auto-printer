from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class UomRecord:
    uas_code: str
    model_name: str
    aircraft_serial: str
    owner_name: str
    phone_number: str = ""
    empty_weight: str = ""
    product_model: str = ""
    manufacturer: str = ""
    status: str = ""
    maximum_takeoff_weight: str = ""
    registration_time: str = ""
    owner_type: str = ""
    qr_payload: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("raw", None)
        return value


@dataclass(slots=True)
class ProcessedLabel:
    source_pdf: Path
    print_png: Path
    print_pdf: Path
    preview_png: Path
    record: UomRecord
    created_at: datetime = field(default_factory=datetime.now)
    source: str = "manual"
    template_name: str = ""


@dataclass(slots=True)
class ProcessedLabelSet:
    qr_label: ProcessedLabel
    info_label: ProcessedLabel

    @property
    def record(self) -> UomRecord:
        return self.qr_label.record

    @property
    def source_pdf(self) -> Path:
        return self.qr_label.source_pdf
