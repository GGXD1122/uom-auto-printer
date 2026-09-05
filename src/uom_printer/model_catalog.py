from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import model_catalog_path


CATALOG_SCHEMA_VERSION = 1
UOM_SOURCE_URL = "https://uom.caac.gov.cn/"
DJI_SOURCE_URL = "https://www.dji.com/cn/support"
_UOM_INTERNAL_FIELDS = {
    "auditState",
    "auditTime",
    "auditUser",
    "createBy",
    "createTime",
    "createUser",
    "deleteFlag",
    "deleted",
    "extInfo",
    "limit",
    "noFile",
    "offset",
    "pageNum",
    "pageSize",
    "pagination",
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
    "updateBy",
    "updateTime",
    "updateUser",
}


class ModelCatalogError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModelCatalogSummary:
    available: bool
    uom_count: int = 0
    dji_count: int = 0
    updated_at: str = ""


def _clean_rows(rows: object) -> list[dict[str, Any]]:
    return [dict(item) for item in rows or [] if isinstance(item, dict)]


def _clean_uom_models(rows: object) -> list[dict[str, Any]]:
    return [
        {
            str(key): value
            for key, value in item.items()
            if str(key) not in _UOM_INTERNAL_FIELDS and not str(key).startswith("_")
        }
        for item in rows or []
        if isinstance(item, dict)
    ]


def build_model_catalog(
    manufacturer: dict[str, Any],
    uom_models: list[dict[str, Any]],
    dji_products: list[dict[str, Any]],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    timestamp = updated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    models = _clean_uom_models(uom_models)
    products = _clean_rows(dji_products)
    return {
        "schemaVersion": CATALOG_SCHEMA_VERSION,
        "updatedAt": timestamp,
        "sources": {
            "uom": {
                "sourceUrl": UOM_SOURCE_URL,
                "fetchedAt": timestamp,
                "manufacturer": {
                    key: str((manufacturer or {}).get(key) or "").strip()
                    for key in ("id", "unitName")
                },
                "count": len(models),
                "models": models,
            },
            "dji": {
                "sourceUrl": DJI_SOURCE_URL,
                "fetchedAt": timestamp,
                "count": len(products),
                "products": products,
            },
        },
    }


class ModelCatalogStore:
    """Atomic, validated local cache for the two official model sources."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        min_uom_models: int = 20,
        min_dji_products: int = 40,
        minimum_retained_ratio: float = 0.65,
    ) -> None:
        self.path = Path(path) if path is not None else model_catalog_path()
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        self.min_uom_models = max(1, int(min_uom_models))
        self.min_dji_products = max(1, int(min_dji_products))
        self.minimum_retained_ratio = max(0.1, min(1.0, float(minimum_retained_ratio)))

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists() and not self.backup_path.exists():
            return None
        try:
            return self._read_validated(self.path)
        except (OSError, json.JSONDecodeError, ModelCatalogError):
            try:
                recovered = self._read_validated(self.backup_path)
            except (OSError, json.JSONDecodeError, ModelCatalogError):
                return None
            self._write_primary(recovered, preserve_primary=False)
            return recovered

    def summary(self) -> ModelCatalogSummary:
        catalog = self.load()
        if catalog is None:
            return ModelCatalogSummary(False)
        sources = catalog["sources"]
        return ModelCatalogSummary(
            True,
            int(sources["uom"]["count"]),
            int(sources["dji"]["count"]),
            str(catalog.get("updatedAt") or ""),
        )

    def save_sources(
        self,
        manufacturer: dict[str, Any],
        uom_models: list[dict[str, Any]],
        dji_products: list[dict[str, Any]],
        *,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        previous = self.load()
        catalog = build_model_catalog(
            manufacturer,
            uom_models,
            dji_products,
            updated_at=updated_at,
        )
        self.validate(catalog, previous=previous)
        self._write_primary(catalog, preserve_primary=True)
        return catalog

    def validate(
        self,
        catalog: dict[str, Any],
        *,
        previous: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(catalog, dict) or int(catalog.get("schemaVersion") or 0) != CATALOG_SCHEMA_VERSION:
            raise ModelCatalogError("型号库版本不受支持。")
        sources = catalog.get("sources")
        if not isinstance(sources, dict):
            raise ModelCatalogError("型号库缺少来源信息。")
        uom = sources.get("uom")
        dji = sources.get("dji")
        if not isinstance(uom, dict) or not isinstance(dji, dict):
            raise ModelCatalogError("型号库必须同时包含UOM和大疆数据。")

        manufacturer = uom.get("manufacturer")
        if not isinstance(manufacturer, dict) or not str(manufacturer.get("id") or "").strip():
            raise ModelCatalogError("UOM型号库缺少生产厂商标识。")
        models = _clean_rows(uom.get("models"))
        if len(models) < self.min_uom_models:
            raise ModelCatalogError(f"UOM只返回 {len(models)} 条型号，疑似分页未完成，旧库未替换。")
        codes: set[str] = set()
        for model in models:
            code = str(model.get("chanpxh") or "").strip().casefold()
            name = str(model.get("chanpmc") or "").strip()
            if not code or not name:
                raise ModelCatalogError("UOM型号存在缺少名称或型号代码的记录。")
            if code in codes:
                raise ModelCatalogError(f"UOM返回重复型号代码：{model.get('chanpxh')}")
            codes.add(code)
        if int(uom.get("count") or -1) != len(models):
            raise ModelCatalogError("UOM型号数量校验失败。")

        products = _clean_rows(dji.get("products"))
        if len(products) < self.min_dji_products:
            raise ModelCatalogError(f"大疆官网只返回 {len(products)} 个产品入口，疑似页面未加载完整，旧库未替换。")
        slugs: set[str] = set()
        for product in products:
            slug = str(product.get("slug") or "").strip().casefold()
            title = str(product.get("title") or "").strip()
            url = str(product.get("url") or "").strip()
            if not slug or not title or "/support/product/" not in url:
                raise ModelCatalogError("大疆产品目录存在不完整记录。")
            if slug in slugs:
                raise ModelCatalogError(f"大疆官网返回重复产品入口：{slug}")
            slugs.add(slug)
        if int(dji.get("count") or -1) != len(products):
            raise ModelCatalogError("大疆产品数量校验失败。")

        if previous is not None:
            old_sources = previous.get("sources") if isinstance(previous, dict) else None
            if isinstance(old_sources, dict):
                self._validate_retained_count("UOM", len(models), old_sources.get("uom"))
                self._validate_retained_count("大疆", len(products), old_sources.get("dji"))

    def _validate_retained_count(self, label: str, current_count: int, previous_source: object) -> None:
        if not isinstance(previous_source, dict):
            return
        previous_count = int(previous_source.get("count") or 0)
        if previous_count <= 0:
            return
        minimum = math.ceil(previous_count * self.minimum_retained_ratio)
        if current_count < minimum:
            raise ModelCatalogError(
                f"{label}数据从 {previous_count} 条降到 {current_count} 条，疑似更新不完整，旧库未替换。"
            )

    def _read_validated(self, path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.validate(data)
        return data

    def _write_primary(self, catalog: dict[str, Any], *, preserve_primary: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            with self.temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if preserve_primary and self.path.exists():
                backup_tmp = self.backup_path.with_suffix(self.backup_path.suffix + ".tmp")
                shutil.copy2(self.path, backup_tmp)
                os.replace(backup_tmp, self.backup_path)
            os.replace(self.temporary_path, self.path)
        finally:
            self.temporary_path.unlink(missing_ok=True)
