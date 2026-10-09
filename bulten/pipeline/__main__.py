"""Komut satırı: python -m bulten.pipeline <komut> [--date YYYY-MM-DD]

  start / advance   PC'de: sırası gelen otomatik adımları çalıştır (panel butonu bunu çağırır)
  gpu               Colab'da: GPU adımlarını çalıştır (--only images | voices)
  status            Günün adımlarını ve "sıra kimde" bilgisini yaz
  unlock            Yarıda kalan kilitleri temizle
  colab-turn        Sıra Colab'daysa 0, değilse 3 döndürür (notebook gereksiz kurulum yapmasın)

--date latest  →  bitmemiş en yeni gün (Colab'ı gece yarısından sonra açarsan da doğru günü bulur)
"""

from __future__ import annotations

import argparse
import logging
import sys

from bulten import organize
from bulten.config import ConfigError, load_config
from bulten.db import RepoError, create_repo
from bulten.pipeline import model, runner
from bulten.utils import ensure_dir, setup_logging, today_str

logger = logging.getLogger("pipeline")

NOT_COLAB_TURN = 3


def resolve_date(repo, value: str | None) -> str:
    if value != "latest":
        return value or today_str()
    active = repo.select("runs", {"status": "aktif"}, order_by="date", desc=True, limit=1)
    return active[0]["date"] if active else today_str()


def _attach_day_log(cfg: dict, date_str: str) -> None:
    """Günlük işlem kaydı gün klasörüne yazılır: panel de Colab da aynı dosyayı görür."""
    path = ensure_dir(organize.day_dir(date_str, cfg)) / "_islem_gunlugu.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
    logging.getLogger().addHandler(handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bulten.pipeline")
    parser.add_argument("command", choices=["start", "advance", "gpu", "status", "unlock", "colab-turn"])
    parser.add_argument("--date", default=None)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--only", choices=["images", "voices"], default=None)
    parser.add_argument("--force", action="store_true", help="'çalışıyor' kilidini yok say")
    args = parser.parse_args(argv)
    setup_logging()

    try:
        needs_text = args.command in ("start", "advance")
        cfg = load_config(args.config, require_text=needs_text, require_db=True)
        repo = create_repo(cfg)
        date_str = resolve_date(repo, args.date)
        if args.command == "colab-turn":
            turn = runner.turn_for_date(repo, date_str)
            ok = turn is not None and turn.actor == model.COLAB
            print(f"{date_str}: " + (turn.title if turn else "Bu gün için kayıt yok."))
            return 0 if ok else NOT_COLAB_TURN
        if args.command == "status":
            for row in runner.list_steps(repo, model.run_id_for(date_str)):
                print(f"{row['position']}. {row['key']:<9} {row['actor']:<6} {row['status']:<10} {row.get('message') or ''}")
        elif args.command == "unlock":
            print(f"{runner.unlock(repo, date_str)} kilit temizlendi.")
        else:
            _attach_day_log(cfg, date_str)
            if args.command == "gpu":
                actors, only = (model.COLAB,), [args.only] if args.only else ["images", "voices"]
            else:
                actors, only = (model.PC,), None
            turn = runner.advance(repo, cfg, date_str, actors=actors, only=only, force=args.force)
            logger.info("%s — %s", turn.title, turn.detail)
            return 1 if turn.status == model.FAILED else 0
        turn = runner.turn_for_date(repo, date_str)
        if turn:
            print(f"\n{turn.title}\n{turn.detail}")
        return 0
    except (ConfigError, RepoError, runner.PipelineBusy) as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
