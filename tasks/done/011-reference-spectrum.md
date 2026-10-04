# 011 — Match the reference video's frequency bars

## Goal

Export the reference video's black rounded frequency bars instead of the blue line waveform.

## Context

Owner authorized the proposal on 2026-10-04. The reference is the final no-box restaurant
practice video in chat `01a10486-7a8c-7471-8d5c-1cc89e1c9ca9`. Its local rendering script
establishes the algorithm and geometry; user media remains outside Git.

## Requirements

- 36 black rounded bars, width 16 px, pitch 29 px, radius 7 px, maximum height 145 px.
- Transparent 1260 × 180 layer at (0, 850); local centerline y=90 and first bar x=118.
- 30 fps, 24 kHz mono PCM input, 800-sample Hann windows, 2048-point FFT, 36 logarithmic
  bands from 80 to 8000 Hz; band response and RMS envelope match the reference.
- Hide bars at RMS <= 0.001, including all five-second shadowing pauses.
- Remove the waveform backplate. Use a light-blue default background and dark default text
  for black-bar visibility. Preserve uploaded-image layout and document its contrast limit.
- Stream bounded PNG batches directly into the existing FFmpeg page process. No new runtime
  dependency, intermediate frame files, API/persistence changes or additional heavy jobs.
- Preserve process cleanup, frozen inputs, immutable exports, timeout and storage limits.

## Acceptance criteria

- [x] Spectrum response and silence/PNG rendering have focused deterministic coverage.
- [x] FFmpeg consumes the finite stream with correct image input indices and transparent overlay.
- [x] Actual reference audio exports at 1920 × 1080 / 30 fps / H.264-AAC; full decode passes.
- [x] Sampled speech frames show black rounded bars and pause frames contain no bars.
- [x] Existing checks pass; backend-critical review findings are resolved.
- [x] Documentation and task evidence are synchronized; generated media stays ignored.

## Out of scope

Subtitle redesign, REPEAT cue, template chooser, color/style controls, persistence and TTS changes.

## Validation

`bash scripts/check.sh`; actual FFmpeg export using cached reference Qwen WAVs, metadata and
full decode, speech/pause frames and audio measurements. No new model run is required.

## Human decisions required

None within the approved proposal. The implementation introduces no dependency.

## Implementation notes

Frontend and focused unit tests belong to GPT-6 Luna/max. Independent review uses the same
model and covers backend production/critical code only, excluding frontend and test files.

- Added a standard-library FFT/PNG analyzer and finite eight-frame async batches directly
  into the existing page process. No additional media files or runtime dependencies.
- Actual encoding uncovered an existing FFmpeg 8/9 concat clock incompatibility: 550
  frames were compressed to 0.568 s. Explicit `-r 30` alongside copy/setts restores the
  grid; strict final duration/frame-rate validation is retained.
- Independent GPT-6 Luna/max review found one Required raster bound issue. Pixel-center,
  half-open bounds now give exactly 16 px width and requested heights; re-review confirmed
  no remaining Blocker/Required findings in the selected critical backend scope.
- Final `bash scripts/check.sh` passed on this Mac: Ruff lint/format; 196 backend tests
  passed, one Windows-only check skipped, one existing Starlette/httpx warning; 11 spike
  checks; 167 existing frontend tests; TypeScript and production build. The selected
  subprocess/adapter/spectrum/API tests cover the new path; no frontend tests were added.
- Real cached reference Qwen WAVs (two sentences) produced 18.3335 s, 550 frames, 30 fps,
  1920 × 1080 H.264/AAC, 438,832 bytes in 8.64 s. Full decode passed. 49 sampled speech
  windows matched the reference NumPy algorithm's integer heights exactly. Final sampled
  speech contained 32,142 black pixels in the bar region; sampled pause contained zero.
  Decoded pause interior had zero PCM peak. No new TTS model run was started.
- Additional real exports with uploaded background + illustration and illustration-only
  each passed final metadata validation and complete decode (9.866667 s). Generated
  inputs/exports/evidence remain ignored under `artifacts/spectrum-validation/`.
- Black bars can be difficult to see on dark uploaded backgrounds. Contrast guidance is
  present in the UI/docs; configurable colors and full reference subtitle layout are deferred.
- Delivery remains in review pending PR/CI and squash integration. No browser-driven
  end-to-end TTS run was performed; genuine adapter/media validation reused accepted audio.
- Owner explicitly authorized pushing the verified branch and creating a PR in
  `Jayden-X/shadowing-video-studio` on 2026-10-04. Task remains in review until integration.

## Integration

PR #13 passed backend, frontend and repository-hygiene CI and was squash-merged into
main as `055b0810fd150290d5796dc204288822a870e1b4`. The later optional-illustration
layout correction is tracked separately in Task 012.
