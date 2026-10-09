"""Supabase (PostgREST) deposu: PC, Colab ve GitHub Actions aynı veriyi görür.

Ağır `supabase` paketi yerine PostgREST'e doğrudan `requests` ile konuşur.
Yalnızca service key kullanılır; anahtar .env / Colab Secrets / GitHub Secrets'tan gelir.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests

from bulten.db.repo import Row, RepoError, check_table, now_iso, with_defaults

logger = logging.getLogger(__name__)

TIMEOUT = 20
# Repo public: GitHub Actions logları herkese açık → hata ayrıntısı (URL, satır verisi) yazılmaz.
PUBLIC_LOGS = os.getenv("GITHUB_ACTIONS") == "true"
PAGE_SIZE = 1000  # PostgREST varsayılan üst sınırı
COLUMN_RE = re.compile(r"[a-z_]+")


def _column(name: str) -> str:
    """Sütun adları sorgu parametresi olduğu için sıkı doğrulanır (filtre enjeksiyonuna karşı)."""
    if not COLUMN_RE.fullmatch(name or ""):
        raise RepoError(f"Geçersiz sütun adı: {name!r}")
    return name


class SupabaseRepo:
    def __init__(self, url: str, service_key: str, session: Any | None = None) -> None:
        if not url or not service_key:
            raise RepoError("SUPABASE_URL ve SUPABASE_SERVICE_KEY gerekli.")
        self._base = url.rstrip("/") + "/rest/v1"
        self._http = session or requests.Session()
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, table: str, params: dict | None = None, json: Any = None, prefer: str = "") -> Any:
        check_table(table)
        headers = {**self._headers, **({"Prefer": prefer} if prefer else {})}
        try:
            resp = self._http.request(
                method, f"{self._base}/{table}", params=params, json=json, headers=headers, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            detail = type(exc).__name__ if PUBLIC_LOGS else str(exc)
            raise RepoError(f"Supabase'e ulaşılamadı: {detail}") from exc
        if resp.status_code >= 400:
            # Gövde satır verisi (ör. fikir metni) içerebilir; public CI loglarına yazılmaz.
            body = "" if PUBLIC_LOGS else f": {resp.text[:300]}"
            raise RepoError(
                f"Supabase {method} {table} hatası ({resp.status_code}){body}",
                conflict=resp.status_code == 409,
            )
        return resp.json() if resp.content else None

    def insert(self, table: str, row: Row) -> Row:
        data = self._request("POST", table, json=with_defaults(row), prefer="return=representation")
        return data[0]

    def upsert(self, table: str, row: Row) -> Row:
        # created_at gönderilmez: var olan satırın oluşturulma zamanı ezilmesin (DB varsayılanı doldurur).
        data = self._request(
            "POST",
            table,
            json={**row, "id": row.get("id") or with_defaults(row)["id"]},
            prefer="return=representation,resolution=merge-duplicates",
        )
        return data[0]

    def get(self, table: str, row_id: str) -> Row | None:
        data = self._request("GET", table, params={"id": f"eq.{row_id}", "limit": 1})
        return data[0] if data else None

    def select(
        self,
        table: str,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
        since: tuple[str, str] | None = None,
    ) -> list[Row]:
        params: dict[str, Any] = {"select": "*"}
        for key, value in (where or {}).items():
            params[_column(key)] = f"is.{_literal(value)}" if value is None or isinstance(value, bool) else f"eq.{value}"
        if since:
            params[_column(since[0])] = f"gte.{since[1]}"
        if order_by:
            params["order"] = f"{_column(order_by)}.{'desc' if desc else 'asc'}.nullslast"
        if limit is not None:
            params["limit"] = limit
            return self._request("GET", table, params=params) or []
        rows: list[Row] = []
        while True:  # sınırsız sorgular sayfa sayfa okunur (1000 satır üst sınırı)
            page = self._request("GET", table, params={**params, "limit": PAGE_SIZE, "offset": len(rows)}) or []
            rows += page
            if len(page) < PAGE_SIZE:
                return rows

    def update(self, table: str, row_id: str, fields: Row) -> Row:
        data = self._request(
            "PATCH",
            table,
            params={"id": f"eq.{row_id}"},
            json={**fields, "updated_at": now_iso()},
            prefer="return=representation",
        )
        if not data:
            raise RepoError(f"{table}: {row_id} bulunamadı")
        return data[0]

    def delete(self, table: str, row_id: str) -> None:
        self._request("DELETE", table, params={"id": f"eq.{row_id}"})


def _literal(value: Any) -> str:
    if value is None:
        return "null"
    return "true" if value else "false"
