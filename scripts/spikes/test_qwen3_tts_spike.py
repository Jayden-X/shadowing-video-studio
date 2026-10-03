"""Deterministic spike checks; no Qwen/PyTorch imports, downloads, or paid requests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qwen3_tts_macos import (
    SYNTHETIC_TEXT,
    VOICE,
    SpeechAudio,
    audio_statistics,
    new_run_directory,
    require_target,
    snapshot_path,
    synthesize_sample,
    write_json,
)
from qwen3_tts_workspace import checked_child, checked_workspace, runtime_environment


class SpikeChecks(unittest.TestCase):
    def setUp(self) -> None:
        test_root = Path(__file__).resolve().parent / "tmp" / "helper-tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self._temporary.cleanup)
        self.workspace = Path(self._temporary.name).resolve()

    def test_requires_native_mac(self) -> None:
        require_target("Darwin", "arm64")
        for system, machine in (("Windows", "AMD64"), ("Darwin", "x86_64")):
            with self.subTest(system=system), self.assertRaises(ValueError):
                require_target(system, machine)

    def test_workspace_requires_absolute_existing_directory(self) -> None:
        self.assertEqual(checked_workspace(str(self.workspace)), self.workspace)
        for value in ("relative/workspace", str(self.workspace / "missing"), "invalid\npath"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_workspace(value)

    def test_workspace_identity_uses_samefile_for_case_insensitive_volumes(self) -> None:
        with patch("qwen3_tts_workspace.os.path.samefile", return_value=True) as samefile:
            self.assertEqual(checked_workspace(str(self.workspace)), self.workspace)
        samefile.assert_called_once_with(self.workspace, self.workspace)

    def test_child_rejects_root_and_escape(self) -> None:
        allowed = self.workspace / "owned" / "output"
        self.assertEqual(checked_child(self.workspace, allowed), allowed)
        for candidate in (self.workspace, self.workspace.parent / "outside"):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                checked_child(self.workspace, candidate)

    def test_child_rejects_symlink_escape(self) -> None:
        outside = self.workspace.parent
        link = self.workspace / "outside-link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"This Windows account cannot create symlinks: {type(error).__name__}")
        with self.assertRaises(ValueError):
            checked_child(self.workspace, link / "generated")
        with self.assertRaises(ValueError):
            checked_workspace(str(link))

    def test_all_runtime_cache_paths_stay_inside_workspace(self) -> None:
        environment = runtime_environment(self.workspace)
        for name, value in environment.items():
            if name.endswith(("_DIR", "_HOME", "_CACHE", "TMPDIR")):
                with self.subTest(name=name):
                    self.assertTrue(Path(value).is_relative_to(self.workspace))
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(environment["HF_HUB_DISABLE_IMPLICIT_TOKEN"], "1")

    def test_model_snapshot_rejects_escape(self) -> None:
        runtime = self.workspace / "runtime"
        runtime.mkdir()
        expected = runtime / "model-cache" / "snapshot"
        self.assertEqual(snapshot_path(self.workspace, runtime, "model-cache/snapshot"), expected)
        for relative in ("../outside", "output/model", str(self.workspace.parent)):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                snapshot_path(self.workspace, runtime, relative)

    def test_results_do_not_overwrite_existing_evidence(self) -> None:
        first = new_run_directory(self.workspace)
        second = new_run_directory(self.workspace)
        self.assertNotEqual(first, second)
        evidence = first / "result.json"
        write_json(evidence, {"status": "first"})
        with self.assertRaises(FileExistsError):
            write_json(evidence, {"status": "replacement"})
        self.assertIn("first", evidence.read_text(encoding="utf-8"))

    def test_audio_checks_reject_invalid_or_silent_output(self) -> None:
        for samples, rate in (([], 24000), ([0.0], 24000), ([float("nan")], 24000), ([1.0], 0)):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                audio_statistics(samples, rate)

    def test_audio_statistics_include_duration_and_amplitude(self) -> None:
        statistics = audio_statistics([0.5, -0.5], 2)
        self.assertEqual(statistics["duration_seconds"], 1)
        self.assertEqual(statistics["peak_absolute_amplitude"], 0.5)
        self.assertEqual(statistics["rms_amplitude"], 0.5)

    def test_speech_boundary_works_without_vendor_types(self) -> None:
        class FakeSpeechProvider:
            def synthesize(self, text: str, voice: str) -> SpeechAudio:
                self.request = (text, voice)
                return SpeechAudio([0.1, -0.1], 24000)

        provider = FakeSpeechProvider()
        audio = synthesize_sample(provider)
        self.assertEqual(provider.request, (SYNTHETIC_TEXT, VOICE))
        self.assertEqual(audio.sample_rate, 24000)


if __name__ == "__main__":
    unittest.main()
