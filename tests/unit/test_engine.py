import hashlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.errors import ServiceError
from app.services.melo_engine import MeloEngine
from app.services.model_assets import acoustic_paths, pretrained_options, verify_sha256


def test_checkpoint_integrity(tmp_path):
    path = tmp_path / "checkpoint.pth"
    path.write_bytes(b"trusted weights")
    verify_sha256(path, hashlib.sha256(b"trusted weights").hexdigest())
    path.write_bytes(b"changed weights")
    with pytest.raises(ValueError, match="checksum"):
        verify_sha256(path, hashlib.sha256(b"trusted weights").hexdigest())


def test_frontend_revision_is_immutable_and_remote_code_disabled():
    options = pretrained_options("bert-base-uncased")
    assert len(options["revision"]) == 40
    assert options["trust_remote_code"] is False
    with pytest.raises(KeyError):
        pretrained_options("attacker/model")


def test_pinned_acoustic_download_and_verification(monkeypatch, tmp_path):
    from app.services import model_assets

    path = tmp_path / "asset"
    path.write_bytes(b"weights")
    download = Mock(return_value=str(path))
    verify = Mock()
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    monkeypatch.setattr(model_assets, "verify_sha256", verify)
    assert acoustic_paths("ZH") == {"config.json": str(path), "checkpoint.pth": str(path)}
    assert verify.call_count == 2
    assert all(len(call.kwargs["revision"]) == 40 for call in download.call_args_list)


def test_cpu_model_initialized_once_and_voices_checked(monkeypatch):
    from app.services import melo_engine

    torch = Mock()
    factory = Mock(
        return_value=SimpleNamespace(hps=SimpleNamespace(data=SimpleNamespace(spk2id={"ZH": 1})))
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "melo", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "melo.api", SimpleNamespace(TTS=factory))
    monkeypatch.setattr(
        melo_engine,
        "acoustic_paths",
        Mock(
            return_value={
                "config.json": "config",
                "checkpoint.pth": "checkpoint",
            }
        ),
    )
    engine = MeloEngine(Settings())
    assert engine._load("ZH") is engine._load("ZH")
    factory.assert_called_once_with(
        language="ZH", device="cpu", config_path="config", ckpt_path="checkpoint"
    )
    torch.set_num_threads.assert_called_once_with(4)
    torch.set_num_interop_threads.assert_called_once_with(1)


def test_warmup_uses_actual_synthesis_and_validates(monkeypatch):
    from app.services import melo_engine

    engine = MeloEngine(Settings(tts_preload_languages="ZH,EN"))
    engine.synthesize = Mock(return_value=b"valid wav")
    validate = Mock()
    monkeypatch.setattr(melo_engine, "validate_wav", validate)
    engine.warmup()
    assert [call.args[1] for call in engine.synthesize.call_args_list] == ["zh", "en-us"]
    assert validate.call_count == 2


def test_lazy_model_download_failure_is_503_and_not_cached(monkeypatch):
    from app.services import melo_engine

    engine = MeloEngine(Settings())
    engine.tts_class = Mock()
    monkeypatch.setattr(melo_engine, "acoustic_paths", Mock(side_effect=OSError("private token")))
    with pytest.raises(ServiceError) as error:
        engine._load("EN")
    assert error.value.status == 503
    assert "private token" not in error.value.message
    assert "EN" not in engine.models


def test_long_text_segments_preserve_content_and_technical_tokens():
    from app.services.melo_engine import text_segments

    text = ("你好 Docker Python OpenAI API，服务正常。" * 40)[:1000]
    chunks = text_segments(text)
    assert "".join(chunks) == text
    assert all(0 < len(chunk) <= 200 for chunk in chunks)
    assert sum(chunk.count("Docker") for chunk in chunks) == text.count("Docker")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tts_max_concurrency": 2},
        {"tts_max_text_length": 1001},
        {"tts_max_queue": -1},
        {"tts_languages": "EN"},
        {"tts_preload_languages": "EN"},
        {"tts_languages": "ZH,JP"},
        {"tts_languages": "ZH", "tts_default_voice": "en-us"},
        {"tts_languages": "ZH", "tts_preload_languages": "ZH,EN"},
    ],
)
def test_invalid_configuration_fails_startup(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_configuration_error_does_not_reveal_environment_secret(monkeypatch):
    monkeypatch.setenv("API_KEY", "PRIVATE_CANARY_SECRET")
    monkeypatch.setenv("TTS_LANGUAGES", "EN")
    with pytest.raises(ValueError) as error:
        Settings()
    assert "PRIVATE" not in str(error.value)
