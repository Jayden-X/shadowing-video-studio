# 002 — Manual sentence editor

## Goal

Allow the user to prepare and edit the canonical sentence list manually.

## Requirements

- Paste source dialogue.
- Create editable sentence items.
- Edit.
- Add.
- Delete.
- Split.
- Merge.
- Reorder.

## Acceptance criteria

- Operations preserve a deterministic ordered sentence list.
- Original source text is not silently lost when processing starts.
- Result can feed later TTS generation.

## Out of scope

- AI provider calls.
- TTS.
- Video rendering.

## Validation

- Unit tests for sentence operations.
- UI tests for critical editing actions once UI stack exists.
