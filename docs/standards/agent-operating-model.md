# Agent Operating Model

## Objective

AI agents should be able to independently complete well-scoped work while preserving human control over product direction and irreversible decisions.

## Required reading order

Before implementation, an agent must read:

1. root `AGENTS.md`
2. `docs/standards/README.md`
3. relevant product requirements
4. relevant ADRs / architecture docs
5. the selected task
6. nearby implementation and tests

Do not start by writing code from the task title alone.

## Working model

For non-trivial work:

1. Inspect the current repository state.
2. Restate the implementation boundary internally.
3. Identify affected modules and tests.
4. Make the smallest coherent change.
5. Validate it.
6. Update documentation/task notes when required.
7. Report verified results and unresolved risks.

## Agent autonomy

Agents may decide without human approval:

- local implementation details inside approved architecture
- names consistent with repository conventions
- small refactors necessary for the task
- tests and fixtures
- error handling consistent with existing behavior
- minor documentation synchronization
- fixes to lint/type/test/build failures caused by the task

## Human decision gates

Stop and request a human decision before:

- changing user-visible product scope
- selecting or replacing a major framework
- introducing a significant runtime/service dependency
- weakening security or secret handling
- introducing cloud/account/multi-user behavior
- making incompatible persistent-format changes
- deleting user data or generated artifacts
- removing an accepted extension seam
- making a materially different UX choice where the task is ambiguous

## No silent scope expansion

Do not add adjacent features because they seem useful.

Allowed supporting work is limited to what is necessary to safely implement, test, or maintain the requested task.

Create follow-up tasks for useful but non-essential work.

## Multi-agent coordination

The owner's current model choice is **GPT-6 Luna with max reasoning** for frontend
implementation and code-review subagents. Preserve existing work when handing off; record
the reviewed scope and actual validation. If that model is unavailable, surface the
limitation rather than silently substituting another model for these tasks.

Agents should optimize for handoffability:

- keep changes localized
- avoid unrelated refactors
- leave the repository buildable
- document non-obvious decisions
- record known limitations
- do not leave hidden local-only setup steps
- do not assume another agent remembers chat history

Repository files are the durable shared context.

## Failure behavior

When blocked:

- do not fake completion
- do not disable tests to obtain green CI
- do not replace a required integration with a mock and claim it is complete
- state the exact failing condition
- preserve successful work
- create or update a task with the remaining work when appropriate

## Output expectation

At completion, report:

- what changed
- what validation actually ran
- what did not run
- known limitations
- any human decision still required
