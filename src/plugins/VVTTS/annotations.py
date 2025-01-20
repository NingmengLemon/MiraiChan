# based on core 0.15.7, engine 0.22.2

from typing import Literal, TypedDict


class Style(TypedDict):
    name: str
    id: int  # used as `speaker` in api
    type: Literal["talk", "frame_decode"]


class Speaker(TypedDict):
    name: str
    speaker_uuid: str
    styles: list[Style]
    version: str
    supported_features: dict[str, str]


class Mora(TypedDict):
    text: str
    consonant: str
    consonant_length: float
    vowel: str
    vowel_length: float
    pitch: float


class AccentPhrase(TypedDict):
    moras: list[Mora]
    accent: int
    pause_mora: Mora | None
    is_interrogative: bool


class AudioQueryResult(TypedDict):
    accent_phrases: list[AccentPhrase]
    speedScale: float
    pitchScale: float
    intonationScale: float
    volumeScale: float
    prePhonemeLength: float
    postPhonemeLength: float
    pauseLength: float | None
    pauseLengthScale: float
    outputSamplingRate: int
    outputStereo: bool
    kana: str
