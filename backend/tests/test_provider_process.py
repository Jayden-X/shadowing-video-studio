import asyncio
import ctypes
import os
import sys
import time
from pathlib import Path

import pytest

from shadowing_video_studio.providers import process as process_module
from shadowing_video_studio.providers.process import SubprocessRunner
from shadowing_video_studio.text_processing import MAX_OUTPUT_BYTES, PreparationError


class FakeInput:
    def __init__(self, ready):
        self.ready = ready
        self.content = b""
        self.closed = False

    def write(self, content):
        self.content += content
        self.ready.set()

    async def drain(self):
        return None

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", finished=False):
        self.pid = 987654321
        self.returncode = 0 if finished else None
        self.ended = asyncio.Event()
        self.started = asyncio.Event()
        self.stdin = FakeInput(self.started)
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stderr.feed_data(stderr)
        self.killed = False
        self.wait_count = 0
        if finished:
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.ended.set()

    def kill(self):
        self.killed = True
        self.returncode = -1
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.ended.set()

    async def wait(self):
        self.wait_count += 1
        await self.ended.wait()
        return self.returncode


def install_process(monkeypatch, item):
    calls = []

    async def spawn(*arguments, **options):
        calls.append((arguments, options))
        if arguments[0] == "taskkill":
            item.kill()
            return FakeProcess(finished=True)
        return item

    monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", spawn)

    class FakeJob:
        def attach_and_resume(self, _pid):
            pass

        def close(self):
            if item.returncode is None:
                item.kill()

    monkeypatch.setattr(process_module, "WindowsJob", FakeJob)
    monkeypatch.setattr(
        process_module.os, "killpg", lambda _pid, _signal: item.kill(), raising=False
    )
    return calls


def test_runner_never_uses_shell_and_preserves_stdin(monkeypatch, tmp_path):
    async def scenario():
        item = FakeProcess(b"safe output", b"safe diagnostic", finished=True)
        calls = install_process(monkeypatch, item)
        result = await SubprocessRunner().run(
            ["synthetic-cli", "fixed argument"],
            cwd=tmp_path,
            environment={"PATH": "bin"},
            timeout=1,
            source=b"$(not-a-shell-command)",
        )
        assert result.stdout == b"safe output"
        assert item.stdin.content == b"$(not-a-shell-command)"
        assert item.stdin.closed
        assert calls[0][0] == ("synthetic-cli", "fixed argument")
        assert "shell" not in calls[0][1]

    asyncio.run(scenario())


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended process ownership")
def test_windows_assignment_failure_reaps_without_sending_source(monkeypatch, tmp_path):
    async def scenario():
        item = FakeProcess()
        install_process(monkeypatch, item)

        class BlockedJob:
            def attach_and_resume(self, _pid):
                raise OSError("Synthetic nested job policy failure")

            def close(self):
                item.kill()

        monkeypatch.setattr(process_module, "WindowsJob", BlockedJob)
        with pytest.raises(OSError):
            await SubprocessRunner().run(
                ["synthetic-cli"], cwd=tmp_path, environment={}, timeout=1, source=b"Private source"
            )
        assert item.stdin.content == b"" and item.stdin.closed
        assert item.killed and item.wait_count >= 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "stdout,stderr,inspect",
    [
        (b"x" * (MAX_OUTPUT_BYTES + 1), b"", False),
        (b"x" * 70000, b"x" * 70000, False),
        (b'{"type":"item.started","item":{"type":"command_execution"}}\n', b"", True),
        (b"invalid event\n", b"", True),
    ],
    ids=["stdout-overflow", "combined-overflow", "tool-event", "malformed-event"],
)
def test_overflow_or_unexpected_events_kill_and_reap_process(
    monkeypatch, tmp_path, stdout, stderr, inspect
):
    async def scenario():
        item = FakeProcess(stdout, stderr)
        install_process(monkeypatch, item)
        with pytest.raises(PreparationError):
            await SubprocessRunner().run(
                ["synthetic-cli"],
                cwd=tmp_path,
                environment={},
                timeout=1,
                inspect_events=inspect,
            )
        assert item.killed and item.returncode is not None
        assert item.wait_count >= 1

    asyncio.run(scenario())


def test_real_process_success_preserves_stdin(tmp_path):
    result = asyncio.run(
        SubprocessRunner().run(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            cwd=tmp_path,
            environment=dict(os.environ),
            timeout=5,
            source=b"exact source",
        )
    )
    assert result.returncode == 0 and result.stdout == b"exact source"


def test_real_process_accepts_bounded_async_stdin_chunks(tmp_path):
    async def scenario():
        async def source():
            yield b"first "
            yield b"second"

        return await SubprocessRunner().run(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            cwd=tmp_path,
            environment=dict(os.environ),
            timeout=5,
            source_stream=source(),
        )

    result = asyncio.run(scenario())
    assert result.returncode == 0 and result.stdout == b"first second"


def test_real_exited_parent_cannot_leave_child_holding_pipes(tmp_path, monkeypatch):
    # Parent exits successfully while a child retains both inherited output pipes.
    child_file = tmp_path / "child.pid"
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import os,sys,subprocess; from pathlib import Path; sys.stdin.buffer.read(); "
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]]); "
        "Path(sys.argv[1]).write_text(str(child.pid)); os._exit(0)"
    )
    spawned = []
    original_spawn = asyncio.create_subprocess_exec

    async def capture(*arguments, **options):
        item = await original_spawn(*arguments, **options)
        spawned.append(item)
        return item

    monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", capture)

    async def scenario():
        with pytest.raises(TimeoutError):
            await SubprocessRunner().run(
                [sys.executable, "-c", parent_code, str(child_file), child_code],
                cwd=tmp_path,
                environment=dict(os.environ),
                timeout=2,
                source=b"start",
            )
        assert spawned[0].returncode == 0
        assert child_file.is_file()
        pid = int(child_file.read_text())
        if os.name == "nt":
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            api.OpenProcess.restype = ctypes.c_void_p
            api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            api.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if handle:
                try:
                    assert api.WaitForSingleObject(handle, 1000) == 0
                finally:
                    api.CloseHandle(handle)
        else:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                proc_state = Path(f"/proc/{pid}/stat")
                if proc_state.exists() and proc_state.read_text().split()[2] == "Z":
                    break  # Exited; the OS owns reaping this now-orphaned process.
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Owned subprocess child survived cleanup")

    asyncio.run(scenario())


def test_deadline_kills_and_reaps_process(monkeypatch, tmp_path):
    async def scenario():
        item = FakeProcess()
        install_process(monkeypatch, item)
        with pytest.raises(TimeoutError):
            await SubprocessRunner().run(
                ["synthetic-cli"], cwd=tmp_path, environment={}, timeout=0.01
            )
        assert item.killed
        assert item.wait_count >= 1

    asyncio.run(scenario())


def test_caller_cancellation_kills_and_reaps_process(monkeypatch, tmp_path):
    async def scenario():
        item = FakeProcess()
        install_process(monkeypatch, item)
        task = asyncio.create_task(
            SubprocessRunner().run(
                ["synthetic-cli"],
                cwd=Path(tmp_path),
                environment={},
                timeout=30,
                source=b"Source",
            )
        )
        await item.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert item.killed and item.stdin.closed
        assert item.wait_count >= 1

    asyncio.run(scenario())
