# 007 — Render and export the first shadowing video

## Goal

Produce a real playable MP4 on the target Mac from the reviewed sentences and accepted
local speech assets, using the product's fixed shadowing template.

## Context

Tasks 002/003 prepare reviewed canonical sentences. Task 004 verified CPU/0.6B/Aiden on
the target Mac; Task 006 supplies generated speech and immutable application asset IDs.
The owner authorized continuing through the first video. Follow product requirements,
ADR 0001/0002, and repository standards; no new product or packaging decision is needed.

## Requirements

- An explicit user action freezes current ordered sentence IDs/text and corresponding
  ready audio asset IDs. Validate their exact correspondence before rendering.
- Place FFmpeg behind a project-owned VideoRenderer contract; argv invocation without a
  shell, bounded process lifetime and safe errors. Share the speech heavy-job gate.
- Use a fixed 16:9, 1920x1080 template: one sentence per page, large readable English text
  on the left, a reserved visual area on the right, dynamic audio waveform at the bottom,
  and a five-second silent shadowing pause after each sentence including the final one.
- Fit/wrap text without truncation. Reject text that cannot fit with an actionable request
  to split it. Treat quotes, Unicode and file-path characters as data.
- Produce H.264/AAC MP4 with consistent frame rate and playable duration/audio streams.
- Report progress and failures without discarding accepted speech or editor contents.
- Preserve previous exports, generate unique immutable output IDs, and serve/download by
  opaque IDs; never accept arbitrary client filesystem output/input paths.
- Confine all generated/temp/cache writes to the approved configured workspace. Preserve
  failed-job evidence; do not overwrite or delete pre-existing media.
- Serve a built frontend through the existing local FastAPI application for the Mac run;
  retain development Vite behavior. Do not select a double-click packaging framework.
- Run the actual full pipeline on the target Mac with at least two synthetic English
  sentences. Verify metadata, decode, visible text/waveform and silent pause boundaries.

## Acceptance criteria

- [x] Ready current speech can trigger exactly one video render with observable progress.
- [x] Missing/stale/mismatched audio is rejected before invoking FFmpeg.
- [x] The generated MP4 has 1920x1080 H.264 video, AAC audio, and expected page/pause duration.
- [x] A user can preview/download it; a subsequent export retains the prior output.
- [x] Renderer failure preserves successful speech and allows an explicit retry.
- [x] Application API/UI and filesystem/process/template cases have deterministic tests.
- [x] Actual target Mac produces the first video through the application workflow; evidence
  clearly separates genuine generation from fixture-based UI checks.

## Out of scope

User media upload, voice cloning, drag-and-drop editing, persistent project/history format,
double-click packaging, MPS/SDPA optimization, scheduling/MCP runtime or multiple videos.

## Validation

Run `bash scripts/check.sh`, renderer/timeline/command/asset/API/UI checks, local browser
smoke, and actual Mac Qwen-to-FFmpeg integration. Use ffprobe, decode verification, sampled
frames and pause audio measurements. Resolve review findings and pass PR CI before squash.

## Human decisions required

None within this approved scope. Mac writes remain under
`/Users/QinWei/Documents/shadowing-video-studio` or `~/.cache`; read-only discovery is allowed.
Any additional write location or product/packaging/persistence expansion requires approval.

## Standards affected

None initially.

## Implementation notes

Run metadata is volatile; generated assets/exports remain immutable and outside Git.

- The renderer and video API are implemented; ordinary checks use fake processes and tiny
  synthetic WAVs. Genuine target Mac encoding evidence is recorded below.
- Existing tests are retained. New API/UI/static-serving checks cover a small set of key
  scenarios in accordance with the owner's focused MVP testing policy.
- Frontend implementation and independent review are assigned to GPT-6 Luna/max as selected
  by the owner. The local service serves a trusted frontend build without selecting a new
  desktop framework or persistent project format.
- Initial full checks passed: 170 backend tests, two Windows symlink permission skips,
  154 frontend tests, typecheck/build, Ruff and the existing spike helpers. PR #8 CI run
  37150221128 passed. The owner's browser acceptance is in progress.
- The owner's eight-sentence export failed before its first page. Read-only investigation
  confirmed that the configured Mac FFmpeg lacks `drawtext`; speech and failed-job inputs
  remain intact. A compatible build and capability preflight are required before retry.
- Backend review identified output budgets being enforced only after encoding. The corrective
  revision checks budgets before copying/encoding and applies `-fs` to every output, with a
  4 MiB packet/footer margin and rejection of truncated/oversized outputs. This is a preventive
  application limit, not an operating-system quota. GPT-6 Luna/max found no remaining
  Blocker/Required in the backend budget, capability and optional shaping deltas.
- The corrective full check passed: 172 backend tests (two Windows skips), 154 frontend
  tests, typecheck/build, Ruff and existing spike helpers. Capability readiness rejects
  missing template filters/encoders/muxers before creating a job and caches successful
  checks by executable fingerprint. Corrective CI and updated application/browser retry
  remain pending.
- Read-only reuse of an existing static arm64 FFmpeg 7.1 resolved the missing `drawtext`;
  no global tools were installed/modified. This build lacks the optional FriBidi
  `text_shaping` option, so only that unsupported setting is omitted after capability checks.
- Genuine rendering from two earlier real Qwen API WAVs completed in 2.59 s: 16.9 s,
  1,081,246 bytes, H.264/AAC, 1920x1080, 30 fps and 507 frames. Full decode passed; measured
  post-speech windows had zero PCM RMS/peak, and sampled speech/pause/second-page frames
  verified text, the reserved right area, dynamic waveform and waveform clearing. This
  uses genuine cached speech, not fixture audio or a new model run.
- The owner then retried the complete browser workflow with eight fresh real Qwen sentences.
  The application completed all eight pages: 61.1 s, 3,079,826 bytes, 1920x1080, 30 fps,
  H.264/AAC and 1,833 video frames. Range preview returned 206 and the download endpoint
  returned an attachment. The owner confirmed preview, sound, five-second pauses and MP4
  download all passed. A subsequent API export reused the speech, received a new asset ID,
  and left the prior MP4 byte-identical (SHA-256 checked). No extra model run was started.
- Final backend lint/format and existing tests passed after the optional-option correction:
  172 passed, two Windows symlink permission skips, one existing Starlette/httpx warning.
  Earlier complete frontend/type/build/spike checks remain applicable because those files
  were unchanged. The final documentation/task-state revision must pass CI before squash.
- The service stays on Mac loopback port 8877. Existing WAVs, exports, source backup and
  failed-job evidence remain inside the authorized project directory and outside Git.
