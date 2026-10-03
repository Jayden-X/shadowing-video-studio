# 003 — AI-assisted text processing

## Goal

Generate a reviewable sentence proposal using a selected AI provider, then let the user explicitly apply and manually correct it.

## Context

Task 002 provides the canonical React-independent sentence document and manual editor. The owner authorized continuing the task queue and selected reuse of the locally logged-in Codex CLI on 2026-10-03. DeepSeek uses the existing environment-based API-key strategy.

Read product requirements, architecture overview, ADR 0001, future task/control seams, and relevant code/testing/security standards.

## Requirements

- Offer Manual and AI-assisted preparation modes; AI calls require explicit provider selection and a Prepare action.
- Define a provider-neutral `TextProcessingProvider` boundary on the backend with DeepSeek and local Codex CLI adapters.
- Expose provider configuration/availability and prepare APIs; credentials stay on the backend.
- Preserve the exact submitted source separately from proposed sentences and the existing edited document.
- Validate provider results locally: exact structured object, non-empty bounded list of non-blank strings; reject truncated, malformed, oversized, or failed results.
- Show the proposal for review and require an Apply action before replacing the canonical document. Discard/failure preserves existing edits; applying a replacement requires clear confirmation.
- Assign canonical IDs in the application/domain layer, never from provider-generated IDs. Reuse the same six manual tools after acceptance.
- Send Codex source over stdin in an isolated temporary working directory, with user/repository configuration and unnecessary tools disabled. Reuse its existing login; never read/copy authentication secrets, run source through a shell, or expose raw provider output/errors to the UI.
- Use bounded input/output and timeouts; do not automatically retry provider failures. Normal tests use fakes/fixtures and require no credentials or model downloads.

## Architecture constraints

- Provider responses are proposal DTOs, independent of canonical sentence models and future media state.
- UI/API/application validation and adapters remain separate. Add no significant dependency or persistent format.
- Future CLI/MCP task control can reuse application functions; human review remains explicit.

## Acceptance criteria

- [x] User can select AI-assisted mode and a configured provider.
- [x] Both provider adapters are replaceable behind the application boundary.
- [x] Invalid/failed provider output is rejected without losing source or edits.
- [x] Proposal must be reviewed/applied before entering the canonical document.
- [x] Accepted output supports all manual corrections with stable application IDs.
- [x] Contract, failure-path, domain and UI tests pass without live AI calls.
- [x] Full repository checks and PR CI pass.
- [x] Setup, prompt, task and configuration documentation are synchronized.

## Out of scope

TTS/video generation, automatic media generation, scheduling, MCP server implementation, batch processing, project persistence, and choosing a new credential store.

## Validation

- Backend provider/application/API contract and failure-path tests using fixtures/fakes.
- Frontend domain/API/UI tests for proposal review/apply/discard, preserved source/edits, and request lifecycle.
- `bash scripts/check.sh` and final PR CI.
- Browser smoke with configured availability and offline/failure behavior; record whether a live synthetic Codex/DeepSeek call was exercised.

## Human decisions required

None for implementation: the owner selected the locally logged-in Codex CLI. Live provider availability may remain an environment-dependent limitation and must be recorded.

## Implementation notes

- Implemented provider-neutral service, strict UTF-16/Unicode proposal validation, configuration/prepare APIs, fixed-endpoint DeepSeek adapter and isolated Codex subprocess adapter. Prompt/schema v1 are package resources; the repository prompt note points to the single runtime source of truth.
- The UI defaults to manual mode. Provider/Prepare actions are explicit; proposal review, Apply and replacement confirmation protect the canonical document. Discard/failure/stop/timeout preserves source and edits; request sequence checks ignore late results. Applying assigns project-owned IDs and reuses all six manual tools.
- Codex runs source on stdin without a shell, isolates working/configuration context, disables capabilities/MCP, verifies readiness and rejects tool events. Process output/deadlines are bounded. Windows uses suspended startup and kill-on-close Job ownership before source delivery; POSIX uses a dedicated process group. Ownership failure does not fall back to weaker execution.
- Backend validation on Windows: Ruff lint/format passed, **95 pytest cases passed**, including real stdin and parent-exit/child-pipe cleanup regressions. Windows-only Job tests are classified explicitly; Linux CI will skip that platform-specific regression.
- Frontend: **91 tests passed** (20 domain, 53 API, 18 UI), typecheck and production build passed. Default Vitest workers passed outside the Windows filesystem sandbox; that sandbox initially rejected temporary transform-cache access. No CI/test configuration was weakened.
- Final repository `bash scripts/check.sh` passed with **95 backend and 91 frontend cases**, lint/format/typecheck/build all passed. Bash syntax check passed for `scripts/dev.sh`. PR #5 CI run `37145369754` passed all three jobs; final task-state-only revision is rechecked before squash integration.
- Built the backend wheel and verified both prompt assets. Installed it into a separate environment and read both resources outside the repository with isolated Python; no editable checkout dependency was required.
- Browser smoke used a clearly synthetic provider fixture: explicit selection, unapplied proposal, replacement Cancel/Apply, same editor after acceptance, failure preservation, pending lock/Stop waiting, and Discard all passed. Offline manual editing also passed. The fixture was stopped and replaced with the actual local backend after validation.
- No live inference was run: DeepSeek credentials were not configured; local Codex CLI 0.160.0 kept `unified_exec` enabled despite all tested disable overrides. The adapter reported unavailable and retained its safety gate. This environment limitation is recorded in setup docs; fixtures/contract tests are not claimed as model-quality proof.
- Independent OCR Delegation Mode review found a process cleanup issue; it was fixed with real process regressions and re-reviewed. Final coverage: 16 reviewable files plus 16 tests/docs/config entries, **32/32 reviewed**, none skipped and no unresolved Blocker/Required findings. Delivery is one Task 003 PR and one final squash commit.
- Work remains browser-session-only; sentence correctness requires human review. No TTS/video, persistence, scheduler or MCP runtime was added.
