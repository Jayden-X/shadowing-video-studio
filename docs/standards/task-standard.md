# Task Specification Standard

## Purpose

Task files are executable contracts for human and AI implementation.

An agent should be able to pick up a ready task without needing hidden chat context.

## Task states

```text
tasks/backlog/
tasks/ready/
tasks/in-progress/
tasks/review/
tasks/done/
```

State movement should reflect reality, not aspiration.

## Definition of Ready

A task may enter `ready/` when it has:

- one clear goal
- enough context
- concrete requirements
- acceptance criteria
- explicit out-of-scope items
- validation expectations
- identified human decision gates

If a task still requires a product decision, it is not implementation-ready unless that decision is the task itself.

## Required sections

Every implementation task should contain:

### Goal
One outcome.

### Context
Why the work exists and relevant repository references.

### Requirements
Required behavior and constraints.

### Architecture constraints
Only when relevant.

### Acceptance criteria
Observable, testable completion conditions.

### Out of scope
Explicit limits.

### Validation
Exact commands/checks/manual evidence.

### Human decisions required
None, or specific unresolved decisions.

### Implementation notes
Filled during implementation with tradeoffs, changed areas, limitations, follow-ups.

## Task sizing

Prefer tasks that fit one focused PR.

Split work when independent parts can be reviewed or validated separately.

Avoid task descriptions such as:

- build the app
- improve architecture
- make it production-ready
- polish everything

## Follow-up work

Non-essential discoveries become backlog tasks rather than unplanned scope expansion.
