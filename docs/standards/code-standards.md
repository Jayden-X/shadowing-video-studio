# Code Standards

## General principles

Optimize for:

1. correctness
2. readability
3. testability
4. clear boundaries
5. maintainability
6. performance only where it matters

Prefer boring, explicit code over clever abstractions.

## Change discipline

- Keep diffs task-scoped.
- Do not perform unrelated cleanup in the same task.
- Prefer small pure functions for deterministic logic.
- Keep I/O at boundaries.
- Avoid global mutable state.
- Do not duplicate domain rules across UI and backend without a deliberate reason.

## Naming

Names should communicate domain intent.

Prefer:

- `SentenceItem`
- `TextProcessingProvider`
- `generateSpeech()`
- `renderVideo()`

Avoid:

- `Manager`
- `Helper`
- `Util`
- `Data`
- `handleThing()`

unless the broader name is genuinely accurate.

## Python

- Python target: 3.12.
- Use type annotations on public functions and important internal boundaries.
- Prefer dataclasses/Pydantic models for structured data where appropriate.
- Keep provider/vendor code behind adapters.
- Raise meaningful domain/application errors instead of leaking arbitrary SDK exceptions upward.
- Use `pathlib` for filesystem paths.
- Avoid synchronous blocking work inside async request paths unless deliberately isolated.
- Ruff is the source of truth for lint/format rules.

## TypeScript / React

- TypeScript strict mode stays enabled.
- Avoid `any`; narrow unknown external data explicitly.
- Domain operations should not live inside React components when they can be pure functions.
- Components should primarily coordinate state and rendering.
- Keep provider/API DTOs separate from domain models when formats differ.
- Do not use component state as the only representation of important domain data.
- Prefer accessible native controls and semantic HTML.
- Avoid adding state-management libraries until React-local state becomes demonstrably insufficient.

## Error handling

Errors should be:

- explicit
- actionable
- logged at the correct boundary
- safe for user display where applicable

Never swallow an exception only to continue with corrupted state.

## Configuration

- No secrets in source.
- Centralize configuration.
- Do not scatter environment variable reads throughout business logic.
- Defaults that affect product behavior should be named and documented.

## Dependencies

Before adding a dependency, confirm that it:

- solves a real task requirement
- is maintained
- does not duplicate an existing dependency
- has acceptable runtime/packaging impact
- improves the code enough to justify its cost

Major dependencies require human approval.

## Comments

Comments should explain **why**, constraints, or surprising behavior.

Do not write comments that merely translate the code into English.
