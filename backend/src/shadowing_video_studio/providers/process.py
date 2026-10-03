"""Bounded subprocess execution; source text is never interpreted by a shell."""

import asyncio
import json
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from shadowing_video_studio.providers.windows_job import WindowsJob
from shadowing_video_studio.text_processing import MAX_OUTPUT_BYTES, PreparationError


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


def check_codex_event(line: bytes) -> str:
    try:
        event = json.loads(line)
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError
        event_type = event["type"]
        if event_type in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict) or item.get("type") not in {"agent_message", "reasoning"}:
                raise PreparationError("Codex attempted an unexpected tool operation.")
        elif event_type not in {"thread.started", "turn.started", "turn.completed"}:
            raise PreparationError("Codex did not complete a valid text preparation run.")
        return event_type
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise PreparationError("Codex returned an invalid event stream.") from exc


class SubprocessRunner:
    async def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: float,
        source: bytes | None = None,
        inspect_events: bool = False,
    ) -> ProcessResult:
        job = WindowsJob() if os.name == "nt" else None
        options = {"start_new_session": True}
        if job:
            options = {
                "creationflags": (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | 0x00000004  # CREATE_SUSPENDED
                    | subprocess.CREATE_NO_WINDOW
                )
            }
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                cwd=cwd,
                env=dict(environment),
                stdin=asyncio.subprocess.PIPE if source is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **options,
            )
            if job:
                job.attach_and_resume(process.pid)
        except BaseException:
            if job:
                job.close()
            if process:
                if process.stdin is not None:
                    process.stdin.close()
                await self._stop(process)
            raise
        consumed = 0

        async def read(stream: asyncio.StreamReader, events: bool) -> bytes:
            nonlocal consumed
            output = bytearray()
            pending = bytearray()
            while chunk := await stream.read(4096):
                consumed += len(chunk)
                if consumed > MAX_OUTPUT_BYTES:
                    raise PreparationError("Codex returned too much output.")
                output.extend(chunk)
                if events:
                    pending.extend(chunk)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending = bytearray(rest)
                        if line.strip():
                            check_codex_event(line)
            if events and pending.strip():
                check_codex_event(pending)
            return bytes(output)

        async def write() -> None:
            if process.stdin is not None:
                try:
                    process.stdin.write(source or b"")
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()

        assert process.stdout is not None and process.stderr is not None
        tasks = [
            asyncio.create_task(read(process.stdout, inspect_events)),
            asyncio.create_task(read(process.stderr, False)),
            asyncio.create_task(write()),
            asyncio.create_task(process.wait()),
        ]
        try:
            async with asyncio.timeout(timeout):
                stdout, stderr, _, returncode = await asyncio.gather(*tasks)
            return ProcessResult(returncode, stdout, stderr)
        except BaseException:
            # Includes caller cancellation, timeout, malformed events and output overflow.
            if job:
                job.close()
            await self._stop(process)
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if job:
                job.close()

    @staticmethod
    async def _stop(process: asyncio.subprocess.Process) -> None:
        # A child may still hold pipes after its parent exits. Our dedicated group
        # remains ours until cleanup, so parent returncode must not skip it.
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
