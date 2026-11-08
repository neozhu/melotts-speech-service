import io
import subprocess
import wave

from app.errors import ServiceError


def validate_wav(audio: bytes) -> float:
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            pcm = wav.readframes(frames)
            if (
                wav.getnchannels() != 1
                or wav.getsampwidth() != 2
                or rate < 8000
                or frames == 0
                or len(pcm) != frames * 2
                or not any(pcm)
            ):
                raise ValueError("invalid PCM")
            return frames / rate
    except (wave.Error, EOFError, ValueError) as exc:
        raise ServiceError(503, "The engine produced invalid audio.", "invalid_audio") from exc


def encode_audio(wav: bytes, fmt: str, timeout: float) -> bytes:
    validate_wav(wav)
    if fmt == "wav":
        return wav
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                "pipe:0",
                "-map_metadata",
                "-1",
                "-vn",
                "-threads",
                "1",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=wav,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceError(503, "Audio encoding failed.", "encoding_failed") from exc
    audio = result.stdout
    if len(audio) < 32 or not (
        audio.startswith(b"ID3") or (audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)
    ):
        raise ServiceError(503, "Audio encoder produced invalid MP3.", "encoding_failed")
    return audio
