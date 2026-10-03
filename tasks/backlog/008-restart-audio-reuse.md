# 008 — Reuse valid sentence audio after restart

## Priority and status

- Priority: **P3** — later optimization, after the accepted first-video workflow.
- Status: **backlog** — requirements recorded; storage/cache design is not selected.

## Goal

Avoid repeating TTS generation after browser/service restart when frontend associations
and the corresponding trusted local audio files still exist and remain valid.

## Context

Tasks 006/007 preserve WAV files but use volatile lookup metadata, so old service asset IDs
cannot currently be reused after restart. The owner explicitly assigned this improvement P3
and requested frontend-cached association keys for best-effort subsequent reuse.
See the prioritized follow-ups in `docs/requirements/product-requirements.md`, the speech
runtime and architecture persistence boundary. P2 voice selection in Task 010 must be
represented in any future cache key.

## Requirements

- Store a versioned, stable association in frontend cache that can be restored for the same
  local work. Include stable sentence/project identity, exact canonical text or its validated
  digest, and a provider-neutral reference to the effective TTS configuration.
- The effective configuration includes voice, language, model identity/revision and generation
  settings; relevant runtime/normalization changes must not accidentally match old audio.
- Keep small trusted backend asset/binding metadata separate from large local WAV files.
  A restored key is a lookup hint; frontend values or an old transient opaque ID never grant
  arbitrary filesystem access or establish a trustworthy text/config/audio binding.
- On restore, resolve only application-owned resources, validate the stored association,
  real file boundary/ownership, digest and WAV format, and then return an eligible current
  service asset/reference. Reuse performs no TTS inference when those checks succeed.
- Show which audio was restored and why an association cannot be reused. Missing frontend
  cache, backend metadata, files, changed text/configuration, or corruption must leave the
  original source/editor data intact and allow explicit regeneration.
- Retain earlier WAV files when restoring, regenerating, or rejecting an association; no
  automatic pruning or overwrite is authorized. No full dialogue or secrets in trace logs.
- Restoring cache must not start generation or export automatically.

## Architecture constraints

Frontend cache is optional convenience data, while backend validation remains authoritative.
UI calls application APIs and never sends an arbitrary local input/output path. Keep the
SpeechProvider/asset boundary and one-heavy-job rule. Do not couple canonical sentence objects
to a storage library or add account/cloud synchronization.

## Acceptance criteria

- [ ] Restart browser/service with association metadata and files intact; unchanged current
  sentences/configuration restore eligible audio without a model call.
- [ ] Exact voice/text/configuration changes prevent stale reuse while preserving prior WAVs.
- [ ] Missing or corrupt cache/metadata/audio results in a clear fallback and explicit
  regeneration, preserving editor data and unrelated assets.
- [ ] Forged keys/paths cannot serve unrelated files or bypass binding/hash/format checks.
- [ ] Successfully restored audio is usable by preview and video export through normal APIs.
- [ ] Cache clearing/file removal is reported as a best-effort limitation.

## Out of scope

General project/history editing, media deletion/pruning, cross-device/cloud synchronization,
batch/scheduler/MCP runtime, or changing the selected TTS backend/model.

## Validation

At implementation time, retain existing tests and cover only the critical valid-restore,
stale/missing/corrupt binding, file-boundary and preview/export paths. Verify a real Mac restart
using previously generated audio; distinguish cache reuse from new generation. Follow the
owner's focused MVP testing policy and applicable CI gates.

## Human decisions required

Before implementation, select and document frontend cache and backend association/index
formats, schema versioning, and how the same document/sentence identity is restored. An ADR
is required for durable storage selection. Do not assume a specific browser cache API or DB.

## Standards affected

Existing architecture, security, focused-testing and delivery standards apply.

## Implementation notes

Requirements only. No persistent format, restore API, cache implementation or runtime change
has been delivered by recording this task. This optimization is not a first-video blocker.
