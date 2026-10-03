# 009 — Upload and reuse local visual assets

Priority: P2  
Status: done — owner browser acceptance passed on 2026-10-04

## Goal

Let the user upload, browse, and reuse locally stored background images and sentence
illustrations, then use the selected immutable assets in a generated shadowing video.

## Context

Task 007 established the fixed 16:9 template, with sentence text on the left and a
reserved visual area on the right. This task adds user-managed images to that template.
The owner explicitly requested implementation after the first-video acceptance.
Storage, layout and sentence-association rules are recorded in
[ADR 0003](../../docs/architecture/decisions/0003-local-visual-library.md).

P2 TTS voice selection (for example, Aiden) is tracked separately in Task 010.
AI-produced illustrations are
a future design seam only; this task does not add an AI provider, model, API, or automatic
generation flow.

## Requirements

- Provide UI flows to upload a background image, browse/select a previously uploaded
  background, and upload/browse/select a right-side illustration for each sentence.
- Distinguish the video-level background selection from illustrations assigned to
  individual canonical sentence IDs. Sentence associations must use stable IDs, never
  sentence text or list positions.
- Import uploaded bytes into an application-owned local folder. The browser must not
  provide a filesystem path for the server to read. Assign every imported asset an
  independent, server-generated stable asset ID; filenames are display metadata only.
- Keep successfully registered image bytes immutable. Uploads and project assignment
  changes must not overwrite, mutate, or automatically delete existing assets. The MVP
  does not need an asset-delete operation.
- Persist the asset library and its references across service restarts so a user can
  browse and reuse prior uploads. Keep media separate from small library metadata where
  practical, using the version-1 metadata and local folder layout in ADR 0003.
- Validate uploaded content as an actual decodable image and enforce explicit byte-size
  and dimension/pixel limits before registering it. Reject invalid, corrupt, unsupported,
  or over-limit uploads with a safe actionable error and no partial library entry or
  changed current assignment. Accept static PNG/JPEG/WebP up to 10 MiB, 8192 pixels per
  dimension and 20 million pixels, verified by local decode within 20 seconds.
- A selected background applies at the video level. A selected illustration is bound to
  its sentence and displayed in the existing right-side visual area. When no asset is
  selected, retain the current template behavior.
- The initial layout uses a background that is static for
  the whole video, and a sentence's illustration remains on its page throughout that
  sentence's frozen audio and the existing five-second shadowing pause. Do not add UI for
  timed image changes, transitions, or a visual timeline in this task.
- Reordering and ordinary text edits preserve illustration associations. Split keeps the
  left sentence's image and leaves the new right sentence unassigned. Merge keeps the
  survivor's image and asks before removing a different image association. Deletion
  removes only the binding. Replacing the document clears sentence bindings and retains
  the background. Existing library files remain intact.
- On explicit video generation, freeze the background selection and every sentence-to-
  illustration association alongside the existing ordered sentence/audio snapshot.
  Resolve frozen assets by server-owned IDs, verify their immutable content (for example,
  using a content hash), and use the exact selected bytes for that render. Each page must
  still match its frozen sentence audio duration plus the existing pause. A missing or
  mismatched asset must be reported before invoking FFmpeg; recovery must allow explicit
  reselection or re-upload without losing sentence text or accepted speech.
- FFmpeg and other backend code must resolve assets through the application-owned asset
  boundary. Never accept arbitrary client input paths or expose server paths in API/UI
  errors.
- Preserve a path for a future illustration producer to register an image through the
  same asset-validation and registration boundary and receive a stable asset ID. Do not
  implement image generation or select a provider/model/API in this task.

## Architecture constraints

- Keep the product local-first and use the existing UI/API, application, filesystem, and
  `VideoRenderer` boundaries. Do not couple frontend code to local filesystem paths.
- Keep image bytes separate from library metadata where practical. Select the storage
  layout/index format through an ADR before implementation; do not make file layout part
  of the canonical sentence or asset domain model.
- Preserve immutable, server-owned asset identity and the existing frozen render-input
  boundary. Do not add a general video editor, generic plugin system, or new framework.

## Acceptance criteria

- [x] A user can upload a valid image, see its preview/name in the library, and select
      it as the video background or as a sentence illustration.
- [x] After a service restart, existing library items remain listed and can be selected
      again with unchanged asset identity and bytes.
- [x] Invalid, corrupt, unsupported, or oversized images produce a safe error, create no
      usable partial asset, and leave current sentence/audio/visual selections intact.
- [x] Uploading or assigning another image never overwrites an existing asset; existing
      assets are not automatically removed. No client-provided path is read by the server.
- [x] A missing stored file is surfaced as unavailable and prevents FFmpeg from starting;
      after explicit re-upload or reselection, rendering can proceed without rebuilding
      speech or losing edited sentences.
- [x] A render uses its frozen video background and sentence-ID illustration bindings;
      each illustration remains visible for its sentence's full speech and five-second
      pause, with page timing still matching the frozen audio and pause.
