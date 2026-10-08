"""Chatterbox Multilingual ile kullanıcının sesinden çok dilli seslendirme."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

SILENCE_SEC = 0.35


class VoiceError(Exception):
    """Ses üretimi yapılamadığında fırlatılır."""


def split_text(text: str, max_chars: int = 300) -> list[str]:
    """Metni cümle sınırlarından max_chars'ı aşmayan parçalara böler."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。؟!?])\s+", text.strip()) if s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        pieces = _hard_split(sentence, max_chars) if len(sentence) > max_chars else [sentence]
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def _hard_split(sentence: str, max_chars: int) -> list[str]:
    """Çok uzun cümleyi virgül/boşluklardan böler."""
    words = re.split(r"(?<=,)\s+|\s+", sentence)
    parts: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _load_model_class() -> Any:
    try:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        return ChatterboxMultilingualTTS
    except ImportError:
        pass
    try:
        from chatterbox import ChatterboxMultilingualTTS  # type: ignore[attr-defined]

        return ChatterboxMultilingualTTS
    except ImportError as exc:
        raise VoiceError(
            "Chatterbox Multilingual bulunamadı. 'pip install -r requirements-voice.txt' çalıştırın; "
            "kuruluysa paket sürümünü kontrol edin (chatterbox.mtl_tts.ChatterboxMultilingualTTS)."
        ) from exc


class VoiceSynthesizer:
    """Model bir kez yüklenir; tüm haber ve dillerde yeniden kullanılır."""

    def __init__(self, cfg: dict[str, Any], model: Any | None = None) -> None:
        vcfg = cfg["voice"]
        self.ref_audio = str(vcfg["ref_audio"])
        if not Path(self.ref_audio).exists():
            raise VoiceError(
                f"Önce kendi sesinizden bir referans kaydı '{self.ref_audio}' olarak ekleyin."
            )
        self.max_chars = int(vcfg.get("max_chars_per_chunk", 300))
        self.exaggeration = float(vcfg.get("exaggeration", 0.5))
        self.cfg_weight = float(vcfg.get("cfg_weight", 0.5))
        self._model = model or self._load(str(vcfg.get("device", "cuda")))
        self.sr = int(self._model.sr)
        # Referans sesi bir kez işle; her parçada yeniden hesaplanmasın.
        self._prompt_path: str | None = self.ref_audio
        if hasattr(self._model, "prepare_conditionals"):
            self._model.prepare_conditionals(self.ref_audio, exaggeration=self.exaggeration)
            self._prompt_path = None

    @staticmethod
    def _load(device: str) -> Any:
        model_cls = _load_model_class()
        if device == "cuda":
            import torch

            if not torch.cuda.is_available():
                raise VoiceError(
                    "GPU bulunamadı. Colab'da Runtime > Change runtime type > GPU seçin "
                    "ya da config.yaml'da voice.device: \"cpu\" yapın (çok yavaş)."
                )
        logger.info("Chatterbox Multilingual yükleniyor (%s)…", device)
        return model_cls.from_pretrained(device=device)

    def synthesize(self, text: str, lang: str) -> np.ndarray:
        chunks = split_text(text, self.max_chars)
        if not chunks:
            raise VoiceError("Seslendirilecek metin boş.")
        silence = np.zeros(int(self.sr * SILENCE_SEC), dtype=np.float32)
        parts: list[np.ndarray] = []
        for i, chunk in enumerate(chunks):
            wav = self._model.generate(
                chunk,
                language_id=lang,
                audio_prompt_path=self._prompt_path,
                exaggeration=self.exaggeration,
                cfg_weight=self.cfg_weight,
            )
            parts.append(_to_numpy(wav))
            if i < len(chunks) - 1:
                parts.append(silence)
        return np.concatenate(parts)

    def synthesize_to_file(self, text: str, lang: str, out_path: str | Path) -> Path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), self.synthesize(text, lang), self.sr)
        return path


def _to_numpy(wav: Any) -> np.ndarray:
    if hasattr(wav, "detach"):
        wav = wav.detach().cpu().numpy()
    return np.asarray(wav, dtype=np.float32).reshape(-1)
