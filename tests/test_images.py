import io

import pytest
from PIL import Image

from bulten import images
from tests.fakes import FakeImageBackend


def test_generate_images_saves_resized_png_and_prompts(tmp_path, base_cfg):
    saved, errors = images.generate_images(["a", "b", "c", "d"], tmp_path, base_cfg, FakeImageBackend())
    assert len(saved) == 3 and errors == []
    assert Image.open(saved[0]).size == (1280, 720)
    text = (tmp_path / "prompts.txt").read_text(encoding="utf-8")
    assert "no logos" in text and base_cfg["images"]["style"] in text


def test_generate_images_one_failure_continues(tmp_path, base_cfg):
    saved, errors = images.generate_images(["a", "b", "c"], tmp_path, base_cfg, FakeImageBackend(fail_on={2}))
    assert [p[-6:] for p in saved] == ["01.png", "03.png"] and len(errors) == 1


def test_create_backend_errors(base_cfg):
    with pytest.raises(images.ImageGenerationError):
        images.create_backend({**base_cfg, "images": {**base_cfg["images"], "provider": "x"}})
    with pytest.raises(images.ImageGenerationError, match="FAL_KEY"):
        images.create_backend({**base_cfg, "images": {**base_cfg["images"], "provider": "fal"}})


def test_flux_local_without_gpu_gives_clear_error(base_cfg):
    try:
        import torch

        if torch.cuda.is_available():
            pytest.skip("GPU mevcut; bu test GPU'suz ortam içindir")
    except ImportError:
        pass
    with pytest.raises(images.ImageGenerationError):
        images.create_backend(base_cfg)


def test_fal_backend(monkeypatch, base_cfg):
    import fal_client

    buf = io.BytesIO()
    Image.new("RGB", (1280, 720)).save(buf, format="PNG")
    captured = {}

    def subscribe(model, arguments):
        captured.update(model=model, **arguments)
        return {"images": [{"url": "https://img"}]}

    class Resp:
        content = buf.getvalue()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fal_client, "subscribe", subscribe)
    monkeypatch.setattr(images.requests, "get", lambda *a, **k: Resp())
    cfg = {**base_cfg, "images": {**base_cfg["images"], "provider": "fal"}, "env": {"FAL_KEY": "k"}}
    img = images.create_backend(cfg).generate("p")
    assert img.size == (1280, 720)
    assert captured["model"] == "fal-ai/flux/schnell"
    assert captured["image_size"] == {"width": 1280, "height": 720}
