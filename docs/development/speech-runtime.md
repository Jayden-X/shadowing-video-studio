# Local sentence speech runtime

Task 006 uses the approved official Qwen3-TTS 0.1.1 CPU path: frozen
`Qwen3-TTS-12Hz-0.6B-CustomVoice`, float32, eager attention, English/Aiden.
There is no automatic model download, runtime installation, backend fallback or MPS optimization.
The approved revision is `85e237c12c027371202489a0ec509ded67b5e4b5`;
a different revision requires explicit validation/selection before changing the adapter.

## Configure an existing runtime

Set backend-only values in the ignored root `.env`:

```dotenv
SPEECH_WORKSPACE=/absolute/existing/ignored/runtime-directory
SPEECH_MODEL_PATH=/absolute/model-cache/snapshots/<40-character-frozen-revision>
SPEECH_PYTHON_EXECUTABLE=/absolute/existing/python3.12-runtime/bin/python
SPEECH_TIMEOUT_SECONDS=600
```

Use the already approved Task 004 isolated runtime and model cache on the target Mac.
The workspace must be a real existing absolute directory, separate from the model cache.
Mac writes remain inside the approved project directory or `~/.cache`.
The executable defaults to the backend interpreter when blank; speech stays unavailable
if its optional dependencies are absent. Python 3.12, Qwen 0.1.1, Transformers 4.57.3,
torch/torchaudio 2.10.0, Accelerate 1.12.0 and SoundFile 0.14.0 are checked through metadata without importing/loading
the model. Readiness is a preflight, not proof that inference succeeds.

Start the normal local service with the existing development launcher, which loads `.env`,
or use `uv run --env-file ../.env uvicorn shadowing_video_studio.main:app --host 127.0.0.1 --port 8765`
from `backend/`. **Use one ASGI worker**; the job gate and metadata are process-local.

## Worker and writes

The Qwen adapter starts a project-owned Python worker at the first Generate action.
It runs the explicitly configured interpreter with isolated imports/bytecode disabled;
source text crosses a bounded stdin JSONL pipe and is never shell code. The model stays
loaded across sentences/jobs. Vendor stdout/stderr is suppressed; only bounded protocol
responses return to the backend. Source, secrets and raw provider diagnostics are not logged.

Each service session creates an exclusive `speech/<opaque-session-id>/` under the workspace.
WAV files use exclusive creation and opaque UUID IDs. Runtime HOME, TMP/TEMP/TMPDIR,
Hugging Face, Torch and XDG caches all point beneath that session's runtime directory;
offline flags prevent network model fetching. Existing snapshots are read in place.
No unrelated environment secrets are passed to the worker.

The sentence deadline includes initial model loading. Timeout, protocol failure, service
shutdown or caller cancellation kills and reaps the owned worker tree (POSIX process group;
Windows suspended startup plus kill-on-close Job). Later explicit work can load a fresh worker.
Failed sentences are not automatically retried. Successful and partial files are preserved.

Production uses `max_new_tokens=4096`. A temporary per-call completion observer delegates
to the original official talker generation, requires a single-sample sequence ending in
the codec EOS token, and restores the method in `finally`. Missing EOS/unknown structures
fail safely and advise splitting the sentence. A normal end marker does **not** establish
pronunciation, transcript completeness or voice quality: listen before using the audio.

## API and reuse

- `GET /api/speech/status`: safe availability/reason and voice/model/backend.
- `POST /api/speech/jobs`: explicit frozen `[{id,text}]`, optional `force`; returns 202 Job.
- `GET /api/speech/jobs/{id}`: queued/running/completed/failed, with per-sentence progress.
- `GET /api/speech/assets/{id}`: validated WAV bytes, never a client path.

Speech routes require a loopback Host and, when the browser supplies Origin, a loopback
HTTP(S) origin. The Vite loopback proxy and local CLI requests work; foreign browser origins
and DNS-rebound hostnames are rejected. This does not introduce accounts or remote access.

Limits: 1–100 unique sentences, each up to 4,000 UTF16 units and total 20,000;
`force:true` requires one sentence. IDs are nonblank, unique, at most 100 UTF16 units.
A second job requiring generation returns 409 while the shared local media gate is held.
An entirely cached request can complete immediately. Partial failure ends with ready/failed
rows and a safe job error; successful assets remain eligible for reuse.

WAVs must be mono PCM16/24 kHz, positive duration, at most 360 seconds and 32 MiB.
There are at most 100 jobs and 1 GiB of reserved/generated media per service session.
Failed attempts reserve their maximum allocation, preventing repeated failures from bypassing
the ceiling. No automatic pruning/deletion is introduced.

Reuse requires **exact sentence ID + exact text + provider configuration fingerprint**.
Regeneration produces a new asset and preserves prior WAVs. Editing/replacing text prevents
matching the old binding; the UI must clear ineligible selections. Task 007 must call
`SpeechAssets.match(asset_id, SpeechSentence(id,text), fingerprint)` before rendering.
This checks bindings, file boundaries and recorded content hash. The shared `HeavyJobGate`
must also coordinate future video rendering; it is not a cross-process lock.

Job/cache/asset bindings are volatile. Service restart loses lookup metadata; prior WAVs
remain on disk and are not rediscovered as trustworthy assets. Browser refresh loses the
document/selection. A durable project/history format is deferred. Ordinary CI uses fakes
and tiny temporary WAVs; it never installs Qwen or downloads weights.

Official behavior references: [Qwen wrapper](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py)
and [talker generation](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/core/models/modeling_qwen3_tts.py).
The completion observer is version-gated to Qwen 0.1.1; runtime/source changes require a new check.
