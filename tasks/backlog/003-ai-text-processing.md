# 003 — AI-assisted text processing

## Goal

Generate a reviewable sentence list using a selectable AI provider.

## Requirements

- Provider abstraction.
- Initial provider targets: DeepSeek and Codex.
- Preserve source text.
- Convert provider output into the canonical sentence model.
- Allow full manual correction before media generation.
- Provider failure must be recoverable.

## Acceptance criteria

- User can select AI-assisted mode.
- User can select an available provider.
- DeepSeek/Codex details do not leak into application-domain sentence handling.
- Provider outputs are validated before acceptance.
- Manual editing remains available after AI processing.

## Out of scope

- Automatic TTS generation without confirmation.
- Batch processing.

## Validation

- Contract/unit tests using fixtures/mocks.
- Failure-path tests.
