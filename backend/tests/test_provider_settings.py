import asyncio

from shadowing_video_studio.provider_settings import ProviderSettings
from shadowing_video_studio.providers.deepseek import DeepSeekTextProvider


def test_invalid_deepseek_model_does_not_disable_codex_configuration():
    settings = ProviderSettings.from_environment({"DEEPSEEK_MODEL": "invalid model"})
    assert settings.error is None
    assert settings.deepseek_error
    assert not asyncio.run(DeepSeekTextProvider(settings).availability()).available


def test_invalid_common_timeout_is_an_error_for_all_adapters():
    settings = ProviderSettings.from_environment({"TEXT_PROVIDER_TIMEOUT_SECONDS": "0"})
    assert settings.error
    assert settings.deepseek_error is None
