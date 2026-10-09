"""Self-hosted veritabanı için şifreleri ve anahtarı üretir; hiçbir gizli değeri ekrana yazmaz.

    python docker/setup_db.py

- docker/.env           → Postgres/PostgREST şifreleri ve JWT sırrı (yoksa üretilir, varsa korunur)
- .env (proje kökü)      → SUPABASE_URL ve SUPABASE_SERVICE_KEY (service_role JWT'si)
- config.yaml            → db.provider: "supabase"
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKER_ENV = ROOT / "docker" / ".env"
PROJECT_ENV = ROOT / ".env"
CONFIG = ROOT / "config.yaml"
LOCAL_URL = "http://127.0.0.1:8000"
TEN_YEARS = 10 * 365 * 24 * 3600


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_jwt(payload: dict, secret: str) -> str:
    """HS256 JWT (PostgREST'in beklediği biçim) — ek kütüphane gerektirmez."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line and not line.lstrip().startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def set_env_values(path: Path, values: dict[str, str]) -> None:
    """Var olan satırları günceller, olmayanları ekler; diğer satırlara dokunmaz."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining and not line.lstrip().startswith("#"):
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def ensure_docker_env() -> dict[str, str]:
    current = read_env(DOCKER_ENV)
    wanted = {
        "POSTGRES_PASSWORD": current.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(24),
        "AUTHENTICATOR_PASSWORD": current.get("AUTHENTICATOR_PASSWORD") or secrets.token_urlsafe(24),
        "JWT_SECRET": current.get("JWT_SECRET") or secrets.token_urlsafe(48),
        "GATEWAY_PORT": current.get("GATEWAY_PORT") or "8000",
    }
    set_env_values(DOCKER_ENV, wanted)
    return wanted


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows konsolu
    values = ensure_docker_env()
    now = int(time.time())
    service_key = sign_jwt({"role": "service_role", "iss": "rssbot", "iat": now, "exp": now + TEN_YEARS}, values["JWT_SECRET"])
    set_env_values(PROJECT_ENV, {"SUPABASE_URL": f"http://127.0.0.1:{values['GATEWAY_PORT']}", "SUPABASE_SERVICE_KEY": service_key})

    text = CONFIG.read_text(encoding="utf-8")
    text = re.sub(r'(\n\s*provider:\s*)"sqlite"', r'\1"supabase"', text, count=1)
    CONFIG.write_text(text, encoding="utf-8")

    print("✅ docker/.env hazır (şifreler üretildi/korundu)")
    print("✅ .env → SUPABASE_URL ve SUPABASE_SERVICE_KEY yazıldı (değerler gösterilmiyor)")
    print("✅ config.yaml → db.provider: supabase")
    print("Sıradaki: docker compose -f docker/docker-compose.yml up -d")


if __name__ == "__main__":
    main()
