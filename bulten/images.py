"""Görsel üretimi: FLUX.1-schnell (yerel GPU) | fal.ai (API)."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any, Protocol

import requests
from PIL import Image

from bulten.utils import ensure_dir, write_text

logger = logging.getLogger(__name__)

SAFETY_SUFFIX = "no text, no letters, no watermark, no logos, no brands, no real or identifiable faces"
DOWNLOAD_TIMEOUT = 60
SEQUENTIAL_OFFLOAD_BELOW_GB = 30


class ImageGenerationError(Exception):
    """Görsel üretimi yapılamadığında (örn. GPU yok) fırlatılır."""


class ImageBackend(Protocol):
    def generate(self, prompt: str) -> Image.Image: ...


def configure_size(backend: Any, width: int, height: int) -> None:
    """Aynı model (yükleme maliyeti yüksek) yatay ve dikey formatta yeniden kullanılır."""
    if hasattr(backend, "set_size"):
        backend.set_size(width, height)


def build_prompt(prompt: str, style: str) -> str:
    parts = [prompt.strip().rstrip("."), style.strip(), SAFETY_SUFFIX]
    return ", ".join(p for p in parts if p)


class FluxLocalBackend:
    """diffusers FluxPipeline; model bir kez yüklenir, tüm görsellerde kullanılır."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        try:
            import torch
            from diffusers import FluxPipeline
        except ImportError as exc:
            raise ImageGenerationError(
                "GPU kütüphaneleri kurulu değil: 'pip install -r requirements-gpu.txt' çalıştırın "
                "ya da images.provider=fal'a geçin."
            ) from exc
        if not torch.cuda.is_available():
            raise ImageGenerationError(
                "GPU bulunamadı; images.provider=fal'a geç ya da GPU'lu ortamda çalıştır."
            )
        icfg = cfg["images"]
        self._torch = torch
        self._width, self._height = int(icfg["width"]), int(icfg["height"])
        self._steps = int(icfg.get("steps", 4))
        logger.info("FLUX modeli yükleniyor: %s (ilk seferde indirme uzun sürebilir)", icfg["model_id"])
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        self._pipe = FluxPipeline.from_pretrained(icfg["model_id"], torch_dtype=dtype)
        total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        if total_gb < SEQUENTIAL_OFFLOAD_BELOW_GB:
            # T4/L4: ~24 GB'lık transformer tek parça sığmaz; katman katman taşınır (yavaş ama çalışır).
            self._pipe.enable_sequential_cpu_offload()
            logger.info("VRAM %.0f GB: enable_sequential_cpu_offload açık (yavaş mod).", total_gb)
        elif total_gb < 40:
            self._pipe.enable_model_cpu_offload()
            logger.info("VRAM %.0f GB: enable_model_cpu_offload açık.", total_gb)
        else:
            self._pipe.to("cuda")

    def set_size(self, width: int, height: int) -> None:
        self._width, self._height = int(width), int(height)

    def generate(self, prompt: str) -> Image.Image:
        result = self._pipe(
            prompt,
            num_inference_steps=self._steps,
            width=self._width,
            height=self._height,
            guidance_scale=0.0,
            max_sequence_length=256,
        )
        return result.images[0]


class FalBackend:
    """fal.ai Flux schnell API; dönen URL'yi indirir."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        key = (cfg.get("env") or {}).get("FAL_KEY")
        if not key:
            raise ImageGenerationError("images.provider=fal için .env içinde FAL_KEY gerekli.")
        os.environ.setdefault("FAL_KEY", key)
        import fal_client

        icfg = cfg["images"]
        self._fal = fal_client
        self._model = icfg.get("fal_model", "fal-ai/flux/schnell")
        self._size = {"width": int(icfg["width"]), "height": int(icfg["height"])}
        self._steps = int(icfg.get("steps", 4))

    def set_size(self, width: int, height: int) -> None:
        self._size = {"width": int(width), "height": int(height)}

    def generate(self, prompt: str) -> Image.Image:
        result = self._fal.subscribe(
            self._model,
            arguments={
                "prompt": prompt,
                "image_size": self._size,
                "num_inference_steps": self._steps,
                "num_images": 1,
                "enable_safety_checker": True,
            },
        )
        url = result["images"][0]["url"]
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")


def create_backend(cfg: dict[str, Any]) -> ImageBackend:
    provider = cfg["images"]["provider"]
    if provider == "flux_local":
        return FluxLocalBackend(cfg)
    if provider == "fal":
        return FalBackend(cfg)
    raise ImageGenerationError(f"Bilinmeyen images.provider: {provider}")


def generate_images(
    prompts: list[str], out_dir: str | Path, cfg: dict[str, Any], backend: ImageBackend
) -> tuple[list[str], list[str]]:
    """Promptlardan PNG üretir. (kaydedilen yollar, hata mesajları) döndürür."""
    icfg = cfg["images"]
    target = ensure_dir(out_dir)
    count = int(icfg.get("count_per_item", 3))
    full_prompts = [build_prompt(p, icfg.get("style", "")) for p in prompts[:count]]
    size = (int(icfg["width"]), int(icfg["height"]))

    saved: list[str] = []
    errors: list[str] = []
    for idx, prompt in enumerate(full_prompts, start=1):
        path = target / f"{idx:02d}.png"
        try:
            image = backend.generate(prompt)
            if image.size != size:
                image = image.resize(size, Image.LANCZOS)
            image.save(path, format="PNG")
            saved.append(str(path))
            logger.info("  görsel %d/%d kaydedildi", idx, len(full_prompts))
        except Exception as exc:  # noqa: BLE001 — tek görsel hatası diğerlerini durdurmamalı
            logger.error("  görsel %d üretilemedi: %s", idx, exc)
            errors.append(f"{idx:02d}: {exc}")

    write_text(
        target / "prompts.txt",
        "\n\n".join(f"{i:02d}: {p}" for i, p in enumerate(full_prompts, start=1)) + "\n",
    )
    return saved, errors
