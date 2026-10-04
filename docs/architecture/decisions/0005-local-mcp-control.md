# ADR 0005 — Local MCP control in the existing application process

## Status

Accepted for Task013. On 2026-10-04 the owner authorized implementing MCP outside Task008,
then explicitly approved the official Python MCP SDK and the concrete local access policy:
disabled by default, direct local connections, distinct read/execute credentials configured
in local environment, and human review of every frozen speech/video request.

## Context

Task005 reserved shared UI/CLI/MCP application commands. Task008 is developed separately;
project/history storage and frontend synchronization cannot be assumed here. Speech and
video already share a single-heavy-job gate in the FastAPI process. A second job service
would break this boundary and volatile asset lookup.

## Decision

Use official `mcp==1.30.0` FastMCP Streamable HTTP mounted at `/mcp/` in the existing
single FastAPI process. Manage its session-manager lifecycle with application lifetime.
MCP tools and HTTP generation handlers call the same project-owned application commands
and service instances. No protocol adapter directly runs media/model subprocesses.

Use direct loopback connections with validated Host/Origin, no forwarded-host trust,
and independent backend-only environment tokens for read and execute scope. Both empty
disables the endpoint; tokens are startup snapshots, never persisted by this feature,
logged or returned. No OAuth, remote service, accounts or credential store is introduced.

Generation has a session-only frozen review request identified by caller `requestId`.
The local server-rendered browser page shows exact text/configuration and video audio
references. Its per-request nonce is never returned by MCP tools. Approval/rejection is
separate from execution. Execution revalidates configuration/bindings through existing
services, owns a shielded submission task, and returns the original outcome on repeats.
Changed inputs require a fresh ID/review. Unknown outcomes never trigger blind retries.

Tickets expire 30 minutes after creation and are limited to 100 per session; no eviction
of idempotency records. Restart discards tickets, not generated files. This deliberately
does not select Task008's persistence, project identities or restart recovery format.

## Alternatives considered

- Independent stdio backend: duplicates media ownership and loses shared job/asset state.
  A future thin stdio-to-existing-backend bridge remains possible for client compatibility.
- Unauthenticated local HTTP: insufficient explicit client/operation authorization.
- Remote/OAuth deployment: unnecessary for current single-user local boundary.
- Waiting for Task008: owner requested independent progress; session-only requests permit
  real capability/preparation/generation integration without inventing project storage.

## Consequences

Clients need Streamable HTTP plus configurable Authorization headers. Multiple workers,
proxies and remote access are unsupported. Local trusted processes are not isolated from
the human browser approval surface. Durable approval, project synchronization and replay
need explicit follow-up contracts after Task008; no automatic restart execution is added.
