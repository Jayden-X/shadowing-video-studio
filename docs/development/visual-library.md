# Local backgrounds and sentence illustrations

Task 009 extends the fixed video template with optional local images. Configure the
existing `SPEECH_WORKSPACE`, `VIDEO_FFMPEG_EXECUTABLE` and `VIDEO_FFPROBE_EXECUTABLE` settings;
no new image dependency or cloud service is required.

## Use

Choose a background in the visual library or upload a new one. Select/upload an
illustration for each sentence. Uploaded resources remain available for later selection,
including after restarting the service. Current selections are cached in this browser;
the sentence document and speech/export lookup metadata still have their existing
session lifecycle. Missing resources show an actionable error and can be reselected.

Backgrounds cover the frame and are dimmed for readable text. Illustrations fit inside
the right panel without cropping and remain visible during that sentence and its
five-second pause. Generation freezes selections; changing a selection requires a new
export. Earlier image and video files are retained.

Supported uploads: static PNG/JPEG/WebP, at most 10 MiB, 8192 pixels per dimension and
20 million pixels. Local decoding must pass within 20 seconds. Uploads are serialized
with speech/video work. The library allows 1 GiB and 500 import folders, counting failed
imports; there is no automatic deletion or overwrite.

Recommended source sizes: 1920 × 1080 (16:9) for backgrounds; 584 × 736 or
1168 × 1472 for portrait illustrations. Other aspect ratios are accepted: backgrounds
are cropped to cover, while illustrations retain their full image with panel margins.
Use PNG for transparent illustrations.

## Storage and API

See [ADR 0003](../architecture/decisions/0003-local-visual-library.md) for immutable
folder/metadata storage, verification and editing rules. Media belongs outside Git.

- `GET /api/visuals/status`: upload readiness and supported formats/byte limit.
- `GET /api/visuals/assets`: resource metadata and availability, without server paths.
- `POST /api/visuals/assets?kind=background|illustration&name=...`: raw image bytes.
- `GET /api/visuals/assets/{id}`: validated image preview.
- `POST /api/video/jobs`: optional `backgroundAssetId`, and optional
  `illustrationAssetId` per sentence; omission preserves previous behavior.

These routes use the same local-host/origin protection as the existing media API.
Names are display metadata. Browsers never supply filesystem paths.

Image snapshots add at most 64 MiB to one video attempt and remain within its 512 MiB
storage budget. Future AI image creation can register resources through this boundary;
it has no UI, provider or runtime implementation yet.

Video readiness also verifies the installed FFmpeg's `loop`/`setpts` filters and `setts`
bitstream filter. Images are decoded once and repeated for the finite frozen page frame
count. Page concat durations and copied H264 packet timestamps are normalized to the
30 fps grid; the final file is checked for the expected frame count and duration.
An unsupported tool is reported before submission and is never installed automatically.

Failed video attempts retain their files. Once their processes stop, verified complete
directory accounting charges actual stored bytes against the session budget. Unsafe or
unreadable attempts retain their full 512 MiB reservation.
