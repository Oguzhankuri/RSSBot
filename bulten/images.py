"""Görsel üretimi: FLUX.1-schnell — yerel GPU (Colab) | Hugging Face Inference API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from bulten.utils import ensure_dir, write_text

logger = logging.getLogger(__name__)

SAFETY_SUFFIX = "no text, no letters, no watermark, no logos, no brands, no real or identifiable faces"
HF_TIMEOUT = 120
SEQUENTIAL_OFFLOAD_BELOW_GB = 30


GATED_HELP = (
    "Hugging Face '{model}' modeline erişim izni yok. 1) huggingface.co/{model} sayfasında giriş yapıp "
    "'Agree and access repository' de. 2) huggingface.co/settings/tokens → 'Read' token oluştur. "
    "3) Token'ı HF_TOKEN adıyla Colab Secrets'a (PC'de .env'e) ekle. "
    "4) GPU'suz üretmek istersen config.yaml → images.provider: \"hf_api\"."
)


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
                "ya da images.provider: hf_api kullanın (GPU gerekmez)."
            ) from exc
        if not torch.cuda.is_available():
            raise ImageGenerationError(
                "GPU bulunamadı; images.provider: hf_api kullan ya da GPU'lu ortamda (Colab) çalıştır."
            )
        icfg = cfg["images"]
        self._torch = torch
        self._width, self._height = int(icfg["width"]), int(icfg["height"])
        self._steps = int(icfg.get("steps", 4))
        logger.info("FLUX modeli yükleniyor: %s (ilk seferde indirme uzun sürebilir)", icfg["model_id"])
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        try:
            self._pipe = FluxPipeline.from_pretrained(icfg["model_id"], torch_dtype=dtype)
        except Exception as exc:  # noqa: BLE001 — huggingface_hub hata sınıfları sürüme göre değişiyor
            if "gated" in type(exc).__name__.lower() or "401" in str(exc) or "403" in str(exc):
                raise ImageGenerationError(GATED_HELP.format(model=icfg["model_id"])) from exc
            raise
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


class HfApiBackend:
    """Hugging Face Inference API: GPU gerekmez, PC'de ya da sunucuda çalışır (HF_TOKEN ile)."""

    def __init__(self, cfg: dict[str, Any], client: Any | None = None) -> None:
        token = (cfg.get("env") or {}).get("HF_TOKEN")
        if not token:
            raise ImageGenerationError(
                "images.provider=hf_api için HF_TOKEN gerekli: huggingface.co/settings/tokens → token oluştur, "
                "panel → Ayarlar → Anahtarlar'a gir."
            )
        icfg = cfg["images"]
        self._model = icfg["model_id"]
        self._width, self._height = int(icfg["width"]), int(icfg["height"])
        self._steps = int(icfg.get("steps", 4))
        if client is None:
            try:
                from huggingface_hub import InferenceClient
            except ImportError as exc:
                raise ImageGenerationError("pip install -r requirements.txt (huggingface_hub eksik)") from exc
            client = InferenceClient(provider=icfg.get("hf_provider", "auto"), token=token, timeout=HF_TIMEOUT)
        self._client = client

    def set_size(self, width: int, height: int) -> None:
        self._width, self._height = int(width), int(height)

    def generate(self, prompt: str) -> Image.Image:
        try:
            image = self._client.text_to_image(
                prompt, model=self._model, width=self._width, height=self._height,
                num_inference_steps=self._steps,
            )
        except Exception as exc:  # noqa: BLE001 — huggingface_hub hata sınıfları sürüme göre değişiyor
            text = str(exc)
            if "401" in text or "403" in text:
                raise ImageGenerationError(GATED_HELP.format(model=self._model)) from exc
            if "402" in text:
                raise ImageGenerationError(
                    "Hugging Face ücretsiz aylık kredin bitti (402). Ay başını bekle, HF PRO al "
                    "ya da images.provider: flux_local (Colab GPU) kullan."
                ) from exc
            raise
        return image.convert("RGB")


def create_backend(cfg: dict[str, Any]) -> ImageBackend:
    provider = cfg["images"]["provider"]
    if provider == "flux_local":
        return FluxLocalBackend(cfg)
    if provider == "hf_api":
        return HfApiBackend(cfg)
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
