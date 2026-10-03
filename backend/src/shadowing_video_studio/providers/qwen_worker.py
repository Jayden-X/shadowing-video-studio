"""Trusted standalone worker: stdlib probe, then optional official CPU Qwen.

This file intentionally does not import the application or its dependencies.
It runs in the explicitly configured isolated Python environment.
"""

import contextlib
import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path

MAX_NEW_TOKENS = 4096
MAX_SECONDS = 360
MAX_REQUEST_BYTES = 65536


class IncompleteSpeech(Exception):
    pass


def probe() -> dict[str, object]:
    try:
        versions = {
            name: importlib.metadata.version(name)
            for name in (
                "qwen-tts",
                "torch",
                "torchaudio",
                "transformers",
                "soundfile",
                "accelerate",
            )
        }
        available = (
            sys.version_info[:2] == (3, 12)
            and versions["qwen-tts"] == "0.1.1"
            and versions["transformers"] == "4.57.3"
            and versions["torch"].split("+")[0] == "2.10.0"
            and versions["torchaudio"].split("+")[0] == "2.10.0"
            and versions["accelerate"] == "1.12.0"
            and versions["soundfile"] == "0.14.0"
            and all(
                importlib.util.find_spec(name) is not None
                for name in (
                    "qwen_tts",
                    "torch",
                    "torchaudio",
                    "transformers",
                    "soundfile",
                    "accelerate",
                )
            )
        )
        return {"available": available}
    except (ImportError, importlib.metadata.PackageNotFoundError, ValueError):
        return {"available": False}


def generate_verified(model, text: str, voice: str = "Aiden"):
    """Observe the original talker result, restoring its method on every path.

    qwen-tts 0.1.1 discards EOS evidence when returning decoded WAVs. The
    underlying HF result retains sequences. No decoding algorithm is replaced.
    EOS confirms generation termination, not pronunciation/content quality.
    """
    talker = model.model.talker
    eos = model.model.config.talker_config.codec_eos_token_id
    original = talker.generate
    observed = False

    def checked_generate(*arguments, **keywords):
        nonlocal observed
        result = original(*arguments, **keywords)
        try:
            sequences = result.sequences.tolist()
            valid = (
                isinstance(sequences, list)
                and len(sequences) == 1
                and isinstance(sequences[0], list)
                and len(sequences[0]) > 1
                and sequences[0][-1] == eos
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise IncompleteSpeech
        observed = True
        return result

    talker.generate = checked_generate
    try:
        result = model.generate_custom_voice(
            text=text,
            language="English",
            speaker=voice,
            non_streaming_mode=True,
            max_new_tokens=MAX_NEW_TOKENS,
        )
        if not observed:
            raise IncompleteSpeech
        return result
    finally:
        talker.generate = original


def write_verified_audio(model, text: str, destination: Path, voice: str = "Aiden") -> None:
    import numpy as np
    import soundfile as sf

    wavs, sample_rate = generate_verified(model, text, voice)
    if not isinstance(wavs, list) or len(wavs) != 1 or sample_rate != 24000:
        raise IncompleteSpeech
    audio = np.asarray(wavs[0])
    if (
        audio.ndim != 1
        or not 0 < len(audio) <= MAX_SECONDS * sample_rate
        or not np.isfinite(audio).all()
        or not np.any(audio != 0)
    ):
        raise IncompleteSpeech
    # Exclusive creation preserves every prior generated selection.
    with destination.open("xb") as handle:
        sf.write(handle, audio, sample_rate, format="WAV", subtype="PCM_16")


def serve(model_path: Path, runtime: Path) -> None:
    # Preserve a dedicated protocol fd; suppress native/vendor output as well as
    # Python print/log warnings. Neither full source nor paths become app logs.
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1) as protocol:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
            os.dup2(sink.fileno(), sys.stderr.fileno())
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                model = None
                while raw := sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1):
                    if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                        return
                    try:
                        request = json.loads(raw)
                        if (
                            set(request) != {"text", "destination", "voice"}
                            or not isinstance(request["text"], str)
                            or not isinstance(request["voice"], str)
                        ):
                            raise ValueError
                        destination = Path(request["destination"])
                        if (
                            not destination.is_absolute()
                            or destination.parent != runtime.parent
                            or destination.suffix != ".wav"
                            or destination.exists()
                            or destination.parent.resolve() != runtime.parent
                        ):
                            raise ValueError
                        if model is None:
                            import torch
                            from qwen_tts import Qwen3TTSModel

                            torch.set_num_threads(4)
                            model = Qwen3TTSModel.from_pretrained(
                                str(model_path),
                                device_map="cpu",
                                dtype=torch.float32,
                                attn_implementation="eager",
                                local_files_only=True,
                                trust_remote_code=False,
                            )
                        speakers = model.get_supported_speakers() or []
                        if request["voice"].lower() not in speakers:
                            result = {"ok": False, "error": "voice"}
                        else:
                            write_verified_audio(
                                model, request["text"], destination, request["voice"]
                            )
                            result = {"ok": True}
                    except IncompleteSpeech:
                        result = {"ok": False, "error": "incomplete"}
                    except Exception:
                        result = {"ok": False, "error": "generation"}
                    protocol.write(json.dumps(result) + "\n")
                    protocol.flush()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "probe":
        print(json.dumps(probe()))
    elif len(sys.argv) == 4 and sys.argv[1] == "serve":
        serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit(2)
