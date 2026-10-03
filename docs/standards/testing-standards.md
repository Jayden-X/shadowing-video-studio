# Testing Standards

## Principle

Vibe coding does not reduce verification requirements.

An agent must prove behavior rather than rely on code plausibility.

## Test selection

Use the cheapest reliable test for the risk:

- pure unit tests for deterministic domain logic
- contract/adapter tests for provider boundaries
- integration tests for filesystem/process/API interactions
- UI tests for important user interactions
- manual smoke tests for model/media behavior that is impractical in CI

## Required behavior

When changing behavior:

- add or update tests
- include the failure/regression case when fixing a bug
- test unhappy paths when failure has meaningful consequences
- keep tests deterministic

## External services

Normal tests must not require:

- paid AI API calls
- live DeepSeek/Codex availability
- large Qwen model downloads
- network access unless explicitly classified as integration tests

Use fixtures/fakes at provider boundaries.

## Media/model tests

Do not commit large generated media.

Prefer:

- tiny synthetic inputs
- command/timeline tests
- metadata assertions
- optional local smoke scripts

Real Qwen3-TTS and FFmpeg validation may be separate explicit integration/spike tasks.

## Test quality

Avoid tests that:

- only reproduce implementation details
- assert meaningless snapshots
- depend on test execution order
- use arbitrary sleeps when a deterministic signal exists
- silently skip important checks

## Validation before completion

At minimum run the checks relevant to changed areas.

Current repository full check:

```bash
bash scripts/check.sh
```

If a required check cannot run, report why and do not claim it passed.

## CI policy

CI is a merge gate, not a substitute for local reasoning.

Never weaken CI simply because a task fails it.
