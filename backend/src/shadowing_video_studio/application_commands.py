"""Generation commands shared by HTTP and MCP; adapters never launch media processes."""

from shadowing_video_studio.generation_requests import SpeechJobRequest, VideoJobRequest
from shadowing_video_studio.speech import SpeechSentence
from shadowing_video_studio.speech_jobs import SpeechJobs
from shadowing_video_studio.video_jobs import VideoJobs, VideoSentenceSelection


async def submit_speech(service: SpeechJobs, payload: SpeechJobRequest) -> dict:
    return await service.submit(
        [SpeechSentence(item.id, item.text) for item in payload.sentences],
        payload.force,
        payload.voice,
        payload.configurationFingerprint,
    )


async def submit_video(service: VideoJobs, payload: VideoJobRequest) -> dict:
    return await service.submit(
        [
            VideoSentenceSelection(item.id, item.text, item.assetId, item.illustrationAssetId)
            for item in payload.sentences
        ],
        background_asset_id=payload.backgroundAssetId,
        voice=payload.voice,
        configuration_fingerprint=payload.configurationFingerprint,
    )


async def speech_capabilities(service: SpeechJobs) -> dict:
    item = await service.capabilities()
    return {
        "available": item.available,
        "reason": item.reason,
        "defaultVoice": item.default_voice,
        "model": item.model,
        "language": item.language,
        "voices": [
            {
                "id": voice.id,
                "label": voice.label,
                "configurationFingerprint": voice.configuration_fingerprint,
            }
            for voice in item.voices
        ],
    }
