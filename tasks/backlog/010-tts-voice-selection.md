# 010 — Select supported local TTS voices in the UI

## Priority and status

- Priority: **P2**.
- Status: **backlog** — requirements recorded; selector/settings contract awaits design.

## Goal

Let the user list and select supported voices, such as Aiden, before explicitly generating
sentence speech with the configured local TTS model.

## Context

The owner clarified that the P2 audio selector means TTS voice selection. Task 006 currently
uses English/Aiden with the accepted CPU/0.6B path. See the prioritized follow-ups in product
requirements and the existing SpeechProvider/runtime boundary.

## Requirements

- List only voices supported by the configured model/runtime, exposed through provider-neutral
  backend capability data. Aiden remains the current default when supported.
- Provide a clear selected voice, optional readable descriptions, and an unavailable reason
  if the configured model cannot offer selectable voices. Do not invent/hard-code unverified
  speaker names in the frontend or silently substitute a different voice/model.
- Select voice before an explicit generation action. Freeze it with sentence text, language,
  model revision and effective settings for a job; changes cannot alter work already running.
- Include the selected voice in generation/result bindings and the audio cache fingerprint.
  Display existing audio as ineligible for a different selected voice, preserve its WAV, and
  require explicit generation before preview/export uses matching newly selected audio.
- Record whether the selector applies to the whole document or permits per-sentence
  overrides before the task becomes ready. Every sentence binding must include its effective
  voice. Selection alone invokes no model inference.
- Keep cache semantics compatible with P3 Task 008; a restored audio association must match
  the selected voice and current effective configuration.

## Architecture constraints

Keep voice identities/settings project-owned, with Qwen capability/generation details behind
SpeechProvider. Maintain the accepted local CPU model path, one heavy job, frozen bindings,
safe errors and existing file preservation. Do not change optional worker/process boundaries.

## Acceptance criteria

- [ ] The UI shows supported voices and the current selection; Aiden is initially selected
  when the configured model supports it.
- [ ] Selecting a supported non-default voice and explicitly generating produces matching
  audio and records the selected voice in job/asset bindings.
- [ ] Unsupported or stale voice selections are rejected with actionable errors and no fallback.
- [ ] Voice changes cannot affect an in-flight job or silently reuse incompatible old audio.
- [ ] Earlier WAVs are preserved and video export accepts only exact current voice/text/config
  bindings; returning to a previously selected voice may reuse still-valid matching audio.

## Out of scope

Voice cloning, custom voice training, BGM/music mixing, uploaded replacement audio, AI-generated
illustrations, new TTS engines or MPS tuning.

## Validation

At implementation time, retain existing tests and cover supported/unavailable capability,
frozen voice/binding changes and safe reuse at key workflow boundaries. Validate one supported
alternative voice on the actual Mac and have the owner listen. Avoid minor UI/style assertions.
Frontend implementation and critical backend code review use GPT-6 Luna with max reasoning.

## Human decisions required

Confirm the selection scope (document-level default and any per-sentence overrides) before
marking this task ready. Discover the supported voice list from the installed runtime and
record the provider-neutral settings/capability contract; approve an
ADR if implementation changes an architecture or persistence boundary.

## Standards affected

Existing architecture, security, focused-testing and agent model-selection standards apply.

## Implementation notes

Requirements only; current production speech remains English/Aiden. No voice selector,
provider capability endpoint or new inference behavior is delivered by this document.
