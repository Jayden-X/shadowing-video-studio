# Product Roadmap

## Phase 0 — Bootstrap

- Repository and AI-development workflow.
- Confirm application stack.
- Confirm local project persistence approach.
- Establish runnable shell and CI.

## Phase 1 — Text workflow

- Paste dialogue.
- Manual sentence editing.
- AI-assisted segmentation/preparation.
- DeepSeek adapter.
- Codex adapter.
- Human confirmation before generation.

## Phase 2 — Speech workflow

- Qwen3-TTS integration.
- Aiden default voice.
- Sentence preview.
- Sentence regeneration.
- Cache/reuse successful sentence audio.

## Phase 3 — Video workflow

- Fixed 1080p template.
- Left text/right visual layout.
- Dynamic waveform.
- 5-second default pause.
- MP4 rendering/export.

## Phase 4 — Reliability / UX

- Progress reporting.
- Cancellation behavior.
- Failure recovery.
- Project/history persistence, including restart audio/media restoration (Task008).
- Versioned outputs.

## Prioritized follow-up work after first-video acceptance

Priority labels below are independent of phase numbers. Implementation is deferred until
the corresponding task is ready and any required design decisions are confirmed.

| Priority | Follow-up | Task |
| --- | --- | --- |
| P2 | UI upload, local folder library and selection of video backgrounds / sentence illustrations | [009](../../tasks/done/009-local-visual-library.md) |
| P2 | UI list and selection of voices supported by the local TTS runtime | [010](../../tasks/done/010-tts-voice-selection.md) |
| P3 | Local project/history save and recovery, including audio reuse and previous outputs after restart (accepted) | [008](../../tasks/done/008-project-history-persistence.md) |
| P3 | Three project deletion modes, retained resources and independent unused-image library cleanup | [014](../../tasks/done/014-project-resource-cleanup.md) |

AI illustration generation is a future producer seam within Task 009's design; it is not
included in that task's initial implementation. Product behavior is defined in
[prioritized requirements](../requirements/product-requirements.md#prioritized-follow-up-requirements).

## Longer-term scope

- Batch jobs.
- Multi-user/accounts.
- Cloud execution.
- General drag-and-drop editor.
- Broad template marketplace.
