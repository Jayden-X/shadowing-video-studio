# Future Task and Control Seams

## Status and boundary

Design requirements reserved for a later release, based on the owner's request. This document selects no scheduler, persistence format, MCP transport, framework, or credential strategy.

The MVP stays manually initiated, runs one video at a time, and contains no scheduler or MCP server. Existing provider/rendering seams remain in place.

## Prepared work and execution attempts

A future application task represents assigned work independently of the UI session. It has a stable `taskId`; each attempt has a distinct `runId`. Preparation references frozen or versioned source and a reviewed canonical sentence list with stable sentence IDs. A later source/edit change creates an explicit revised assignment rather than silently changing an existing run.

Preparation must make the following visible before unattended execution:

- required human inputs, sentence/voice review, and unresolved decisions
- dependencies and required assets, model/provider availability, and configuration references
- permitted operations and output locations
- which approvals are already satisfied and which results still require human confirmation
- suspension/schedule intent and the policy for a task that cannot safely proceed

Readiness checks run when work is assigned and again before execution where conditions may have changed. Credentials are resolved through the selected local secret mechanism; task metadata contains safe references only. An unresolved mandatory review pauses the task and reports the needed action. A declared unattended policy cannot override a product-required human review.

The task lifecycle must support suspended preparation, scheduled start, execution, interruption, and recovery. These are capabilities, not a prescribed enum or serialized format. A UI session ending must not be treated as proof that an attempt completed or failed.

## Scheduling and recovery

Keep scheduling policy separate from the application workflow. It may later choose an eligible task when a scheduled time or defined idle condition is met. Record the schedule's time zone; daylight-saving ambiguity, clock changes, missed starts, machine sleep, idle detection, and user activity policy need an ADR before implementation.

Several tasks may be prepared, but the first future executor permits only one heavy local model/media job at a time. Resumed work uses the same execution limit. Broader concurrency is a separate product/resource decision.

Classify failures so the application can distinguish missing human input/permission, invalid input, unavailable dependencies, transient provider/process failures, cancellation, and unknown outcomes. Each case needs an explicit pause, fail, or retry policy. Do not retry merely because an error occurred.

Recovery must use durable, validated checkpoints and reusable asset references once persistence is selected. A retry is allowed only when the operation's idempotency and previous outcome are known; uncertain completion must be reconciled before repeating a side effect. Resume must verify input/configuration versions and checkpoint validity. Cancellation and interruption must record partial progress and must not silently delete user assets or completed outputs.

## Diagnostic trace

Record enough ordered events to reconstruct an attempt and explain why it stopped. Events should carry, where relevant:

- `taskId`, `runId`, correlation identity, and canonical sentence ID
- timestamps, operation/state changes, and their reason
- adapter/provider/model version and safe configuration values or references
- input-version and generated-asset references
- sanitized error category/cause, checkpoint, retry attempt, cancellation, and outcome
- human approval/required-action references

Keep full source text and media in authorized project storage, separate from diagnostic events. Do not log secrets, authorization headers, credential-bearing configuration, full dialogue, or raw provider responses that contain them. Retention and storage are deferred decisions; this seam does not require event sourcing.

## Shared application control and MCP

UI, a future CLI, and MCP are adapters to the same application commands and status/result queries. Providers and persistence remain behind application ports. No control adapter may write domain state, modify project storage, or launch model/media processes directly.

Expose explicit capabilities with validated inputs and useful status/errors. A future local MCP client may inspect capabilities, prepare/edit assignments, and request supported execution actions. Start, resume, cancel, and export must enforce the command's permissions and the user's applicable approvals; required human review remains authoritative. Input revisions invalidate affected approvals where appropriate.

The initial future MCP deployment boundary is local. Before implementation, choose a local transport, permitted client/operation scope, connection authorization, and controlled filesystem access. Do not assume that local access grants unrestricted control, and do not choose a new credential strategy in this design note.

## Decisions required before implementation

- Task/checkpoint persistence, versioning, and compatibility policy.
- Concrete lifecycle transitions, retry/idempotency contracts, and recovery validation.
- Schedule/time-zone/daylight-saving semantics and idle/resource policy.
- Diagnostic storage, access, and retention.
- Local MCP transport, capability contracts, authorization, and approval handling.

Each implementation must enter through a scoped task and any required ADR. These seams do not expand the current task queue into an automatic product-development plan.
