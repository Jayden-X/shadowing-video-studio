"""Lazy reusable Qwen CPU adapter with a bounded, owned worker process."""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from shadowing_video_studio.providers.process import SubprocessRunner
from shadowing_video_studio.providers.windows_job import WindowsJob
from shadowing_video_studio.speech import SpeechError, SpeechReadiness
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_settings import SpeechSettings

WORKER = Path(__file__).with_name("qwen_worker.py")


def runtime_environment(runtime: Path | None = None) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}
    }
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "OMP_NUM_THREADS": "4",
        }
    )
    if runtime:
        environment.update(
            {
                "HOME": str(runtime),
                "USERPROFILE": str(runtime),
                "TMPDIR": str(runtime),
                "TMP": str(runtime),
                "TEMP": str(runtime),
                "XDG_CACHE_HOME": str(runtime / "cache"),
                "HF_HOME": str(runtime / "cache" / "huggingface"),
                "TORCH_HOME": str(runtime / "cache" / "torch"),
            }
        )
    return environment


class QwenSpeechProvider:
    def __init__(self, settings: SpeechSettings, assets: SpeechAssets | None = None) -> None:
        self._settings = settings
        self._assets = assets
        self._process: asyncio.subprocess.Process | None = None
        self._job: WindowsJob | None = None
        self._lock = asyncio.Lock()

    @property
    def fingerprint(self) -> str:
        return self._settings.fingerprint()

    def _executable(self) -> str:
        path = shutil.which(self._settings.python_executable)
        if not path or Path(path).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            raise SpeechError("Configure the existing speech runtime Python executable.", 503)
        return path

    async def readiness(self) -> SpeechReadiness:
        try:
            workspace, _ = self._settings.validated_paths()
            result = await SubprocessRunner().run(
                [self._executable(), "-I", "-B", str(WORKER), "probe"],
                cwd=workspace,
                environment=runtime_environment(),
                timeout=10,
            )
            payload = json.loads(result.stdout)
            if result.returncode or payload != {"available": True}:
                raise SpeechError(
                    "Use the validated Python 3.12 Qwen 0.1.1 CPU runtime "
                    "with torch/torchaudio 2.10.0.",
                    503,
                )
            return SpeechReadiness(True)
        except SpeechError as exc:
            return SpeechReadiness(False, exc.detail)
        except Exception:
            return SpeechReadiness(
                False, "Speech runtime readiness could not be checked. Check its configuration."
            )

    async def _start(self) -> asyncio.subprocess.Process:
        if self._process and self._process.returncode is None:
            return self._process
        await self._stop()
        _, model = self._settings.validated_paths()
        if not self._assets:
            raise SpeechError("Configure the speech workspace before generating audio.", 503)
        runtime = self._assets.runtime_directory()
        job = WindowsJob() if os.name == "nt" else None
        options = {"start_new_session": True}
        if job:
            options = {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                | 4
                | subprocess.CREATE_NO_WINDOW
            }
        try:
            process = await asyncio.create_subprocess_exec(
                self._executable(),
                "-I",
                "-B",
                str(WORKER),
                "serve",
                str(model),
                str(runtime),
                cwd=runtime,
                env=runtime_environment(runtime),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=4096,
                **options,
            )
            self._process = process
            self._job = job
            if job:
                job.attach_and_resume(process.pid)
            return process
        except BaseException:
            if job:
                job.close()
            await self._stop()
            raise

    async def generate(self, text: str, destination: Path) -> None:
        async with self._lock:
            try:
                async with asyncio.timeout(self._settings.timeout_seconds):
                    process = await self._start()
                    assert process.stdin and process.stdout
                    request = (
                        json.dumps({"text": text, "destination": str(destination)}).encode() + b"\n"
                    )
                    if len(request) > 65536:
                        raise SpeechError(
                            "Split this sentence into shorter sentences before generating speech."
                        )
                    process.stdin.write(request)
                    await process.stdin.drain()
                    raw = await process.stdout.readline()
                    if len(raw) > 4096 or not raw.endswith(b"\n"):
                        raise ValueError
                    result = json.loads(raw)
                    if result == {"ok": False, "error": "incomplete"}:
                        raise SpeechError(
                            "Speech did not finish normally. Split this sentence and try again."
                        )
                    if result == {"ok": False, "error": "generation"}:
                        raise SpeechError(
                            "Speech generation failed. Check the local runtime and try again."
                        )
                    if result != {"ok": True}:
                        raise ValueError
            except asyncio.CancelledError:
                await self._stop()
                raise
            except TimeoutError as exc:
                await self._stop()
                raise SpeechError(
                    "Speech timed out. Split the sentence or increase its configured timeout.", 504
                ) from exc
            except SpeechError:
                raise
            except (OSError, ValueError, TypeError, RecursionError) as exc:
                await self._stop()
                raise SpeechError(
                    "The speech worker stopped unexpectedly. Check the runtime and try again."
                ) from exc

    async def _stop(self) -> None:
        process, self._process = self._process, None
        if self._job:
            self._job.close()
            self._job = None
        if process:
            if process.stdin:
                process.stdin.close()

            async def drain() -> None:
                if process.stdout:
                    while await process.stdout.read(4096):
                        pass

            # Drain even rejected/oversized protocol output while killing. A
            # paused pipe must not keep asyncio Process.wait pending forever.
            await asyncio.gather(SubprocessRunner._stop(process), drain())

    async def close(self) -> None:
        await self._stop()
