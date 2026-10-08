import pytest
import soundfile as sf

from bulten import voice
from tests.fakes import FakeChatterboxModel, FakeTTSModel


def test_split_text_respects_limit():
    text = "Birinci cümle. " * 30 + "Ve " + "çok " * 120 + "uzun cümle."
    chunks = voice.split_text(text, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_split_text_empty():
    assert voice.split_text("   ") == []


def test_missing_ref_audio(base_cfg):
    cfg = {**base_cfg, "voice": {**base_cfg["voice"], "ref_audio": "yok.wav"}}
    with pytest.raises(voice.VoiceError, match="referans"):
        voice.VoiceSynthesizer(cfg, model=FakeTTSModel())


def test_synthesize_to_file(tmp_path, base_cfg):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    cfg = {**base_cfg, "voice": {**base_cfg["voice"], "ref_audio": str(ref), "max_chars_per_chunk": 20}}
    model = FakeTTSModel()
    synth = voice.VoiceSynthesizer(cfg, model=model)
    out = synth.synthesize_to_file("Merhaba dünya. Bu bir test. Üçüncü cümle.", "en", tmp_path / "ses" / "en.wav")
    data, sr = sf.read(out)
    assert sr == 24000 and len(model.calls) == 3
    assert all(lang == "en" for _, lang in model.calls)
    assert len(data) == 3 * 2400 + 2 * int(24000 * voice.SILENCE_SEC)


def test_empty_text_raises(tmp_path, base_cfg):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    cfg = {**base_cfg, "voice": {**base_cfg["voice"], "ref_audio": str(ref)}}
    with pytest.raises(voice.VoiceError):
        voice.VoiceSynthesizer(cfg, model=FakeTTSModel()).synthesize("  ", "en")


def test_reference_prepared_once(tmp_path, base_cfg):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    cfg = {**base_cfg, "voice": {**base_cfg["voice"], "ref_audio": str(ref), "max_chars_per_chunk": 20}}
    model = FakeChatterboxModel()
    synth = voice.VoiceSynthesizer(cfg, model=model)
    synth.synthesize("Bir cümle. İki cümle. Üç cümle.", "de")
    synth.synthesize("Dört.", "ru")
    assert model.prepared == [str(ref)]
    assert set(model.prompt_paths) == {None}
