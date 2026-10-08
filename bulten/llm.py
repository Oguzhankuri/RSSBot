"""DeepSeek (OpenAI uyumlu) istemcisi + üstel geri çekilmeli yeniden deneme."""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BASE_DELAY_SEC = 2.0
RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


class DeepSeekClient:
    """Rewrite ve çeviri modüllerinin paylaştığı ince sarmalayıcı."""

    def __init__(self, cfg: dict[str, Any], client: Any | None = None) -> None:
        rcfg = cfg["rewrite"]
        self.model: str = rcfg.get("model", "deepseek-chat")
        self._client = client or OpenAI(
            api_key=cfg["env"]["DEEPSEEK_API_KEY"],
            base_url=rcfg.get("base_url", "https://api.deepseek.com"),
            timeout=120,
        )

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                return (resp.choices[0].message.content or "").strip()
            except RETRYABLE as exc:
                if attempt == MAX_ATTEMPTS:
                    raise
                delay = BASE_DELAY_SEC * (2 ** (attempt - 1))
                logger.warning("DeepSeek hatası (%s), %.0f sn sonra tekrar (%d/%d)", exc, delay, attempt, MAX_ATTEMPTS)
                time.sleep(delay)
        raise RuntimeError("unreachable")
