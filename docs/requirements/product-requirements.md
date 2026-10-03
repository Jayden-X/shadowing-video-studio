# Product Requirements

## Status

Draft / discussion baseline. This document captures the currently confirmed direction and should be updated as decisions are made.

## Product goal

Create a repeatable local tool for producing English listening and shadowing-practice videos.

Primary flow:

**paste dialogue → process/confirm sentences → preview voice → generate video → review/regenerate → save MP4**

The product is an **English shadowing video generator**, not a general-purpose video editor and not a digital-human platform.

## MVP boundary

The first version is intentionally limited to:

- One primary user on the current Mac.
- One video per run/project flow.
- Paste-in text input.
- No account system.
- No multi-user collaboration.
- No cloud runtime.
- No batch jobs.
- Manual initiation of the current workflow; no scheduler or MCP server in MVP.

These are MVP product limits only. The architecture should avoid hard-coding assumptions that would make later expansion unnecessarily expensive.

Likely future extensions may include:
- Other devices/operating systems.
- File import.
- Batch jobs.
- Multiple prepared tasks that can be suspended and scheduled for local execution.
- AI control through MCP using the same application capabilities as the UI.
- Local and cloud execution modes.
- More templates.
- More TTS engines/voices.
- More AI providers.
- Optional user/account capabilities.

Do not prebuild these features in the MVP.

## Confirmed future task-control requirements

These requirements preserve a design path beyond MVP. They do not authorize implementing scheduling, unattended execution, or MCP in the first release.

### Prepared tasks and scheduled execution

The user should be able to define and assign multiple tasks while using the computer, suspend them, and arrange execution for an idle period or a scheduled time such as overnight.

Before a task is assigned for unattended execution, preparation must identify required human input and review, dependencies, permissions, provider/model configuration, and how results will be confirmed. A run must use a frozen or versioned source and reviewed canonical sentence list so later editing does not silently change assigned work.

Execution should proceed without routine intervention once preparation is complete. If a required human decision remains or an exception prevents safe continuation, the task must pause with an actionable reason. Scheduling must never silently skip a required review gate.

Tasks need stable identities, recoverable progress, and a trace of attempts, failures, retries, cancellations, and results sufficient to diagnose a run and improve the workflow. Trace data must exclude secrets and full user dialogue by default.

The initial future local executor should run at most one heavy model/media job at a time, even when several tasks are prepared. More concurrency requires a separate decision. Scheduling must record its time zone and define daylight-saving and idle-detection behavior before implementation.

### MCP control

Future AI clients should be able to discover capabilities, prepare tasks, inspect progress and results, and request supported execution actions through MCP.

MCP must use the same application commands, validation, permissions, and human-review rules as the UI or a future CLI. It must not modify project files/state directly or bypass review. Starting, resuming, cancelling, and exporting work must respect the user's declared approval policy and validated inputs.

The first future MCP boundary is local. Transport, authorization details, and credential handling require decisions before implementation; this requirement does not introduce remote access or a new secret strategy.

See [future task and control seams](../architecture/future-task-control.md) for the architecture constraints and deferred decisions.

## Default video settings

- Video: 16:9, 1920 × 1080.
- One sentence per page.
- Default shadowing pause: 5 seconds after each sentence.
- Layout: large English text on the left; visual/character area on the right; dynamic waveform at the bottom.
- TTS: Qwen3-TTS.
- Default voice: Aiden.
- Voice cloning is not part of the current default.
- Output: MP4.

## Text and sentence processing

The user must be able to choose how input text is prepared.

### Manual mode

Support:
- Edit sentence text.
- Add sentence.
- Delete sentence.
- Split sentence.
- Merge sentences.
- Reorder sentences.

### AI-assisted mode

AI may prepare/segment the dialogue.

Initial provider targets:
- DeepSeek.
- Codex.

Requirements:
- Provider-specific implementation must be behind an abstraction.
- AI output must not bypass user review.
- The user can edit the AI result using the same manual tools before TTS/video generation.
- Failure of an AI provider must not corrupt the user's source text.

## Audio quality and regeneration

The workflow must support:
- Sentence-level preview.
- Sentence-level regeneration.
- Reuse of successful generated results.
- Failure recovery without regenerating the entire video whenever practical.

Automatic quality checks may assist but must not replace user review in the first version.

## Template philosophy

MVP should use a fixed template plus a small number of understandable settings.

Do not build a drag-and-drop video editor in MVP.

## Persistence and outputs

MP4 export is required.

Preferred behavior:
- New outputs should not silently overwrite prior final videos.
- Generated intermediate assets should be reusable within a project/run when safe.
- Runtime/generated media should stay outside Git.

Exact local project/history storage design is still to be decided.

## Open decisions

- Concrete application stack and packaging strategy.
- Exact project/history persistence model.
- Which non-default voices are exposed in MVP.
- Which simple style controls are exposed.
- Exact cancellation/resume behavior.
- Exact export folder UX.
