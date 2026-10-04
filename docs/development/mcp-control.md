# Local MCP control

Task013 adds a local control adapter on Task008's initial saved-project implementation,
`feature/008-project-history` at commit `902bb3a`. Saved-project storage/restore remains
supported by the existing UI and API. Only MCP project binding and editor synchronization
are deferred from this delivery. The integration target is subject to further changes.
Its initial API, application commands and project-history documentation have been read;
this delivery preserves their storage/restore behavior and leaves MCP project binding
for a later integration task. A control request is **not** a project: it contains a frozen
input snapshot for one speech/video submission, independent of the browser editor.

## Tools

| Tool | Access | Behavior |
| --- | --- | --- |
| `get_capabilities` | read | Live local model/voice/media availability, limits, deferred features |
| `list_text_providers` | read | Configured provider availability; no source sent |
| `list_visual_assets` | read | Existing image IDs and metadata |
| `propose_sentences` | execute | Explicit provider draft; may send source externally |
| `request_generation` | execute | Freeze validated speech/video input for local review |
| `get_request` | read | Review/submission state; never approval nonce |
| `execute_request` | execute | Submit approved frozen work; repeat returns same submission |
| `get_job` | read | Progress/output only for jobs issued by reviewed MCP requests in this session |

Proposals must be reviewed as sentences before speech. Video approval requires listening
to the exact audio references and inspecting selected background/illustration previews
displayed by the local review page. Speech payload `force`
is allowed only with one sentence for regeneration. Video payload uses sentence/audio IDs
and optional existing background/illustration IDs; never filesystem paths.

## Session workflow

1. Discover capabilities/voices and prepare sentence text.
2. Call `request_generation` with a unique `requestId`, operation `speech` or `video`, and
   the corresponding validated payload. No generation starts.
3. Ask the owner to open the returned `reviewPath` on the backend's local origin. They
   inspect exact text/configuration, audio and image previews where applicable, then
   approve or reject.
4. Query `get_request`; call `execute_request` only after approval.
5. Query `get_job` using the result's job ID. Use existing local preview/download routes.

For example, the tool arguments for a speech request are:

```json
{
  "request": {
    "requestId": "demo-speech-1",
    "operation": "speech",
    "payload": {
      "sentences": [{"id": "one", "text": "Hello, how are you?"}],
      "voice": "Aiden",
      "force": false
    }
  }
}
```

The payload must match the selected operation: `speech` accepts text/voice/force;
`video` requires an `assetId` on each sentence and accepts optional
`backgroundAssetId`/`illustrationAssetId`. Extra fields and mismatched operation payloads
fail validation. Request IDs contain 1–100 ASCII letters, digits, underscores or hyphens.

The `speech` object returned by `get_capabilities` uses the same camelCase shape as
`GET /api/speech/capabilities`: `defaultVoice`, `voices`, and each voice's `configurationFingerprint`. The MCP envelope additionally carries media readiness,
access scope, limits, review policy and deferred MCP features; `deferred.projects` and
`deferred.historyRecovery` concern MCP integration, not the existing saved-project UI/API.

Use the selected voice's `configurationFingerprint` from current capabilities when available. An omitted value
is resolved and frozen before review; execution revalidates it. A matching original
request with the same ID returns its existing ticket. Different inputs with that ID fail.
Approval applies only to the frozen payload and expires 30 minutes after creation.

A service session holds at most 100 requests. Do not invent retries after a failed or
unknown submission: inspect existing jobs, fix the cause, then explicitly create/review
a new request. Client disconnection does not cancel an accepted generation request. Jobs
remain subject to the existing single-heavy-job gate.

## Task008 integration seam

The initial `feature/008-project-history` target implements saved projects, immutable
output history and validated audio reopening through
[ADR 0004](../architecture/decisions/0004-project-history-persistence.md) and
[its operating guide](project-history.md). Task013 does not change that storage format.
Its transient MCP submissions do not carry a `ProjectCommand`, update the editor or
register a saved project's history. The follow-up should use these existing contracts:

- Project creation accepts a 32-hex-character `operationToken`, `name` and validated
  `snapshot`. Saves also require `expectedRevision`; stale revisions must remain conflicts.
