"""Panel için tek şifreli giriş (kullanıcı adı yok).

- Şifrenin kendisi hiçbir yerde saklanmaz; .env'de yalnızca scrypt özeti durur (PANEL_PASSWORD_HASH).
- Başarılı girişte 30 gün geçerli, imzalı bir oturum çerezi verilir (PANEL_SESSION_SECRET ile HMAC).
- Peş peşe yanlış denemelerde bekleme süresi katlanarak artar (kaba kuvvet denemelerine karşı).

Şifre belirlemek (sunucuda bir kez):   python3 -m bulten.auth set-password
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD_LEN = 12
SESSION_DAYS = 30
COOKIE_NAME = "rssbot_oturum"
FREE_ATTEMPTS = 3
MAX_LOCK_SEC = 15 * 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    # ":" ayırıcı: "$" docker compose / .env dosyalarında değişken sanılabilir.
    return f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}:{_b64(salt)}:{_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split(":")
        if algo != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(_unb64(digest))
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, _unb64(digest))


def _signing_key(session_secret: str, password_hash: str) -> bytes:
    # Şifre değişince özet değişir → eski tüm oturumlar kendiliğinden geçersiz olur.
    return hashlib.sha256(f"{session_secret}|{password_hash}".encode()).digest()


def issue_token(session_secret: str, password_hash: str, now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(_signing_key(session_secret, password_hash), str(expires).encode(), hashlib.sha256).digest()
    return f"{expires}.{_b64(sig)}"


def verify_token(token: str | None, session_secret: str, password_hash: str, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, sig = token.split(".", 1)
    if not expires.isdigit() or int(expires) < (now or time.time()):
        return False
    expected = hmac.new(_signing_key(session_secret, password_hash), expires.encode(), hashlib.sha256).digest()
    try:
        return hmac.compare_digest(expected, _unb64(sig))
    except (ValueError, TypeError):
        return False


@dataclass
class Throttle:
    """Tek kullanıcılı panel: tüm yanlış denemeler ortak sayılır; süre 2^n saniye artar (en çok 15 dk)."""

    failures: int = 0
    locked_until: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def wait_seconds(self, now: float | None = None) -> int:
        return max(0, int(self.locked_until - (now or time.time()) + 0.999))

    def record_failure(self, now: float | None = None) -> None:
        with self._lock:
            self.failures += 1
            if self.failures > FREE_ATTEMPTS:
                delay = min(MAX_LOCK_SEC, 2 ** (self.failures - FREE_ATTEMPTS))
                self.locked_until = (now or time.time()) + delay

    def record_success(self) -> None:
        with self._lock:
            self.failures, self.locked_until = 0, 0.0


THROTTLE = Throttle()


def _set_env(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        out.append(f"{key}={remaining.pop(key)}" if key in remaining else line)
    out += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from getpass import getpass

    args = argv if argv is not None else sys.argv[1:]
    if args[:1] != ["set-password"]:
        print("Kullanım: python3 -m bulten.auth set-password [--env .env]")
        return 2
    env_path = Path(args[args.index("--env") + 1]) if "--env" in args else Path(".env")
    password = getpass("Yeni panel şifresi: ")
    if len(password) < MIN_PASSWORD_LEN:
        print(f"Şifre en az {MIN_PASSWORD_LEN} karakter olmalı.")
        return 1
    if getpass("Tekrar: ") != password:
        print("Şifreler uyuşmuyor.")
        return 1
    _set_env(env_path, {"PANEL_PASSWORD_HASH": hash_password(password), "PANEL_SESSION_SECRET": secrets.token_urlsafe(32)})
    print(f"✅ Şifre özeti {env_path} dosyasına yazıldı. Eski oturumlar geçersiz. Paneli yeniden başlat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
