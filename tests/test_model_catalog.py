import json

import pytest

from uom_printer.model_catalog import ModelCatalogError, ModelCatalogStore


def uom_models(count: int) -> list[dict[str, str]]:
    return [
        {
            "id": f"demo-model-{index}",
            "chanpmc": f"DJI 演示机型 {index}",
            "chanpxh": f"DEMO-{index:03d}",
            "kongjzl": "0.45",
            "zuidqfzl": "0.47",
        }
        for index in range(count)
    ]


def dji_products(count: int) -> list[dict[str, str]]:
    return [
        {
            "title": f"DJI 演示机型 {index}",
            "slug": f"demo-model-{index}",
            "url": f"https://www.dji.com/cn/support/product/demo-model-{index}",
        }
        for index in range(count)
    ]


def manufacturer() -> dict[str, str]:
    return {"id": "demo-company", "unitName": "演示厂商"}


def test_fresh_install_does_not_create_or_bundle_catalog(tmp_path) -> None:
    store = ModelCatalogStore(tmp_path / "model-catalog.json")

    assert store.load() is None
    assert store.summary().available is False
    assert not store.path.exists()


def test_catalog_save_is_atomic_and_keeps_previous_complete_backup(tmp_path) -> None:
    store = ModelCatalogStore(tmp_path / "model-catalog.json")
    store.save_sources(manufacturer(), uom_models(20), dji_products(40), updated_at="2026-07-29T09:00:00+08:00")
    store.save_sources(manufacturer(), uom_models(21), dji_products(41), updated_at="2026-07-29T10:00:00+08:00")

    assert store.load()["sources"]["uom"]["count"] == 21
    assert json.loads(store.backup_path.read_text(encoding="utf-8"))["sources"]["uom"]["count"] == 20
    assert not store.temporary_path.exists()


def test_corrupt_primary_recovers_from_last_valid_backup(tmp_path) -> None:
    store = ModelCatalogStore(tmp_path / "model-catalog.json")
    store.save_sources(manufacturer(), uom_models(20), dji_products(40))
    store.save_sources(manufacturer(), uom_models(21), dji_products(41))
    store.path.write_text("{broken", encoding="utf-8")

    recovered = store.load()

    assert recovered is not None
    assert recovered["sources"]["uom"]["count"] == 20
    assert json.loads(store.path.read_text(encoding="utf-8"))["sources"]["dji"]["count"] == 40


def test_suspicious_count_drop_is_rejected_without_replacing_old_catalog(tmp_path) -> None:
    store = ModelCatalogStore(tmp_path / "model-catalog.json")
    store.save_sources(manufacturer(), uom_models(100), dji_products(100))
    original = store.path.read_bytes()

    with pytest.raises(ModelCatalogError, match="疑似更新不完整"):
        store.save_sources(manufacturer(), uom_models(60), dji_products(100))

    assert store.path.read_bytes() == original


def test_duplicate_uom_model_code_is_rejected(tmp_path) -> None:
    models = uom_models(20)
    models[-1]["chanpxh"] = models[0]["chanpxh"]
    store = ModelCatalogStore(tmp_path / "model-catalog.json")

    with pytest.raises(ModelCatalogError, match="重复型号代码"):
        store.save_sources(manufacturer(), models, dji_products(40))

    assert not store.path.exists()


def test_incomplete_dji_source_is_rejected_on_first_update(tmp_path) -> None:
    store = ModelCatalogStore(tmp_path / "model-catalog.json")

    with pytest.raises(ModelCatalogError, match="疑似页面未加载完整"):
        store.save_sources(manufacturer(), uom_models(20), dji_products(3))

    assert not store.path.exists()


def test_catalog_strips_uom_audit_metadata_before_persisting(tmp_path) -> None:
    models = uom_models(20)
    models[0].update(
        {
            "auditUser": "internal-auditor",
            "createUser": "internal-creator",
            "params": {"private": "metadata"},
            "chanplb": "01",
        }
    )
    company = {**manufacturer(), "unitUsccode": "not-needed-locally"}
    store = ModelCatalogStore(tmp_path / "model-catalog.json")

    catalog = store.save_sources(company, models, dji_products(40))

    saved_model = catalog["sources"]["uom"]["models"][0]
    assert saved_model["chanplb"] == "01"
    assert "auditUser" not in saved_model
    assert "createUser" not in saved_model
    assert "params" not in saved_model
    assert catalog["sources"]["uom"]["manufacturer"] == {
        "id": "demo-company",
        "unitName": "演示厂商",
    }
