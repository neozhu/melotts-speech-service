from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", hide_input_in_errors=True)

    api_key: SecretStr = SecretStr("")
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    tts_languages: str = "ZH,EN"
    tts_preload_languages: str = "ZH"
    tts_default_voice: str = "zh"
    tts_max_text_length: int = Field(default=500, ge=1, le=1000)
    tts_max_concurrency: int = Field(default=1, ge=1, le=1)
    tts_max_queue: int = Field(default=4, ge=0, le=4)
    tts_queue_timeout_seconds: float = Field(default=120, gt=0, le=3600)
    tts_encode_timeout_seconds: float = Field(default=30, gt=0, le=300)
    tts_cpu_threads: int = Field(default=4, ge=1, le=6)
    tts_interop_threads: int = Field(default=1, ge=1, le=1)
    hf_home: str = "/data/hf"
    xdg_cache_home: str = "/data/cache"
    log_level: str = "INFO"

    @field_validator("tts_languages", "tts_preload_languages")
    @classmethod
    def languages(cls, value: str) -> str:
        values = list(dict.fromkeys(part.strip().upper() for part in value.split(",")))
        if not values or any(part not in {"ZH", "EN"} for part in values):
            raise ValueError("languages must be a comma-separated subset of ZH,EN")
        return ",".join(values)

    @field_validator("log_level")
    @classmethod
    def level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid log level")
        return value

    @model_validator(mode="after")
    def consistent_languages(self):
        from app.services.voice_map import resolve_voice

        enabled = set(self.tts_languages.split(","))
        preloaded = set(self.tts_preload_languages.split(","))
        if "ZH" not in enabled or "ZH" not in preloaded:
            raise ValueError("ZH must be enabled and preloaded for Mandarin readiness")
        if not preloaded <= enabled:
            raise ValueError("preloaded languages must be enabled")
        try:
            self.tts_default_voice = resolve_voice(self.tts_default_voice, enabled).id
        except ValueError as exc:
            raise ValueError("default voice must be enabled") from exc
        return self
