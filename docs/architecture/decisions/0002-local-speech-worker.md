# ADR 0002 — Isolate the optional local speech runtime

## Status

Accepted implementation decision for Task 006, within ADR 0001's local Python stack and
SpeechProvider boundary. The owner approved the official CPU/0.6B/Aiden path after actual
Mac validation and authorized speech/video integration.

## Context

Task 004 established a frozen model and isolated Python 3.12 environment on the target
Mac. Qwen's optional ML dependencies are large. Sentence generation must reuse the loaded
model, report progress without blocking API requests, and have a bounded failure lifetime.

## Decision

The Qwen SpeechProvider adapter owns one local persistent Python child process invoked
with an explicitly configured interpreter. It loads the frozen local model lazily and
handles serialized synthesis requests through private bounded JSONL IPC. The application
uses project-owned audio values and asset IDs; vendor types remain inside the adapter.

The same FastAPI service continues to serve the browser and application API. The worker
has no network listener or independent public API. It is an optional adapter detail, not
a new service/framework or persistent project format. A deadline or application shutdown
closes the worker; a later explicit request may create a fresh worker.

All worker cache/temp/media paths are confined to the configured approved workspace.
Model access is offline with no remote code. Ordinary CI uses deterministic fake providers
and never installs model dependencies or downloads weights. Speech and rendering share a
local heavy-job gate; success assets are immutable and run metadata is volatile.

## Alternatives considered

- In-process Qwen: simple, but cannot terminate an individual stuck inference safely and
  requires the application interpreter to carry the full ML dependency environment.
- A fresh process per sentence: bounded lifetime, but repeatedly pays import/model-load cost.
- Remote service or a new model backend: outside the approved local MVP and unnecessary.

## Consequences

The adapter owns IPC validation, child lifecycle, bounded output and safe failure handling.
An interpreter/model path must be configured explicitly. Process restart loses volatile
asset selections; existing media files remain intact. End-user packaging and durable
project/history recovery are separate decisions and are not selected here.
