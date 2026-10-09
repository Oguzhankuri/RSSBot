"""SQLite belge deposu: Supabase kurulmadan yerelde ve testlerde çalışır.

Her tablo (id, data JSON) çiftlerini tutar; filtreleme Python tarafında yapılır.
Veri hacmi küçük (günde onlarca satır) olduğu için bu yeterince hızlıdır.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from bulten.db.repo import TABLES, Row, RepoError, check_table, matches, now_iso, sort_rows, with_defaults


class SqliteRepo:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Panel ve pipeline alt süreci aynı dosyayı paylaşır: bekleme süresi + açık işlemler.
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30, isolation_level=None)
        self._lock = threading.Lock()
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        with self._tx():
            for table in TABLES:
                self._conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (id TEXT PRIMARY KEY, data TEXT NOT NULL)')

    @contextmanager
    def _tx(self):
        """BEGIN IMMEDIATE: oku-değiştir-yaz arasında başka süreç yazamaz."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _get_raw(self, table: str, row_id: str) -> Row | None:
        found = self._conn.execute(f'SELECT data FROM "{table}" WHERE id = ?', (row_id,)).fetchone()
        return json.loads(found[0]) if found else None

    def _put(self, table: str, row: Row, replace: bool) -> None:
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        self._conn.execute(
            f'{verb} INTO "{table}" (id, data) VALUES (?, ?)', (row["id"], json.dumps(row, ensure_ascii=False))
        )

    def insert(self, table: str, row: Row) -> Row:
        check_table(table)
        full = with_defaults(row)
        try:
            with self._tx():
                self._put(table, full, replace=False)
        except sqlite3.IntegrityError as exc:
            raise RepoError(f"{table}: {full['id']} zaten var", conflict=True) from exc
        return full

    def upsert(self, table: str, row: Row) -> Row:
        check_table(table)
        with self._tx():
            existing = self._get_raw(table, row["id"]) if row.get("id") else None
            full = with_defaults({**(existing or {}), **row})
            self._put(table, full, replace=True)
        return full

    def get(self, table: str, row_id: str) -> Row | None:
        check_table(table)
        with self._lock:
            return self._get_raw(table, row_id)

    def select(
        self,
        table: str,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
        since: tuple[str, str] | None = None,
    ) -> list[Row]:
        check_table(table)
        with self._lock:
            raw = self._conn.execute(f'SELECT data FROM "{table}"').fetchall()
        rows = [r for r in (json.loads(x[0]) for x in raw) if matches(r, where, since)]
        return sort_rows(rows, order_by, desc, limit)

    def update(self, table: str, row_id: str, fields: Row) -> Row:
        check_table(table)
        with self._tx():
            existing = self._get_raw(table, row_id)
            if existing is None:
                raise RepoError(f"{table}: {row_id} bulunamadı")
            full = {**existing, **fields, "id": row_id, "updated_at": now_iso()}
            self._put(table, full, replace=True)
        return full

    def delete(self, table: str, row_id: str) -> None:
        check_table(table)
        with self._tx():
            self._conn.execute(f'DELETE FROM "{table}" WHERE id = ?', (row_id,))
