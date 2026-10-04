# 012 — Omit unused illustration layers

## Goal

Pages without an illustration show the background without the reserved blue canvas or gray dim layer.

## Context

Owner requested this correction after Task 011 / PR #13. PR #13 is merged; this fix uses
its own branch/PR. Product requirements, ADR 0003 and the visual runtime/library docs
now record this explicit layout decision.

## Requirements

- Determine illustration presence per frozen sentence, throughout speech and the pause.
- Without an illustration, draw no right-side panel and do not dim the background.
- Retain the panel and existing dim behavior on illustrated pages.
- Use dark text on undimmed pages; preserve white text on dimmed uploaded backgrounds.
- Keep image input indices, finite frame counts, five-second pauses and media safeguards.

## Acceptance criteria

- [x] All four background/illustration combinations have focused regression coverage.
- [x] Unillustrated speech/pause frames display the background without placeholder or dimming.
- [x] Illustrated pages retain their existing panel/dimming behavior.
- [x] Actual exports pass metadata validation and complete decoding.
- [x] Relevant checks and backend-critical review pass; documentation is synchronized.

## Out of scope

Automatic contrast selection, subtitle redesign, template/style controls, TTS and persistence.

## Validation

Full `bash scripts/check.sh` using installed dependencies (`uv run --no-sync`): Ruff,
200 backend tests passed, one Windows-only skip, 11 spike checks, 167 frontend tests,
TypeScript and production build. Lockless dependency discovery initially hit the sandbox's
network restriction; no new dependency was needed.

Actual cached Qwen audio produced a mixed illustrated/unillustrated 18.3335 s MP4 and a
no-image default 9.866667 s MP4. Both passed final metadata validation and full decode.
Unillustrated right-region mean RGB error against the scaled source was <2 during speech
and pause. Default right RGB was (156,214,245), with no placeholder. Illustrated dimming
remained (sample mean 77.78 versus 198.86 on the undimmed page). Evidence/exports remain
ignored under `artifacts/spectrum-validation/no-illustration-*`.

## Human decisions required

None. The owner authorized the layout correction and delivery to this repository.

## Implementation notes

Only the page filter composition changes: background dimming and the right-side panel
are conditional on that sentence's illustration. No new API, dependency or process.
GPT-6 Luna/max handled focused unit tests. Independent backend production review found
no Blocker/Required findings; frontend and test code were excluded as requested.
PR/CI and squash integration remain pending; dark images may reduce text/bar contrast.
