import io
import logging
import os
import threading
from contextlib import redirect_stderr, redirect_stdout

from app.config import Settings
from app.errors import ServiceError
from app.services.audio_encoder import encode_audio, validate_wav
from app.services.model_assets import acoustic_paths
from app.services.voice_map import available_voices, resolve_voice

logger = logging.getLogger("speech")


def text_segments(text: str) -> list[str]:
    """Keep each BERT input below its position limit, including unpunctuated text."""
    segments = []
    while len(text) > 200:
        cut = max(text.rfind(separator, 0, 200) for separator in " ，。！？,.!?;")
        cut = cut + 1 if cut >= 100 else 200
        segments.append(text[:cut])
        text = text[cut:]
    if text:
        segments.append(text)
    return segments


class MeloEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.models: dict = {}
        self.lock = threading.RLock()
        self.tts_class = None

    def _initialize(self):
        if self.tts_class is not None:
            return
        os.environ["HF_HOME"] = self.settings.hf_home
        os.environ["XDG_CACHE_HOME"] = self.settings.xdg_cache_home
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        os.environ["DO_NOT_TRACK"] = "1"
        os.environ["OMP_NUM_THREADS"] = str(self.settings.tts_cpu_threads)
        os.environ["MKL_NUM_THREADS"] = str(self.settings.tts_cpu_threads)
        import torch

        torch.set_num_threads(self.settings.tts_cpu_threads)
        torch.set_num_interop_threads(self.settings.tts_interop_threads)
        from melo.api import TTS

        self.tts_class = TTS

    def _load(self, language: str):
        if language not in self.models:
            try:
                self._initialize()
                paths = acoustic_paths(language)
                model = self.tts_class(
                    language=language,
                    device="cpu",
                    config_path=paths["config.json"],
                    ckpt_path=paths["checkpoint.pth"],
                )
                for voice in available_voices({language}):
                    if voice.speaker not in model.hps.data.spk2id:
                        raise ValueError("Pinned configuration is missing a configured voice")
            except Exception as exc:
                logger.error(
                    "model_load_failed",
                    extra={
                        "language": language,
                        "error_type": type(exc).__name__,
                    },
                )
                raise ServiceError(503, "Model initialization failed.", "model_not_ready") from exc
            self.models[language] = model
        return self.models[language]

    def _wav(self, text: str, voice_id: str, speed: float) -> bytes:
        import numpy as np
        import soundfile as sf

        voice = resolve_voice(voice_id, set(self.settings.tts_languages.split(",")))
        model = self._load(voice.language)
        parts = []
        for segment in text_segments(text):
            audio = model.tts_to_file(
                segment,
                model.hps.data.spk2id[voice.speaker],
                output_path=None,
                speed=speed,
                quiet=True,
            )
            if audio is None or audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
                raise ServiceError(503, "The engine produced invalid audio.", "invalid_audio")
            parts.append(audio)
        audio = np.concatenate(parts)
        output = io.BytesIO()
        sf.write(output, audio, model.hps.data.sampling_rate, format="WAV", subtype="PCM_16")
        return output.getvalue()

    def synthesize(self, text: str, voice: str, speed: float, fmt: str) -> bytes:
        # Upstream has module-level BERT caches; serialize both loading and inference.
        # quiet=True plus discarded upstream output prevents phonemizer diagnostics
        # and assertion messages from exposing text. Never log exception messages.
        with self.lock, open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            wav = self._wav(text, voice, speed)
            return encode_audio(wav, fmt, self.settings.tts_encode_timeout_seconds)

    def warmup(self):
        for language in self.settings.tts_preload_languages.split(","):
            voice, phrase = (
                ("zh", "你好，语音服务已经准备好了。")
                if language == "ZH"
                else ("en-us", "The speech service is ready.")
            )
            validate_wav(self.synthesize(phrase, voice, 1.0, "wav"))
            logger.info("language_warmed", extra={"language": language})
