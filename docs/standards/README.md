# Engineering & Agent Standards

This directory is the shared operating standard for every human and AI agent working on Shadowing Video Studio.

The goal is not to create bureaucracy. The goal is to make independent agents produce compatible code, decisions, tests, commits, and documentation without repeatedly re-explaining the project.

## Authority order

When instructions conflict, use this precedence:

1. Explicit instruction from the human owner for the current task.
2. Product requirements under `docs/requirements/`.
3. Accepted ADRs under `docs/architecture/decisions/`.
4. Standards in this directory.
5. The selected task specification under `tasks/`.
6. Existing implementation patterns.

A lower-level document must not silently override a higher-level one.

If a real conflict remains, stop and surface it.

## Standards index

- [Agent operating model](agent-operating-model.md)
- [Code standards](code-standards.md)
- [Architecture guardrails](architecture-guardrails.md)
- [Testing standards](testing-standards.md)
- [Git and delivery workflow](git-workflow.md)
- [Task specification standard](task-standard.md)
- [Review and quality gates](review-standard.md)
- [Documentation and decision records](documentation-standard.md)
- [Security and local data](security-standard.md)

## How to evolve these standards

These documents are intentionally expected to evolve.

When a recurring problem appears:

1. Fix the immediate problem.
2. Ask whether the problem represents a reusable rule.
3. If yes, update the smallest relevant standards document.
4. Add an example when ambiguity is likely.
5. Avoid duplicating the same rule across many files.

Do not add a rule for a one-off preference unless it is likely to help future work.

## Scope

These standards apply repository-wide unless a nested `AGENTS.md` or an accepted ADR introduces a more specific rule for a subdirectory.

Nested rules may specialize behavior but must not contradict product requirements or accepted architecture decisions.