- Snapshots preserve `documentId`, `document`, `voice`, `backgroundAssetId`,
  `illustrationsBySentence` and `hasPrepared`; reuse these fields and stable identities.
- Project speech generation adds `configurationFingerprint` and optional
  `singleSentenceId`; project video generation adds `configurationFingerprint` and
  the complete sentence-ID-to-asset-ID `audioAssetIds` mapping.
- Attach a `ProjectCommand` to project-backed generation so its existing freeze/replay
  and trusted registration boundaries own durable attempts and history. Do not map
  transient `requestId` to durable `operationToken` without a documented recovery contract.
- Bind MCP human review to the exact project revision and frozen generation inputs.
  Changed inputs require new review; never restore expired session approval.

Re-read the target branch before implementing this mapping because it may change.
Project reopening must retain its current explicit-regeneration/no-automatic-resume policy.

Service restart loses MCP tickets and transient-submission lookup metadata. Saved-project
recovery supplied by Task008 remains separate; this MCP request workflow cannot promise
that its generated outputs are associated with a saved project. Media files are preserved.
MCP does not synchronize its request snapshot into the frontend editor. Project tools,
cancellation, resume, scheduling and media import are not exposed.


## Connection setup

With `bash scripts/dev.sh`, the backend listens on port 8765: use
`http://127.0.0.1:8765/mcp/` for MCP and open
`http://127.0.0.1:8765/control` for human review. The frontend on port 5173 is the
sentence editor; it does not proxy the MCP or review routes. Include the trailing slash
on `/mcp/`. The returned `reviewPath` is relative to this same backend origin.

Run exactly one application worker, bind to loopback, and do not put the
endpoint behind a proxy or expose it on a LAN. Existing local media/model configuration
still applies. No cloud service or account is added.

Set `MCP_READ_TOKEN` and/or `MCP_EXECUTE_TOKEN` in the existing backend-only local
environment configuration, excluded from Git. With both empty, MCP returns 404. Use
independently generated random credentials of at least 32 characters; settings permit
32–256 printable ASCII characters (code points 33–126), excluding spaces/control
characters, and reject identical read/execute tokens.
Tokens are loaded at service start. Rotate them by changing configuration and restarting;
this also invalidates transient approvals. Never place credentials in URLs or dialogue.

Configure an MCP client supporting Streamable HTTP and custom Authorization headers:

```json
{
  "url": "http://127.0.0.1:8765/mcp/",
  "headers": {"Authorization": "Bearer <your-local-read-or-execute-token>"}
}
```

This is a client-neutral connection fragment, not a particular client's configuration
file schema. To run only the backend for MCP/review, from the repository root:

```bash
cd backend
uv sync --extra dev
uv run --env-file ../.env uvicorn shadowing_video_studio.main:app \
  --app-dir src --host 127.0.0.1 --port 8000
```

In that case change the client URL to `http://127.0.0.1:8000/mcp/` and open
`http://127.0.0.1:8000/control`. The review page does not require a frontend build.
Create the local `.env` from `.env.example` before using the command.

Execute access includes queries and preparation/submission tools. Read
access permits queries only. The local human review page is a separate browser surface,
protected by local Host/Origin validation, per-request approval nonce, no-store headers
and a restrictive content policy. MCP exposes no approval operation or nonce.

The credential authorizes app controls, not unrestricted local filesystem access. This
scheme assumes the current trusted single-user Mac; it does not isolate hostile local
processes or establish a remote multi-user security boundary. The guarantee is that MCP
provides no approval tool or nonce. A trusted local process with HTTP/browser access can
automate that separate surface; use human review according to the owner's approval policy.
Source is returned only
where needed for authorized proposals/job inspection; keep SDK debug logging disabled.

Tool schemas describe structured object results, returned in MCP `structuredContent`
and equivalent text content. Protocol/application errors are sanitized. Tool failures
set MCP `isError`; known failures include an `error` object with `code`, `detail` and
`statusCode`. Invalid schema inputs use a generic message rather than echoing dialogue.
A successfully queried request can still carry a `failed` or `unknown_outcome` state:
inspect its `error` before proceeding, rather than interpreting a successful query as
successful generation. Raw provider tracebacks are never returned.

SDK 1.30.0 is pinned and its Streamable HTTP implementation is reused rather than implementing JSON-RPC or transport ourselves.
