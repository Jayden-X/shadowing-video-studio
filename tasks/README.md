# Task Workflow

This directory is the lightweight execution queue for humans and AI coding agents.

## States

- `backlog/` — valid ideas/work, not ready for implementation.
- `ready/` — sufficiently specified and approved for implementation.
- `in-progress/` — actively being implemented.
- `review/` — implementation complete, awaiting review/acceptance.
- `done/` — accepted and completed.

## Task format

Each task should contain:

- Goal
- Context
- Requirements
- Acceptance criteria
- Out of scope
- Validation
- Human decisions required (if any)
- Implementation notes

Tasks should be small enough for one focused PR/change set.

Do not use task state folders as a substitute for GitHub Issues if the project later needs richer collaboration; this local format exists primarily to make AI execution context explicit.
