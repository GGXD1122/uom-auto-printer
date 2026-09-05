import json

from uom_printer.paths import config_path
from uom_printer.settings import AppSettings, SettingsStore


def test_legacy_poll_interval_is_normalized_to_fixed_default(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "poll_seconds": 15,
                "poll_jitter_min_seconds": 10,
                "poll_jitter_max_seconds": 20,
                "auto_print": False,
            }
        ),
        encoding="utf-8",
    )

    settings = SettingsStore(path).load()

    assert settings.poll_jitter_min_seconds == 3
    assert settings.poll_jitter_max_seconds == 10
    assert settings.poll_seconds == 7
    assert settings.auto_print is False


def test_upgrade_migrates_old_shared_config_without_resetting_copy_counts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UOM_PRINTER_APP_DATA", str(tmp_path))
    legacy = tmp_path / "config.json"
    legacy.write_text(
        json.dumps({"qr_label_copies": 1, "info_label_copies": 1, "printer_name": "DL-720W"}),
        encoding="utf-8",
    )

    migrated = config_path()
    settings = SettingsStore().load()

    assert migrated == tmp_path / "auto-printer-config.json"
    assert migrated.exists()
    assert settings.qr_label_copies == 1
    assert settings.info_label_copies == 1
    assert settings.printer_name == "DL-720W"


def test_legacy_single_copy_field_is_preserved_for_both_labels(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"copies": 1}), encoding="utf-8")

    settings = SettingsStore(path).load()

    assert settings.qr_label_copies == 1
    assert settings.info_label_copies == 1


def test_corrupt_primary_recovers_from_backup_without_destroying_backup(tmp_path) -> None:
    path = tmp_path / "config.json"
    backup = tmp_path / "config.json.bak"
    path.write_text("{broken", encoding="utf-8")
    backup.write_text(json.dumps({"qr_label_copies": 1, "info_label_copies": 1}), encoding="utf-8")

    settings = SettingsStore(path).load()

    assert settings.qr_label_copies == 1
    assert settings.info_label_copies == 1
    assert json.loads(backup.read_text(encoding="utf-8"))["qr_label_copies"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["qr_label_copies"] == 1


def test_save_keeps_previous_settings_as_backup(tmp_path) -> None:
    path = tmp_path / "config.json"
    store = SettingsStore(path)
    store.save(AppSettings(qr_label_copies=1, info_label_copies=1))
    store.save(AppSettings(qr_label_copies=3, info_label_copies=2))

    assert SettingsStore(path).load().qr_label_copies == 3
    assert json.loads(store.backup_path.read_text(encoding="utf-8"))["qr_label_copies"] == 1