- [x] Reordering and ordinary text edits retain sentence illustration bindings. The
      split/merge/delete rules are explicit and covered by focused tests.
- [x] With no selected images, the existing fixed-template video workflow remains
      available and visually behaves as it does today.
- [x] Focused API/filesystem/UI tests cover upload, selection, restart/reuse, missing-file
      and upload errors, and no-overwrite behavior while retaining the existing tests.
- [x] The owner accepts the target-Mac browser upload/select/export workflow. Automated
      checks and genuine media evidence support the criteria above; they do not replace
      this requested browser acceptance.

## Out of scope

- AI illustration generation or any provider/model/API integration.
- Background music, user audio/WAV upload, voice cloning, or changing the existing TTS
  voice workflow.
- Timed illustration changes, transitions, drag-and-drop editing, or a general video
  timeline/editor.
- Cloud storage, accounts, multi-user access, batch videos, or a durable project/history
  system beyond the library metadata needed to preserve assets and selections.
- Automatic cleanup or deletion of user-uploaded image files.

## Validation

- Run `bash scripts/check.sh` and focused deterministic backend/API/filesystem and UI
  checks for the key upload/select/restart/missing/error/no-overwrite paths.
- Manually smoke-test background and per-sentence illustration upload, library reuse,
  sentence reorder/edit, export preview, and image continuity through speech and pause.
- Verify missing/corrupt asset rejection occurs before FFmpeg, that asset bytes survive a
  service restart, and that runtime/user media remains outside Git.
- Any actual-image/FFmpeg evidence must use small safe fixtures; do not download model
  weights or commit user-provided or generated media.

## Human decisions required

No unresolved scope/runtime decisions for implementation. The owner authorized a local
folder resource library; ADR 0003 records the small JSON storage format and initial
layout choices. Backgrounds cover the frame under a readability dim layer; illustrations
fit without cropping in the existing right panel for the full sentence page. Missing or
changed images require explicit reselection/upload and preserve text/audio. The owner confirmed target-Mac background/illustration acceptance on 2026-10-04.

## Standards affected

`docs/standards/code-standards.md` now requires finite media inputs, actual generated-file
validation and safe failed-attempt storage accounting, based on the real Mac failures.

## Implementation notes

- Visual library/probe/API added behind local filesystem and process boundaries.
- Video submission freezes unique image bytes before tool invocation; snapshots count
  toward the existing attempt budget. Omitted images preserve previous behavior.
- Frontend implementation delegated to GPT-6 Luna/max. Backend critical review uses
  GPT-6 Luna/max and OCR deterministic delegation; frontend/test files excluded.
- Final backend checks passed: 182 tests, three Windows symlink permission skips,
  Ruff and existing spike helpers. Normal frontend typecheck, 158 tests and production
  build passed; no checks were removed or weakened.
- GPT-6 Luna/max covered all nine selected backend production files. Its Required
  failed-attempt reservation finding is fixed: safe complete directory accounting
  charges actual retained bytes; unreadable/unsafe attempts retain their full reservation.
  The focused existing failure scenario verifies four failures followed by successful
  explicit retry while preserving evidence. The reviewer accepted this narrow correction.
- Real Mac image rendering exposed unbounded image decoding, tail-frame and color-range
  problems. The renderer now decodes one static frame, repeats the exact finite frame
  count, preserves background hue by applying dimming in RGB, and retains strict format
  validation. Real color samples differ from their expected dimmed RGB by at most 3/255.
- A fresh Qwen API run exposed Matroska millisecond timestamp precision in final copy
  muxing. Fixed page durations and `setts` normalize PTS/DTS separately to the 30 fps grid
  while retaining H264/B-frame ordering. Preflight checks that bitstream filter. Final
  validation also enforces nominal frame rate, exact frozen frame count and stream time.
- Final-source Mac proof reused genuine 3.52/3.28-second Qwen WAVs: 16.833333 seconds,
  505 frames, all presentation timestamps on the 30 fps grid, complete decode, silent
  pause RMS/peak zero, PNG/JPEG/WebP, reload/recovery and unchanged original image bytes.
  Per-page monitored memory peaked below 500 MiB for the small representative fixtures;
  this is observed usage, not a production OS memory quota.
- The updated Mac service passed real image upload/preview, invalid-upload preservation
  and a controlled restart with unchanged IDs/digests. A new complete speech→image-video
  API run then produced 16.366667 seconds, 491 frames, 1,195,290 bytes, 1080p30 H264/AAC.
  Preview returned 206, download returned an attachment, and complete decode passed.
- GPT-6 Luna/max accepted the finite-frame, color and CFR corrections. All nine selected
  backend production files are covered; no Blocker/Required remains in that scope.
- Owner background/illustration acceptance passed on 2026-10-04. Final code revision
  `9fc622d` passed CI run `37156949815`; PR #10 is ready for squash integration.
  The service remains on loopback port 8877.
- TTS voice selection remains P2 Task 010. Restart audio reuse remains P3 Task 008.
