"""Panelin arayüzden bağımsız (test edilebilir) yardımcıları."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any

from bulten import organize
from bulten.db import Repo
from bulten.pipeline import model

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COLAB_URL = "https://colab.research.google.com/github/Oguzhankuri/RSSBot/blob/main/gunluk_bulten_colab.ipynb"
LOG_NAME = "_islem_gunlugu.log"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

STATUS_ICONS = {
    model.WAITING: "⚪",
    model.QUEUED: "👉",
    model.RUNNING: "⏳",
    model.DONE: "✅",
    model.FAILED: "❌",
    model.SKIPPED: "⏭️",
}
ACTOR_LABELS = {model.PC: "Bilgisayar", model.COLAB: "Colab (GPU)", model.USER: "Sen"}


def colab_url(cfg: dict[str, Any]) -> str:
    return (cfg.get("colab") or {}).get("notebook_url") or DEFAULT_COLAB_URL


def uses_local_db(cfg: dict[str, Any]) -> bool:
    """Veritabanı bu bilgisayardaki Docker'da mı (Colab için tünel gerekir)?"""
    url = (cfg.get("env") or {}).get("SUPABASE_URL") or ""
    return cfg.get("db", {}).get("provider") == "supabase" and ("127.0.0.1" in url or "localhost" in url)


def pipeline_command(date_str: str, config_path: str = "config.yaml", force: bool = False) -> list[str]:
    cmd = [sys.executable, "-m", "bulten.pipeline", "advance", "--date", date_str, "--config", config_path]
    return cmd + ["--force"] if force else cmd


def start_background(cmd: list[str], cwd: Path = ROOT) -> subprocess.Popen:
    """Uzun işi panelden bağımsız süreçte başlatır; panel donmaz, durum DB'den izlenir."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(  # noqa: S603 — komut sabit, kullanıcı girdisi yok
        cmd, cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags
    )


def log_path(cfg: dict[str, Any], date_str: str) -> Path:
    return organize.day_dir(date_str, cfg) / LOG_NAME


def tail(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return ""
    with path.open(encoding="utf-8", errors="replace") as fh:
        return "".join(deque(fh, maxlen=lines))


def tr_voice_todo(repo: Repo, cfg: dict[str, Any], date_str: str) -> list[dict[str, Any]]:
    """TR kaydı yapılacak içerikler: okunacak dosya + kaydın konacağı yer + durum."""
    rows = repo.select("contents", {"run_id": model.run_id_for(date_str)}, order_by="created_at")
    todo = []
    for content in rows:
        folder = organize.absolute_folder(content["folder"], cfg)
        todo.append(
            {
                "content": content,
                "script_path": folder / "senaryo_tr.md",
                "wav_path": folder / "ses" / "tr.wav",
                "done": (folder / "ses" / "tr.wav").exists(),
            }
        )
    return todo


def save_upload(target: Path, data: bytes) -> Path:
    """Panelden yüklenen TR kaydını doğru klasöre yazar (yalnızca WAV)."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Yalnızca WAV dosyası yükleyebilirsin.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Dosya çok büyük (en fazla 200 MB).")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target
