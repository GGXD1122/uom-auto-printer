from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import ProcessedLabel
from .paths import database_path


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self.connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_pdf TEXT NOT NULL,
                    output_png TEXT NOT NULL,
                    output_pdf TEXT NOT NULL,
                    preview_png TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS uom_seen (
                    account_key TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(account_key, record_key)
                );
                """
            )
            db.commit()

    def record_job(self, label: ProcessedLabel, status: str = "generated", error: str = "") -> int:
        with closing(self.connect()) as db:
            cursor = db.execute(
                "INSERT INTO jobs(source,source_pdf,output_png,output_pdf,preview_png,record_json,status,error) VALUES(?,?,?,?,?,?,?,?)",
                (
                    label.source,
                    str(label.source_pdf),
                    str(label.print_png),
                    str(label.print_pdf),
                    str(label.preview_png),
                    json.dumps(label.record.to_dict(), ensure_ascii=False),
                    status,
                    error,
                ),
            )
            db.commit()
            return int(cursor.lastrowid)

    def uom_seen_ids(self, account_key: str) -> set[str]:
        """Return completed/baseline rows; errors are intentionally retried."""
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT record_key FROM uom_seen WHERE account_key=? AND status<>'error'",
                (account_key,),
            ).fetchall()
            return {str(row[0]) for row in rows}

    def record_uom(self, account_key: str, record_key: str, status: str, error: str = "") -> None:
        with closing(self.connect()) as db:
            db.execute(
                "INSERT INTO uom_seen(account_key, record_key, status, error) VALUES(?,?,?,?) "
                "ON CONFLICT(account_key, record_key) DO UPDATE SET "
                "status=excluded.status, error=excluded.error, updated_at=CURRENT_TIMESTAMP",
                (account_key, record_key, status, error),
            )
            db.commit()
