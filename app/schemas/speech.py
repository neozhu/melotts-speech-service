import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_text(text: str) -> str:
    text = "".join(" " if unicodedata.category(char).startswith("C") else char for char in text)
    return re.sub(r"\s+", " ", text).strip()


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model: str
    input: str
    voice: str | None = None
    response_format: str = "mp3"
    speed: float = Field(default=1.0, ge=0.25, le=4.0, allow_inf_nan=False)

    @field_validator("speed", mode="before")
    @classmethod
    def numeric_speed(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("speed must be numeric")
        return value

    @field_validator("input")
    @classmethod
    def text(cls, value: str) -> str:
        # Bound raw content too: repeated whitespace must not bypass the resource cap.
        if len(value) > 1000:
            raise ValueError("input exceeds the absolute length limit")
        value = normalize_text(value)
        if not value or not any(char.isalnum() for char in value):
            raise ValueError("input must contain spoken text")
        return value
