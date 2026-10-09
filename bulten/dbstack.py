"""Self-hosted veritabanı yığınını (docker/docker-compose.yml) panelden yönetmek için yardımcılar."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker" / "docker-compose.yml"
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
TIMEOUT = 90


class StackError(RuntimeError):
    pass


def _compose(*args: str) -> str:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StackError(f"Docker çalıştırılamadı: {type(exc).__name__}. Docker Desktop açık mı?") from exc
    if result.returncode != 0:
        raise StackError((result.stderr or result.stdout).strip()[-300:] or "docker compose hatası")
    return result.stdout + result.stderr


def start_tunnel() -> None:
    _compose("--profile", "tunnel", "up", "-d", "tunnel")


def stop_tunnel() -> None:
    _compose("--profile", "tunnel", "stop", "tunnel")


def tunnel_url() -> str | None:
    """Çalışan tünelin güncel adresi (her başlatmada değişir)."""
    try:
        found = TUNNEL_RE.findall(_compose("--profile", "tunnel", "logs", "tunnel"))
    except StackError:
        return None
    return found[-1] if found else None
