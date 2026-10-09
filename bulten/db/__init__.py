"""Yapılandırmaya göre doğru depoyu seçer."""

from __future__ import annotations

from typing import Any

from bulten.db.repo import Repo, RepoError, kv_get, kv_set, new_id, now_iso
from bulten.db.sqlite_repo import SqliteRepo
from bulten.db.supabase_repo import SupabaseRepo

__all__ = ["Repo", "RepoError", "SqliteRepo", "SupabaseRepo", "create_repo", "kv_get", "kv_set", "new_id", "now_iso"]


def create_repo(cfg: dict[str, Any]) -> Repo:
    dcfg = cfg.get("db") or {}
    provider = dcfg.get("provider", "sqlite")
    if provider == "supabase":
        env = cfg.get("env") or {}
        return SupabaseRepo(env.get("SUPABASE_URL") or "", env.get("SUPABASE_SERVICE_KEY") or "")
    if provider == "sqlite":
        return SqliteRepo(dcfg.get("sqlite_path", "state/bulten.db"))
    raise RepoError(f"Bilinmeyen db.provider: {provider!r} (supabase | sqlite)")
