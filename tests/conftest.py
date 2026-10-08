import copy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def base_cfg() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    cfg = copy.deepcopy(raw)
    cfg["feeds"] = ["https://example.com/rss"]
    cfg["env"] = {"DEEPSEEK_API_KEY": "test-key", "FAL_KEY": None}
    return cfg


@pytest.fixture
def write_cfg(tmp_path, base_cfg):
    def _write(overrides: dict | None = None) -> Path:
        data = {k: v for k, v in base_cfg.items() if k != "env"}
        for key, value in (overrides or {}).items():
            data[key] = value
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return path

    return _write
