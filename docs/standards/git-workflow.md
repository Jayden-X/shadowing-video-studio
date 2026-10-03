# Git & Delivery Workflow

## Objective

Keep `main` readable, reviewable, and easy for both humans and AI agents to reason about.

## Branches

Do not implement non-trivial work directly on `main`.

Suggested prefixes:

- `feat/`
- `fix/`
- `chore/`
- `docs/`
- `refactor/`
- `spike/`

Prefer names tied to one task, for example:

`feat/002-manual-sentence-editor`

## One task, one delivery unit

The default unit is:

**one task → one focused branch → one PR → one squash commit on main**

A task may touch many files.

Do **not** create one permanent commit per file.

## Intermediate commits

Agents/tools may create temporary intermediate commits on a working branch when technically necessary.

Before integration:

- the PR must be focused
- the final merge to `main` must use squash
- temporary commit noise must not become main history

## Commit messages

Use an imperative Conventional-Commit-style subject:

- `feat: add manual sentence editor`
- `fix: preserve sentence identity during split`
- `docs: define agent delivery standards`
- `chore: bootstrap local application`

The final squash commit should describe the task outcome, not individual file operations.

## Main history

`main` should contain meaningful product/engineering milestones.

Avoid:

- `add file`
- `update readme`
- repeated identical commits
- formatting-only commits mixed with feature work
- checkpoint/WIP commits

## Pull requests

A PR should contain:

- one clear goal
- task reference
- acceptance criteria
- validation performed
- known limitations
- architecture/product decisions, if any

## Force push

Allowed only when intentionally cleaning a private working branch or early repository history and when no other contributor is relying on that history.

Do not force-push shared `main` casually.

## Merge policy

Preferred: **Squash and merge**.

Merge/rebase strategies require a specific reason.

## Generated and secret files

Never commit:

- secrets
- local `.env`
- model weights
- caches
- generated audio/video
- user source media
- local runtime databases unless explicitly designed as fixtures
