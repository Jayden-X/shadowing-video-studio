# 010 — Select supported local TTS voices in the UI

## Priority and status

- Priority: **P2**.
- Status: **done** — owner listening/browser acceptance passed on 2026-10-04.

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
- The selector applies to the whole document, as confirmed by the owner on 2026-10-04.
  Per-sentence overrides are out of scope. Every sentence binding includes its effective
  voice. Selection alone invokes no model inference.
- Keep cache semantics compatible with P3 Task 008; a restored audio association must match
  the selected voice and current effective configuration.

## Architecture constraints

Keep voice identities/settings project-owned, with Qwen capability/generation details behind
SpeechProvider. Maintain the accepted local CPU model path, one heavy job, frozen bindings,
safe errors and existing file preservation. Do not change optional worker/process boundaries.

## Acceptance criteria

- [x] The UI shows supported voices and the current selection; Aiden is initially selected
  when the configured model supports it.
- [x] Selecting a supported non-default voice and explicitly generating produces matching
  audio and records the selected voice in job/asset bindings.
- [x] Unsupported or stale voice selections are rejected with actionable errors and no fallback.
- [x] Voice changes cannot affect an in-flight job or silently reuse incompatible old audio.
- [x] Earlier WAVs are preserved and video export accepts only exact current voice/text/config
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

Document-level scope confirmed. No architecture/process/persistence boundary changes.
The owner initially deferred target-Mac checks, then authorized restored SSH access during
this batch. Alternative-voice generation and owner listening/browser acceptance are passed.

## Standards affected

Existing architecture, security, focused-testing and agent model-selection standards apply.

## Implementation notes

Implementation is on `feature/010-tts-voice-selection`. Task009 owner acceptance was
confirmed during development; PR #10 squash merged as `8e14494`, and its main CI passed
(run `37159753241`). Task010 is delivered separately against that main baseline.

Contract: `GET /api/speech/capabilities` returns provider-neutral voices with IDs, labels
and effective configuration fingerprints. Names come from the configured frozen model's
`talker_config.spk_id`, the source used by Qwen's `get_supported_speakers`, without loading
weights. The worker independently validates the selected voice against the loaded model.
Speech requests, job/row results and video requests bind the chosen voice and fingerprint;
old clients omit the fields and retain the existing Aiden default.

Focused deterministic tests prove non-default voice routing and frozen result bindings,
same-voice reuse, old-file preservation, unsupported/stale rejection, exact video matching
and worker-level unsupported-speaker rejection before synthesis. Real-Mac integration
also generated Ryan audio; the owner accepted the clear/complete sample and browser workflow.

Local checks: backend 187 passed, three Windows symlink-permission skips; Ruff lint/format
passed across backend and spikes. Spike helpers: 10 passed, one Windows symlink skip;
shell syntax passed. Frontend full default-pool check passed: 167 tests, typecheck/build.
Local async/process checks required execution outside the Windows sandbox because its
loopback socketpair/temp process bootstrap failed before test code could execute.

GPT-6 Luna/max implemented frontend and focused tests and reviewed all nine selected
backend production files using OCR deterministic preview/rules. No Blocker/Required
remained. Frontend and test source were excluded from review under the owner's MVP policy.

## Target-Mac acceptance

- [x] After SSH access returns, deploy the built frontend/backend together within the
  approved `/Users/QinWei/Documents/shadowing-video-studio` directory (cache allowed).
- [x] Verify the actual frozen model/runtime's voice list, Aiden default and explicit
  document-wide alternative selection without inference on selection.
- [x] Generate short sentences with a supported alternative voice and record bindings.
- [x] Owner listens and confirms complete, clear audio and the selected voice.
- [x] Verify changed voice blocks old audio preview/export, preserves its WAV, and
  explicit generation/return to an earlier voice reuses only matching valid audio.
- [x] Generate and API-preview/download a video with alternative-voice audio and existing
  background/illustration selections; verify complete decode and five-second pauses.
- [x] Owner accepts the browser voice selection/preview/export workflow.

### Real-Mac evidence (2026-10-04)

- PR #11 code revision `08b25f4` passed CI run `37160054402` and was deployed to a fresh
  project-owned `tmp/first-video.igZFtODV/source-010-001` directory with the built frontend.
  Six known old jobs were checked terminal before stopping only the owned old 8877 process.
  Existing source trees and all user media were preserved; the original Mac checkout was
  left untouched. New service PID 57202, loopback port 8877, existing validated environments.
- Actual metadata reports Aiden, Dylan, Eric, Ono_Anna, Ryan, Serena, Sohee, Uncle_Fu and
  Vivian. Aiden remains default. Capabilities and rejected unsupported/stale requests did
  not start the model worker. No inference occurs on selection/capability lookup.
- Real Aiden job `ba1bda53479045f79647d9e9c274d266` and Ryan job
  `51313d7fca144505a2d1c2326a5a6d0d` completed. Ryan's two WAVs are 3.68 and 2.8 seconds;
  rows bind Ryan and its exact effective configuration fingerprint. Same-voice generation
  requests reuse exact asset IDs; returning to Aiden reused its ID and unchanged WAV bytes.
- Wrong-voice and stale-fingerprint video requests returned 409 before rendering. The
  accepted Ryan export `98733e4843c34633ac52c2246c29b927` reused existing library images
  and produced 16.5 seconds, 495 frames, 1,121,754 bytes, 1080p30 H264/AAC. Range preview,
  attachment download, exact frame count and complete decode passed. Interior PCM peaks
  of both five-second practice pauses were zero.
- Evidence and synthetic audio/video stay ignored under the approved Mac project's
  `tmp/first-video.igZFtODV/evidence-010-001/`. Local copied Ryan/Aiden samples are ignored
  under `tmp/task010-evidence-001/`. The owner confirmed Ryan listening and browser
  voice selection/preview/export acceptance on 2026-10-04.
- The initial smoke script's case-sensitive dictionary lookup for a response header failed
  after successful rendering. A read-only continuation checked the existing jobs/output
  using the case-insensitive header interface; no production fix or re-generation was needed.
