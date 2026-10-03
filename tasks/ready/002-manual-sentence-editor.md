# 002 — Manual sentence editor

## Goal

Allow the user to paste source dialogue and prepare the canonical ordered sentence list manually.

## Context

This is the first real product workflow after the application shell. The canonical sentence model created here will later be reused by AI-assisted text processing, TTS generation, regeneration, and video rendering.

Read:
- `docs/requirements/product-requirements.md`
- `docs/architecture/overview.md`
- ADR 0001

## Requirements

- Paste source dialogue.
- Convert source text into an initial editable sentence list using deterministic local rules only.
- Preserve the original pasted source text separately.
- Edit sentence text.
- Add a sentence.
- Delete a sentence.
- Split a sentence.
- Merge adjacent sentences.
- Reorder sentences.
- Keep sentence identity stable enough for later per-sentence audio/result state.

## Architecture constraints

- Define a canonical sentence/domain model independent of React component state.
- Manual editing must not depend on DeepSeek, Codex, Qwen3-TTS, or FFmpeg.
- UI operations should call deterministic domain/application functions that can be unit tested.
- Do not choose the long-term persistence technology in this task unless required for basic browser refresh behavior.

## Acceptance criteria

- [ ] User can paste dialogue and create an ordered sentence list.
- [ ] User can edit, add, delete, split, merge, and reorder sentences.
- [ ] Original source text remains available and is not silently overwritten.
- [ ] Sentence operations produce deterministic results.
- [ ] Domain sentence operations have unit tests.
- [ ] Critical UI editing behavior has tests appropriate to the current frontend stack.
- [ ] Backend/frontend checks pass.
- [ ] No AI/TTS/video dependency is required to use the editor.

## Out of scope

- DeepSeek/Codex calls.
- TTS generation.
- Audio playback.
- Video rendering.
- Batch processing.
- Final project/history persistence design.

## Validation

- Python tests if backend/domain logic is introduced there.
- Vitest tests for frontend/domain helpers.
- Manual smoke test of all six editing operations.
- `bash scripts/check.sh`.

## Human decisions required

None unless implementation reveals a product ambiguity that changes the user-visible editing behavior.

## Implementation notes

Fill in during implementation.
