"""Shared validated generation inputs for HTTP and application control."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from shadowing_video_studio.speech import MAX_SPEECH_SENTENCES, VOICE


class SentenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: StrictStr = Field(min_length=1, max_length=100)
    text: StrictStr = Field(min_length=1, max_length=4000)


class SpeechJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sentences: list[SentenceRequest] = Field(min_length=1, max_length=MAX_SPEECH_SENTENCES)
    force: StrictBool = False
    voice: StrictStr = Field(default=VOICE, min_length=1, max_length=64)
    configurationFingerprint: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class VideoSentenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: StrictStr = Field(min_length=1, max_length=100)
    text: StrictStr = Field(min_length=1, max_length=4000)
    assetId: StrictStr = Field(pattern=r"^[0-9a-f]{32}$")
    illustrationAssetId: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class VideoJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sentences: list[VideoSentenceRequest] = Field(min_length=1, max_length=MAX_SPEECH_SENTENCES)
    backgroundAssetId: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    voice: StrictStr = Field(default=VOICE, min_length=1, max_length=64)
    configurationFingerprint: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
