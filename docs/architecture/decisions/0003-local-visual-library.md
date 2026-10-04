# ADR 0003 — Immutable local visual library

- Status: Accepted for Task 009 under the owner's local-folder resource requirement
- Date: 2026-10-03

## Context

The owner requested UI uploads and reuse of backgrounds and sentence illustrations.
The existing application stores generated media under `SPEECH_WORKSPACE`; video jobs
already freeze sentence/audio inputs. Images need durable identity without introducing
a database or coupling sentences to filesystem paths.

## Decision

Use an application-owned library under
`SPEECH_WORKSPACE/visuals/{backgrounds,illustrations}/<asset-id>/`.
Each import receives a server-generated UUID hex ID and an exclusively created folder.
Store validated original bytes as `image.png`, `image.jpg`, or `image.webp`, and write
`asset.json` last as the registration record. Its version-1 schema contains ID, kind,
display name, MIME type, dimensions, byte count and SHA-256. It contains no arbitrary
path. The library validates schema, directory ownership, file bounds, image headers
and digest before listing a resource as available or resolving its bytes.

Accept static PNG, JPEG and WebP up to 10 MiB, 8192 pixels per dimension and 20 million
pixels. Verify decoding through the existing bounded local FFmpeg/ffprobe adapter.
Reject linked paths. Cap the library at 1 GiB and 500 import folders, including failed
imports. No upload overwrites another resource and no automatic deletion is provided.
An interrupted or failed import without valid metadata is not a selectable resource.

The UI uses opaque IDs through the local API. Cache current background and sentence-ID
associations in browser storage, and reconcile them against the server library on load.
The image library is durable; the editable document and speech/export lookup metadata
retain their current lifecycle. No durable project/history format is selected here.

Video submission freezes validated image bytes with the ordered sentence/audio inputs.
Each unique image is copied once into the render attempt, with a 64 MiB aggregate input
limit inside the existing 512 MiB job budget. The renderer consumes only these snapshots.
A missing or changed library asset is rejected before media tool preflight/rendering.

## Layout and sentence editing

Use a static full-video background, scaled to cover 1920 × 1080. Per the owner's
2026-10-04 layout correction, a sentence without an illustration has no background dim
layer and no right-side placeholder panel, throughout speech and the five-second pause.
Illustrated pages retain the dim layer and right-side panel; contain the selected image
and keep it visible for that sentence's audio and pause. Background and illustration
inputs remain independent; no images uses the default light-blue background and dark text.

Bind illustrations to stable sentence IDs. Text edits and reorder preserve bindings;
deletion removes only the association. Split retains the left sentence's illustration
and leaves the new right sentence unassigned. Merge retains the survivor's illustration;
confirm before losing a different illustration from the removed sentence. Replacing the
document clears sentence associations and retains the background. Library bytes remain.

## Consequences

- No new framework, database, model, image SDK or service is required.
- Folder/JSON details remain inside the visual library adapter, not canonical sentences.
- Missing files can be listed as unavailable when their metadata remains valid; recovery
  is explicit reselection or upload and preserves text/audio.
- Future AI illustration producers can use the same import/validation boundary and
  receive an asset ID. No generator/provider is implemented in Task 009.
- Metadata-last registration makes crash remnants unselectable; it does not provide a
  multi-process transaction or OS disk quota. The current one-service local runtime
  serializes imports. Manual cleanup and schema migration remain future work.

## Alternatives considered

- SQLite: useful for a future durable project/history system, but unnecessary for the
  current small immutable resource library and would expand that undecided boundary.
- A single mutable JSON index: fewer files, but every upload would rewrite shared state;
  independent sidecars keep earlier successful imports intact after interruption.
- Client-provided local paths: conflicts with browser uploads and controlled filesystem
  access. Opaque IDs and imported bytes support future producers through the same boundary.
