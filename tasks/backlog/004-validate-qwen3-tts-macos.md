# 004 — Validate Qwen3-TTS on the target Mac

## Goal

De-risk the local TTS runtime before finalizing end-user packaging.

## Context

The product requires local Qwen3-TTS and currently defaults to the Aiden voice. The official Qwen3-TTS package is Python-based, but Apple Silicon acceleration/backend behavior must be verified on the actual target Mac before the project commits to a packaging strategy.

## Requirements

- Record target Mac hardware and macOS version for the test without committing private machine identifiers.
- Verify an install path in an isolated environment.
- Generate a short synthetic sentence with the intended model/voice.
- Measure approximate startup/model-load time, generation time, and peak memory at a practical level.
- Determine whether the usable path is official PyTorch/MPS/CPU, an MLX-compatible implementation, or another supported local backend.
- Keep the application-facing SpeechProvider boundary independent of the chosen runtime backend.

## Acceptance criteria

- [ ] A reproducible install/run note exists.
- [ ] A short sentence is generated successfully.
- [ ] Aiden/default-voice behavior is confirmed or the mismatch is documented.
- [ ] Runtime performance is judged usable/not usable for the MVP.
- [ ] The selected local backend and its tradeoffs are documented.
- [ ] Packaging implications are recorded.

## Out of scope

- Building the full TTS UI.
- Voice cloning.
- Production packaging.

## Validation

Manual runtime spike on the target Mac plus a small adapter smoke test once the backend choice is made.
