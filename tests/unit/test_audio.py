import io
import subprocess
import wave
from unittest.mock import Mock

import pytest

from app.errors import ServiceError
from app.services.audio_encoder import encode_audio, validate_wav


def make_wav(frames=b"\x01\x10" * 2400):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(frames)
    return output.getvalue()


def test_wav_passthrough():
    audio = make_wav()
    assert encode_audio(audio, "wav", 30) == audio
    assert validate_wav(audio) == pytest.approx(0.1)


@pytest.mark.parametrize("audio", [b"bad", make_wav(b""), make_wav(b"\x00\x00" * 200)])
def test_invalid_or_silent_wav(audio):
    with pytest.raises(ServiceError):
        validate_wav(audio)


def test_mp3_subprocess_is_bounded_and_uses_no_shell(monkeypatch):
    runner = Mock(return_value=Mock(stdout=b"ID3" + b"x" * 100, returncode=0))
    monkeypatch.setattr(subprocess, "run", runner)
    audio = make_wav()
    assert encode_audio(audio, "mp3", 17).startswith(b"ID3")
    args, kwargs = runner.call_args
    assert isinstance(args[0], list)
    assert kwargs["timeout"] == 17
    assert kwargs["input"] == audio
    assert not kwargs.get("shell", False)


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("ffmpeg", 1),
        FileNotFoundError("secret path"),
        subprocess.CalledProcessError(1, "ffmpeg", stderr=b"private text"),
    ],
)
def test_encoder_errors_are_sanitized(monkeypatch, failure):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(ServiceError) as error:
        encode_audio(make_wav(), "mp3", 1)
    assert error.value.status == 503
    assert "private text" not in error.value.message


def test_bad_mp3_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", Mock(return_value=Mock(stdout=b"not mp3")))
    with pytest.raises(ServiceError):
        encode_audio(make_wav(), "mp3", 1)
