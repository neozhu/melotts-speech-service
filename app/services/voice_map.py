from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    id: str
    language: str
    speaker: str


VOICES = (
    Voice("zh", "ZH", "ZH"),
    Voice("en-us", "EN", "EN-US"),
    Voice("en-br", "EN", "EN-BR"),
    Voice("en-au", "EN", "EN-AU"),
    Voice("en-india", "EN", "EN_INDIA"),
    Voice("en-default", "EN", "EN-Default"),
)
ALIASES = {"alloy": "zh", "en_india": "en-india"}


def available_voices(languages: set[str]) -> list[Voice]:
    return [voice for voice in VOICES if voice.language in languages]


def resolve_voice(value: str, languages: set[str]) -> Voice:
    key = value.lower()
    key = ALIASES.get(key, key)
    for voice in available_voices(languages):
        if voice.id == key:
            return voice
    raise ValueError("unsupported voice")
