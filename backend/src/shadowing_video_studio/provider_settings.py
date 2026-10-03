import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class ProviderSettings:
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    codex_executable: str = "codex"
    timeout_seconds: float = 60
    error: str | None = None
    deepseek_error: str | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        env = os.environ if environment is None else environment
        error = None
        try:
            timeout = float(env.get("TEXT_PROVIDER_TIMEOUT_SECONDS", "60"))
            if not 1 <= timeout <= 110:
                raise ValueError
        except ValueError:
            timeout = 60
            error = "Set TEXT_PROVIDER_TIMEOUT_SECONDS to a number between 1 and 110."
        model = env.get("DEEPSEEK_MODEL", "deepseek-flash").strip()
        model_error = None
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", model):
            model_error = "Set DEEPSEEK_MODEL to a valid model identifier."
        return cls(
            deepseek_api_key=env.get("DEEPSEEK_API_KEY", "").strip(),
            deepseek_model=model,
            codex_executable=env.get("CODEX_EXECUTABLE", "codex").strip() or "codex",
            timeout_seconds=timeout,
            error=error,
            deepseek_error=model_error,
        )
