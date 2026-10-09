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
    with pytest.raises(images.ImageGenerationError, match="HF_TOKEN"):
        images.create_backend({**base_cfg, "images": {**base_cfg["images"], "provider": "hf_api"}})


def test_flux_local_without_gpu_gives_clear_error(base_cfg):
    try:
        import torch

        if torch.cuda.is_available():
            pytest.skip("GPU mevcut; bu test GPU'suz ortam içindir")
    except ImportError:
        pass
    with pytest.raises(images.ImageGenerationError):
        images.create_backend(base_cfg)


class FakeInference:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def text_to_image(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if self.error:
            raise self.error
        return Image.new("RGBA", (kwargs["width"], kwargs["height"]))


def _hf_cfg(base_cfg):
    return {**base_cfg, "images": {**base_cfg["images"], "provider": "hf_api"}, "env": {"HF_TOKEN": "t"}}


def test_hf_api_backend_generates_with_size_and_steps(base_cfg):
    client = FakeInference()
    backend = images.HfApiBackend(_hf_cfg(base_cfg), client=client)
    backend.set_size(720, 1280)
    img = backend.generate("p")
    assert img.mode == "RGB" and img.size == (720, 1280)
    call = client.calls[0]
    assert call["model"] == base_cfg["images"]["model_id"] and call["num_inference_steps"] == base_cfg["images"]["steps"]


def test_hf_api_create_backend_uses_inference_client(monkeypatch, base_cfg):
    import huggingface_hub

    seen = {}

    class Client(FakeInference):
        def __init__(self, provider, token, timeout):
            super().__init__()
            seen.update(provider=provider, token=token)

    monkeypatch.setattr(huggingface_hub, "InferenceClient", Client)
    backend = images.create_backend(_hf_cfg(base_cfg))
    assert backend.generate("p").size == (1280, 720)
    assert seen == {"provider": "auto", "token": "t"}


@pytest.mark.parametrize(("message", "match"), [
    ("401 Client Error: Unauthorized", "erişim izni"),
    ("402 Payment Required", "kredi"),
])
def test_hf_api_errors_are_explained(base_cfg, message, match):
    backend = images.HfApiBackend(_hf_cfg(base_cfg), client=FakeInference(RuntimeError(message)))
    with pytest.raises(images.ImageGenerationError, match=match):
        backend.generate("p")


def test_hf_api_other_errors_propagate(base_cfg):
    backend = images.HfApiBackend(_hf_cfg(base_cfg), client=FakeInference(TimeoutError("yavaş")))
    with pytest.raises(TimeoutError):
        backend.generate("p")
