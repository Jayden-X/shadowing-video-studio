# AGENTS.md

Repository-wide operating instructions for Codex and every other coding agent.

## Mission

Build **Shadowing Video Studio**, a reliable local-first English shadowing video generator.

Favor a small MVP, explicit domain boundaries, reproducible validation, and repository-based shared context.

## Instruction authority

Follow the precedence defined in [Engineering & Agent Standards](docs/standards/README.md).

Never silently resolve a conflict by changing product scope or architecture.

## Required reading before implementation

1. `README.md`
2. `docs/standards/README.md`
3. Relevant files under `docs/requirements/`
4. Relevant architecture docs and ADRs
5. The selected task under `tasks/ready/`
6. Nearby implementation and tests

For non-trivial changes, also read the specific standards relevant to the work.

## Core product constraints

Current MVP:

- local-first on the current Mac
- one primary user
- one video at a time
- paste-in dialogue first
- manual and AI-assisted sentence preparation
- DeepSeek/Codex as initial AI-provider targets
- Qwen3-TTS with Aiden as the current default voice
- FFmpeg-based MP4 generation
- no accounts, cloud runtime, multi-user collaboration, or batch jobs in MVP

These are product-scope constraints, not permanent architecture constraints.

The full source of truth is `docs/requirements/product-requirements.md`.

## Agent operating rules

Follow:

- `docs/standards/agent-operating-model.md`
- `docs/standards/code-standards.md`
- `docs/standards/architecture-guardrails.md`
- `docs/standards/testing-standards.md`
- `docs/standards/git-workflow.md`
- `docs/standards/task-standard.md`
- `docs/standards/review-standard.md`
- `docs/standards/documentation-standard.md`
- `docs/standards/security-standard.md`

## Delivery rule

Default delivery unit:

**one task → one branch → one PR → one squash commit on `main`**

Tools may create temporary intermediate commits on a work branch, but commit-per-file noise must not enter `main`.

## Human decision gates

Stop and request a decision before making:

- user-visible product-scope changes
- major framework/runtime dependency choices
- incompatible persistence changes
- security/credential-policy changes
- cloud/account/multi-user expansion
- destructive user-data behavior
- major architecture boundary changes

## Definition of done

Do not claim completion until:

- acceptance criteria are satisfied
- relevant tests/checks actually ran and passed
- blocker/required review findings are resolved
- no secrets/generated media/model weights are committed
- affected documentation/task notes are synchronized
- limitations and unverified items are stated explicitly

## Standards are living documentation

When a recurring engineering or agent-coordination problem is discovered, fix the immediate issue and update the smallest relevant file under `docs/standards/`.

Do not rely on chat history as permanent project policy.
