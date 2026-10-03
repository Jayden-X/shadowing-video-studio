# Qwen3-TTS on the target Mac: runtime spike

## Status and boundary

Task 004 provides a reproducible experiment for the official Qwen Python runtime.
The experiment was reproduced on the target Mac on 2026-10-03. The owner confirmed the CPU
audio is complete and clear, accepted Aiden, and selected the official CPU/0.6B path for
the first video. This note does not select final production packaging. Normal application
checks and CI do not install this experiment's dependencies or download model weights.

The first experiment uses the official **0.6B CustomVoice** checkpoint, **Aiden**, English,
`eager` attention, and float32. CPU and MPS run in separate processes. Both CustomVoice
sizes include Aiden; the official usage examples demonstrate CUDA, so MPS compatibility
must be measured on the actual Mac. See the [Qwen README](https://github.com/QwenLM/Qwen3-TTS).

## Preconditions

- Native ARM64 macOS shell and interpreter; this script refuses Windows, Intel, and Rosetta.
- Existing system `/usr/bin/python3` (3.9+) for the path guard, and an existing authorized `uv`.
- An existing, explicitly approved absolute workspace directory with no symlink components.
- Network access for the isolated Python runtime, PyPI packages, and the official HF model.
- Enough free disk and RAM for model loading. The official model repositories currently total
  about [2.5 GB for 0.6B](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/tree/main)
  and [4.52 GB for 1.7B](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/tree/main),
  including their speech tokenizer. Dependencies and temporary downloads require additional
  space. These numbers are download sizes, not RAM requirements or a hardware guarantee.

The system shell, Python, `sw_vers`, and `sysctl` are executed read-only. The runner does not
change system Python, install globally, create a launcher, or remove existing artifacts.
An already authorized `uv` executable may be supplied using `UV_BIN`; its location is not
the experiment output location.

## Preparation

Run from the repository, or copy the four runtime files from `scripts/spikes/` into the
approved workspace before running. Keep them together:

- `qwen3_tts_macos.sh`
- `qwen3_tts_macos.py`
- `qwen3_tts_workspace.py`
- `qwen3-tts-requirements.in`

Use the exact absolute path approved for the Mac. The examples deliberately require replacing
`/absolute/approved/workspace`; they do not assume a home directory or request broader access.

```bash
UV_BIN="/absolute/path/to/authorized/uv" \
  bash scripts/spikes/qwen3_tts_macos.sh \
  --workspace-root /absolute/approved/workspace prepare
```

Preparation creates a new directory under `spikes/task004/runtimes/` in that workspace:

1. Installs managed Python 3.12 into the workspace's experiment cache and creates a fresh venv.
2. Resolves `qwen-tts==0.1.1`, `torch==2.10.0`, and `torchaudio==2.10.0` into a hash lock,
   then syncs that venv. Qwen itself fixes Transformers 4.57.3 and Accelerate 1.12.0.
3. Downloads the complete official 0.6B snapshot at
   `85e237c12c027371202489a0ec509ded67b5e4b5`, including `speech_tokenizer/`.
4. Writes `preparation.json` with package versions, the lock digest, download duration,
   model revision, and safe hardware metadata.

The checkpoint is loaded from the frozen local snapshot in offline mode during inference.
This avoids accidentally mixing top-level weights and child components from different
revisions. See [HF snapshot download documentation](https://huggingface.co/docs/huggingface_hub/guides/download)
and the [official Qwen loader](https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/main/qwen_tts/core/models/modeling_qwen3_tts.py).

The hash lock and installed versions belong to this particular experiment. Preserve them
with the result; new preparation on a later date can resolve newer transitive packages.
See [uv dependency locking](https://docs.astral.sh/uv/pip/compile/). No FlashAttention, CUDA,
MLX, voice cloning, or model conversion is installed by the scripts.

## Run CPU and MPS separately

Copy the generated runtime **name** printed at the end of preparation, without its path.

```bash
bash scripts/spikes/qwen3_tts_macos.sh \
  --workspace-root /absolute/approved/workspace run PREPARED_RUNTIME_NAME cpu

bash scripts/spikes/qwen3_tts_macos.sh \
  --workspace-root /absolute/approved/workspace run PREPARED_RUNTIME_NAME mps
```

MPS uses `PYTORCH_ENABLE_MPS_FALLBACK=0` initially. If it fails on an unsupported operation,
preserve that failure and optionally run a separate experiment:

```bash
bash scripts/spikes/qwen3_tts_macos.sh \
  --workspace-root /absolute/approved/workspace run PREPARED_RUNTIME_NAME mps \
  --mps-cpu-fallback
```

The resulting metadata labels fallback explicitly. It is not proof of a fully accelerated
path. [PyTorch MPS](https://docs.pytorch.org/docs/2.10/notes/mps.html) exposes capability checks,
while [MPS fallback](https://docs.pytorch.org/docs/2.10/mps_environment_variables.html) only
handles certain unsupported operations. The scripts never automatically switch device,
dtype, model, voice, or backend after a failure.

Every invocation creates a fresh result directory. Existing JSON and WAV evidence is never
overwritten. Failed runs exit nonzero and retain a local `failure.log`; do not commit that
log because tracebacks can contain machine-specific paths.

## Measurements and review

The runner generates this deliberately synthetic sentence twice with seed 42, a 256-token
limit, and no style instruction:

> Hello. This is a short English shadowing practice sentence.

It records:

- safe Mac version/chip/architecture/RAM/CPU and Python/package versions;
- model-loading, import, first-generation, and warm-generation durations;
- audio sample rate, mono sample count, duration, peak/RMS amplitude, and generation/audio
  duration ratio;
- Darwin process peak RSS and approximate sampled MPS tensor/driver memory peaks;
- requested/reported device, dtype, attention, fallback flag, voice, and model revision.

Generation timing includes completion of the waveform and transfers; MPS kernels are
[synchronized](https://docs.pytorch.org/docs/2.10/generated/torch.mps.synchronize.html) before
and after timing. MPS memory is sampled every 100 ms, so brief peaks may be missed.
[Tensor allocation](https://docs.pytorch.org/docs/2.10/generated/torch.mps.current_allocated_memory.html)
excludes allocator caches; [driver allocation](https://docs.pytorch.org/docs/2.10/generated/torch.mps.driver_allocated_memory.html)
includes them and Metal framework allocation. Do not add these to RSS to claim total unified
memory use. Darwin RSS is recorded in bytes, following the
[current kernel implementation](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/kern/kern_resource.c).

Nonempty, finite, nonsilent waveform checks reject structural failures. They do not establish
correct pronunciation or complete spoken content. Listen to `first.wav` and `warm.wav`, check
that the sentence finishes, and record intelligibility, Aiden suitability, artifacts, and
whether latency/memory is acceptable for sentence preview and later video generation.
The generated status leaves `audio_review` pending. Do not mark Task 004 complete from JSON
alone or apply an invented latency acceptance threshold.

The tiny spike `SpeechProvider` protocol returns project-owned sample/rate values. The Qwen
wrapper converts vendor output at that boundary. Its fake smoke test proves the contract can
be used without Qwen imports; it is not a production adapter or real model proof.

## Filesystem and privacy

Runtime/cache/output paths are resolved and constrained to the supplied physical workspace.
The script rejects a symlink escape and `..` runtime names. Mac case normalization is accepted.
Python/uv/HF/PyTorch/Numba/matplotlib/Gradio and temporary write locations are set under
`spikes/task004/`; Python bytecode/user site packages are disabled. Model downloads use no
HF credential, and inference is offline. This path guard is protection against accidental
misconfiguration, not an operating-system sandbox against concurrent malicious path changes.
The venv interpreter's symlink target must also remain inside the workspace; its invocation
path is preserved so Python and uv use that venv rather than its managed base interpreter.

Use a workspace outside Git, or the repository's ignored `tmp/` directory. Do not commit
models, WAV files, installed Python/venv, caches, logs, or raw runtime JSON. Only copy a reviewed
summary of safe hardware values and results into this note; exclude usernames, serial numbers,
hostnames, UUIDs, credentials, absolute paths, and private source text. The preparation JSON's
snapshot path is relative to its own runtime directory.

## Lightweight checks

These commands require no model packages or download. Helper tests put temporary fixtures
under their own ignored `scripts/spikes/tmp/` directory.

```bash
python -m unittest discover -s scripts/spikes -p 'test_*.py' -v
python -m py_compile scripts/spikes/qwen3_tts_macos.py scripts/spikes/qwen3_tts_workspace.py
bash -n scripts/spikes/qwen3_tts_macos.sh
```

On Windows, invoking the actual prepare command must exit 2 before creating a runtime. The
standard application check remains `bash scripts/check.sh`; it does not execute this spike.

## Target Mac result: 2026-10-03

| Evidence | Result |
| --- | --- |
| Install/hash lock and frozen snapshot | Reproduced; 88 packages, Python 3.12.15, uv 0.12.22, full model revision above |
| Aiden support reported by the loaded model | `aiden` present; both device profiles generated audio |
| CPU first/warm audio and timings | 24 kHz mono, 4.08 s each; 10.37 / 9.28 s generation |
| MPS first/warm audio and timings | 24 kHz mono, 4.24 / 10.80 s; 19.20 / 41.92 s generation; fallback disabled |
| CPU peak RSS | 3.85 GiB |
| MPS peak RSS / sampled tensor / driver | 2.25 / 4.28 / 6.49 GiB; separate metrics, not additive |
| Human listening review | Owner confirmed CPU sample complete/clear and Aiden suitable for first release |
| MVP suitability and selected local backend | Official PyTorch CPU, 0.6B CustomVoice, float32/eager; explicitly selected by owner |

Hardware: Apple M4, 16 GiB RAM, 10 logical CPUs, macOS 15.5, native ARM64. Installed versions:
qwen-tts 0.1.1, torch/torchaudio 2.10.0, Transformers 4.57.3, Accelerate 1.12.0,
SoundFile 0.14.0. Hash lock SHA-256:
`c1bc2496f7207c76a5ddbdddada309808a70fb16a1bb82ffb3114cdacc1d6195`.
CPU import/model load took 32.08/5.16 s; MPS took 6.13/5.50 s. The first import was cold,
so these are observations rather than a controlled comparative startup benchmark.
`OMP_NUM_THREADS=4` and `MKL_NUM_THREADS=4` limited the experiments' thread configuration.

CPU is usable for the manually initiated first video; approximately 9–10 s per short
sentence means preview needs clear progress, successful audio reuse, and sentence-level
regeneration. These two short generations do not prove long-dialogue latency, pronunciation
coverage, or stability under memory pressure. MPS float32/eager was slower and produced
different durations on repeated seeded input; neither MPS sample received human approval.
It is retained as measured evidence, not selected as the default. No automatic backend,
dtype, model or voice substitution was performed.

Both profiles emitted missing-SoX/FlashAttention notices but generated valid WAVs successfully;
the experiment did not install either system SoX or FlashAttention. Do not generalize that
result to cloning or every Qwen mode. Eleven lightweight tests passed on the actual Mac,
including the symlink escape test skipped by the Windows account.

### Existing resources and packaging implications

Owner-authorized read-only discovery found a complete official 1.7B CustomVoice cache, a
previous Python 3.14 TTS project using MPS/float16/SDPA/Aiden, an older Conda environment,
and existing Homebrew FFmpeg/ffprobe 9.0.2. No old script/environment was modified or executed.
The old project had WAV headers but no reproducible dependency/acceptance note. Its interpreter
version conflicts with this project's Python 3.12 baseline; the Conda torch/torchaudio versions
also differed. Reuse the model cache and installed FFmpeg where configuration is verified;
do not treat old artifacts as proof that the old environment still runs. A later optimized
MPS experiment can use the old configuration as a hypothesis without changing the accepted
CPU default.

The first development runtime can reuse this isolated Python 3.12 environment and frozen
model. Keep the model loaded for consecutive sentences and serialize heavy generation.
Distribute model downloads separately from application code/ordinary CI, retain the exact
dependency/model versions, and keep generated assets in the approved local workspace.
Final double-click packaging remains a separate decision; this spike introduces no global
Python replacement, persistent project format, or new desktop framework.
