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

- [x] User can paste dialogue and create an ordered sentence list.
- [x] User can edit, add, delete, split, merge, and reorder sentences.
- [x] Original source text remains available and is not silently overwritten.
- [x] Sentence operations produce deterministic results.
- [x] Domain sentence operations have unit tests.
- [x] Critical UI editing behavior has tests appropriate to the current frontend stack.
- [x] Backend/frontend checks pass.
- [x] No AI/TTS/video dependency is required to use the editor.

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

- Added React-independent `SentenceDocument` / `SentenceItem` models and immutable domain operations. Editing/reordering retain IDs, split retains the left ID, merge retains the preceding ID, and deleted IDs are not reused within a document.
- Added a responsive source/editor UI with accessible controls, cursor-based split feedback, list-boundary buttons, and explicit confirmation before preparing a replacement list. The source draft and prepared source snapshot are independent from edits.
- Manual editing remains available when the local service is offline. No AI/TTS/video integration is required.
- Added UI test dependencies only, a frontend lockfile, and `npm ci` in CI. Setup documentation uses the same locked install path.
- Validation on 2026-10-03: `bash scripts/check.sh` passed (Ruff lint/format, 1 backend test, 28 frontend tests including 16 domain + 10 UI + 2 API tests, TypeScript check, and Vite production build).
- Browser smoke at `http://127.0.0.1:5173` passed paste/prepare, edit, add, split at cursor, merge, reorder, delete, original snapshot preservation, and cancel/confirm replacement while the backend was offline.
- Independent OCR delegation review completed with no Blocker/Required findings; all 7 previewed implementation files were reviewed, with tests/docs/dependency metadata also examined. No external review endpoint was used.
- Limitations: work is held in the current browser session and refresh/closing the page clears it. Local splitting uses punctuation/newlines and may require correction for abbreviations or decimals. No persistence format is selected.
- Final delivery remains gated by PR CI and squash integration.
