# 004 — Validate Qwen3-TTS on the target Mac

## Goal

De-risk the local TTS runtime with reproducible evidence from the actual target Mac before
selecting the end-user packaging strategy.

## Context

The product defaults to local Qwen3-TTS with Aiden. ADR 0001 selects Python 3.12 and a
vendor-independent `SpeechProvider`; heavy TTS dependencies remain optional and outside
normal CI. The human owner authorized the official CPU/MPS experiment and access to the
specified Mac workspace. See [Mac spike instructions](../../docs/development/qwen3-tts-macos-spike.md).

## Requirements

- Record hardware and macOS/Python/package versions without private machine identifiers.
- Install into a fresh isolated Python 3.12 environment with a reproducible hash lock.
- Freeze the full official 0.6B CustomVoice checkpoint and its speech tokenizer revision.
- Generate a short synthetic English sentence using Aiden; preserve first and warm output.
- Measure import/model-load/generation time and practical peak RSS/approximate MPS allocation.
- Compare the official CPU/eager/float32 baseline and an independent MPS/eager/float32 run.
- Preserve failed runs and mark any optional MPS-to-CPU fallback explicitly; no automatic
  device/backend/voice replacement or swallowed errors.
- Determine whether the measured local path is usable for the MVP, document tradeoffs, and
  keep application contracts independent of vendor types.
- Confine created runtime/cache/model/audio/log/temp files to the explicitly authorized
  workspace, refuse symlink escapes, and never overwrite or delete prior results.

## Architecture constraints

- This is a runtime spike, not a production TTS service, UI, persistence format, or package.
- Do not install model dependencies or download weights in ordinary CI.
- Do not introduce MLX/another backend or select production packaging without a human
  decision and applicable ADR.
- Use only synthetic text; no cloning or user media/credentials.

## Acceptance criteria

- [x] The install/run note has been reproduced on the actual target Mac.
- [x] A short sentence is generated successfully.
- [x] Aiden/default-voice behavior is confirmed or the mismatch is documented.
- [x] Actual performance and human listening evidence judge the path usable/not usable.
- [x] The selected local backend and its tradeoffs are documented after the decision gate.
- [x] Packaging implications are recorded.

## Out of scope

- Full TTS UI, voice cloning, video generation, production packaging, and scheduling/MCP.
- Selecting a replacement runtime based solely on documentation or mocked tests.

## Validation

- [x] Real ARM64 Mac prepare, CPU, and MPS (or explicit failure evidence) experiment.
- [x] Listen to the synthetic output and document completion/intelligibility/voice suitability.
- [x] Run deterministic helper/contract checks without model dependencies:
  `python -m unittest discover -s scripts/spikes -p 'test_*.py' -v`.
- [x] Run Python compilation, shell syntax, and Ruff checks for the spike files.
- [x] Run the existing full application check without TTS installation before final delivery.
- [x] Required review findings resolved and PR CI passed before squash integration.

## Human decisions required

- Resolved on 2026-10-03: the owner confirmed CPU audio complete/clear and Aiden suitable,
  then selected the official CPU/0.6B path to continue speech/video integration.
- Decide on a replacement backend only if later evidence makes the accepted path unsuitable.
- Exact end-user launcher/packaging remains deferred; this spike records implications.

## Standards affected

None. Existing security, testing, architecture, and task-state rules apply.

## Implementation notes

- Added an optional bash preparation/run entrypoint, path/cache guard, Python runner,
  pinned experimental dependency input, pure helper/port tests, and a development note.
- CPU/MPS runs use fresh result directories and frozen local offline checkpoints; provider
  output is converted to project-owned waveform/rate values in a tiny experimental port.
- Normal backend dependencies remain unchanged. The repository check and CI now run spike
  Ruff lint/format, shell syntax, and deterministic stdlib helper tests using the existing
  backend development environment; they do not install TTS dependencies or download models.
- Windows/local source checks are separate from required Mac integration evidence.
- Local checks passed: Ruff check/format, all three Python files compiled, and bash syntax.
  Eleven deterministic tests ran: ten passed; symlink creation was unavailable for the Windows
  account, so the one actual symlink test must be rerun on Mac. Both real prepare entrypoints
  refused Windows with exit code 2 before any runtime installation.
- Target Mac preflight exposed two corrected issues: directory identity now uses `samefile`
  for case-insensitive volumes, and venv interpreter symlinks are validated without replacing
  their invocation path with the managed base interpreter.
- Actual Mac validation: isolated prepare succeeded; CPU and MPS each produced two synthetic
  WAVs and safe timing/memory records. Eleven pure tests passed on Mac without skips.
- CPU first/warm generation 10.37/9.28 s, 4.08 s mono/24 kHz WAV, peak RSS 3.85 GiB.
  Owner listened and accepted this audio. MPS float32/eager was slower (19.20/41.92 s) with
  output duration variability (4.24/10.80 s), so its audio is not the selected default.
- Read-only resource discovery identified existing 1.7B CustomVoice cache and FFmpeg 9.0.2.
  Old Python 3.14 and mismatched Conda environments are reference material, not a reused runtime.
- Full safe hardware/version/performance and packaging implications are in the linked note;
  raw model/audio/runtime logs remain ignored, and private machine identifiers are omitted.
- Full application check passed on Windows: 95 backend tests, 91 frontend tests, typecheck,
  production build, Ruff and shell syntax. Eleven helper tests ran (one Windows symlink
  permission skip); all eleven previously passed on the target Mac. PR #6 CI run
  37147207810 passed all three jobs. Final review covered 11/11 files with no
  Blocker/Required findings. The final task-state-only revision is checked again before merge.
