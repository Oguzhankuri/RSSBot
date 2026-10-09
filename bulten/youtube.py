"""YouTube bağlantısı: video linki ↔ içerik eşleşmesi ve performans metriklerinin çekilmesi.

Bir kerelik yetkilendirme:   python -m bulten.youtube auth
Metrikleri çekme:            python -m bulten.youtube sync   (panelde buton da var)
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Protocol

from bulten.db import Repo, RepoError

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
METRICS = "views,averageViewDuration,averageViewPercentage,likes,comments,subscribersGained"
METRIC_COLUMNS = ("views", "avg_view_duration", "avg_view_pct", "likes", "comments", "subs_gained")
BATCH = 50
START_DATE = "2020-01-01"

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtu\.be/|youtube\.com/(?:shorts|embed|live)/)([A-Za-z0-9_-]{11})"),
)


class YouTubeError(RuntimeError):
    pass


def parse_video_id(value: str) -> str | None:
    value = (value or "").strip()
    if VIDEO_ID_RE.match(value):
        return value
    for pattern in URL_PATTERNS:
        found = pattern.search(value)
        if found:
            return found.group(1)
    return None


def link_video(repo: Repo, content_id: str, url_or_id: str) -> dict:
    video_id = parse_video_id(url_or_id)
    if video_id is None:
        raise YouTubeError("Geçerli bir YouTube linki değil (watch?v=…, youtu.be/…, shorts/…).")
    return repo.update("contents", content_id, {"yt_video_id": video_id})


class AnalyticsSource(Protocol):
    def fetch(self, video_ids: list[str], end_date: str) -> dict[str, dict[str, float]]: ...


class YouTubeAnalytics:
    """YouTube Analytics API v2 (kanal sahibinin OAuth yetkisiyle)."""

    def __init__(self, service: Any) -> None:
        self._service = service

    @classmethod
    def from_token(cls, token_path: str | Path) -> "YouTubeAnalytics":
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise YouTubeError("pip install -r requirements.txt (google-api-python-client eksik)") from exc
        if not Path(token_path).exists():
            raise YouTubeError("YouTube yetkisi yok. Bir kez çalıştır: python -m bulten.youtube auth")
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            Path(token_path).write_text(creds.to_json(), encoding="utf-8")
        return cls(build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False))

    def fetch(self, video_ids: list[str], end_date: str) -> dict[str, dict[str, float]]:
        results: dict[str, dict[str, float]] = {}
        for i in range(0, len(video_ids), BATCH):
            chunk = video_ids[i : i + BATCH]
            resp = self._service.reports().query(
                ids="channel==MINE",
                startDate=START_DATE,
                endDate=end_date,
                metrics=METRICS,
                dimensions="video",
                filters="video==" + ",".join(chunk),
            ).execute()
            for row in resp.get("rows") or []:
                results[row[0]] = dict(zip(METRIC_COLUMNS, row[1:]))
        return results


def authorize(cfg: dict[str, Any]) -> Path:
    """Tarayıcıda Google onayı açar, token'ı secrets/ altına kaydeder."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    ycfg = cfg["youtube"]
    secret = Path(ycfg["client_secret"])
    if not secret.exists():
        raise YouTubeError(f"{secret} yok. Google Cloud → OAuth istemcisi (Desktop) JSON'unu buraya koy.")
    creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
    token = Path(ycfg["token_path"])
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    return token


def sync_metrics(repo: Repo, source: AnalyticsSource, end_date: str) -> int:
    """Linki olan tüm içeriklerin güncel metriklerini zaman serisi olarak kaydeder."""
    contents = [c for c in repo.select("contents") if c.get("yt_video_id")]
    if not contents:
        return 0
    data = source.fetch(sorted({c["yt_video_id"] for c in contents}), end_date)
    saved = 0
    for content in contents:
        values = data.get(content["yt_video_id"])
        if values is None:
            continue
        repo.insert("metrics", {"content_id": content["id"], "yt_video_id": content["yt_video_id"], **values})
        saved += 1
    logger.info("YouTube: %d içeriğin metrikleri güncellendi.", saved)
    return saved


def main(argv: list[str] | None = None) -> int:
    import argparse

    from bulten.config import ConfigError, load_config
    from bulten.db import create_repo
    from bulten.utils import setup_logging, today_str

    parser = argparse.ArgumentParser(prog="python -m bulten.youtube")
    parser.add_argument("command", choices=["auth", "sync"])
    args = parser.parse_args(argv)
    setup_logging()
    try:
        cfg = load_config("config.yaml", require_db=True)
        if args.command == "auth":
            logger.info("Token kaydedildi: %s", authorize(cfg))
        else:
            source = YouTubeAnalytics.from_token(cfg["youtube"]["token_path"])
            sync_metrics(create_repo(cfg), source, today_str())
        return 0
    except (ConfigError, RepoError, YouTubeError) as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
