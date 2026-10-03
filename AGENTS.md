# AGENTS.md

This file defines repository-wide instructions for Codex and other coding agents.

## Mission

Build **Shadowing Video Studio**, a local-first English shadowing video generator. Optimize for a small, reliable MVP while keeping clean extension seams for later capabilities.

## Read before coding

Before changing implementation code, read:

1. `README.md`
2. `docs/requirements/product-requirements.md`
3. `docs/architecture/overview.md`
4. `docs/development/ai-development.md`
5. The selected task under `tasks/ready/`

If a task conflicts with product requirements or architecture boundaries, stop and surface the conflict instead of silently redefining scope.

## Product constraints

MVP:
- One primary user on the current Mac.
- One video at a time.
- Paste-in text input first.
- No accounts, multi-user collaboration, cloud runtime, or batch jobs in MVP.
- These are MVP scope constraints, not permanent architecture constraints.

Text processing:
- Manual mode.
- AI-assisted mode.
- AI providers should be replaceable; initial targets are DeepSeek and Codex.
- AI output must remain reviewable/editable before media generation.

Media defaults:
- 16:9, 1920x1080.
- One sentence per page.
- 5-second default shadowing pause.
- Left-side large English subtitle, right-side visual area, bottom waveform.
- Qwen3-TTS with Aiden as default voice.
- MP4 output.

## AI operating rules

### You may decide without asking
- Local implementation details consistent with existing architecture.
- Small refactors needed to complete the task.
- Test structure.
- Naming consistent with existing conventions.
- Fixes for lint/build/test failures introduced by your change.
- Small documentation updates required by the change.

### Escalate for human decision
Do not make these choices implicitly:
- Product-scope changes.
- Architecture changes that remove an extension seam.
- Introducing a major framework or significant dependency not already approved.
- Changing persistent data/file formats incompatibly.
- Changing credential/secret strategy.
- Deleting user data or generated assets.
- Expanding MVP into cloud, multi-user, batch, or account features.

## Task discipline

Only implement work that has a task file in `tasks/ready/`, unless the human explicitly gives a direct task.

For task-based work:
1. Move/copy the task conceptually from ready to in-progress in your working branch/process.
2. Implement only the stated goal and necessary supporting changes.
3. Run every validation step in the task.
4. Record implementation notes and any deviations.
5. Do not mark acceptance criteria complete unless verified.
6. Move the task to review/done only when the workflow being used supports that safely.

## Definition of done

A task is done only when:
- Acceptance criteria are satisfied.
- Relevant automated tests pass.
- Build/lint checks pass where available.
- No secrets or generated media are committed.
- Documentation is updated when behavior or architecture changed.
- Known limitations are written down instead of hidden.

## Repository hygiene

Never commit:
- `.env` or credentials.
- API keys/tokens.
- Model weights/caches.
- Generated audio/video.
- User source media.
- Runtime databases/state.
- Logs/temp/cache directories.

Prefer small commits and focused diffs.
