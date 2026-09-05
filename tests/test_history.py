from pathlib import Path

from uom_printer.history import HistoryStore


def test_uom_baseline_processed_and_error_retry(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    assert store.uom_seen_ids("uom-web") == set()
    store.record_uom("uom-web", "__baseline__", "baseline")
    store.record_uom("uom-web", "record-1", "baseline")
    store.record_uom("uom-web", "record-2", "error", "二维码尚未生成")
    assert store.uom_seen_ids("uom-web") == {"__baseline__", "record-1"}
    store.record_uom("uom-web", "record-2", "processed")
    assert store.uom_seen_ids("uom-web") == {"__baseline__", "record-1", "record-2"}
