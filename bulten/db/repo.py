"""Veri erişim arayüzü (repository pattern): iş mantığı depolama türünü bilmez."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

TABLES = (
    "ideas",
    "seen_items",
    "runs",
    "run_steps",
    "contents",
    "ratings",
    "metrics",
    "insights",
    "kv",
)

Row = dict[str, Any]


class RepoError(Exception):
    """Veritabanı işlemi başarısız olduğunda fırlatılır.

    conflict=True yalnızca "bu kimlik zaten var" demektir; ağ/sunucu hatalarında False.
    """

    def __init__(self, message: str, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


class Repo(Protocol):
    """Her satırın metin 'id' birincil anahtarı vardır; filtreler eşitlik karşılaştırmasıdır."""

    def insert(self, table: str, row: Row) -> Row: ...

    def upsert(self, table: str, row: Row) -> Row: ...

    def get(self, table: str, row_id: str) -> Row | None: ...

    def select(
        self,
        table: str,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
        since: tuple[str, str] | None = None,
    ) -> list[Row]: ...

    def update(self, table: str, row_id: str, fields: Row) -> Row: ...

    def delete(self, table: str, row_id: str) -> None: ...


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_table(table: str) -> None:
    if table not in TABLES:
        raise RepoError(f"Bilinmeyen tablo: {table}")


def with_defaults(row: Row) -> Row:
    """id ve created_at yoksa ekleyerek YENİ bir sözlük döndürür."""
    return {**row, "id": row.get("id") or new_id(), "created_at": row.get("created_at") or now_iso()}


def matches(row: Row, where: dict[str, Any] | None, since: tuple[str, str] | None) -> bool:
    if where and any(row.get(k) != v for k, v in where.items()):
        return False
    if since:
        col, value = since
        if str(row.get(col) or "") < value:
            return False
    return True


def sort_rows(rows: list[Row], order_by: str | None, desc: bool, limit: int | None) -> list[Row]:
    """Postgres'teki 'nullslast' davranışıyla aynı: boş değerler yön ne olursa olsun sonda."""
    if order_by:
        present = sorted((r for r in rows if r.get(order_by) is not None), key=lambda r: r[order_by], reverse=desc)
        rows = present + [r for r in rows if r.get(order_by) is None]
    return rows[:limit] if limit is not None else rows


# --- Küçük anahtar/değer yardımcıları (Telegram offset, tek seferlik bayraklar) ---

def kv_get(repo: Repo, key: str, default: Any = None) -> Any:
    row = repo.get("kv", key)
    return default if row is None else row.get("value", default)


def kv_set(repo: Repo, key: str, value: Any) -> None:
    repo.upsert("kv", {"id": key, "value": value, "updated_at": now_iso()})
