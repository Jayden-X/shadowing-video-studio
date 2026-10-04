# Testing Standards

## Principle

Vibe coding does not reduce verification requirements.

An agent must prove behavior rather than rely on code plausibility.

## MVP test scope

The owner selected a focused test approach for the current MVP:

- Keep existing tests and CI checks.
- Add tests for core workflow transitions, important domain rules, failure recovery,
  and data/filesystem/process safety where a regression would matter.
- Prefer a small representative set of scenarios over a separate test for every helper,
  UI string, style, setter, or implementation detail.
- Defer low-impact edge cases and cosmetic assertions. Record a material unverified risk
  explicitly rather than expanding the suite to cover every possible variation.
- Focus new unit tests on backend logic and critical code; frontend and other low-impact
  logic do not require detailed new unit coverage. Delegate frontend and unit-test work to
  GPT-6 Luna with max reasoning, as recorded in the agent operating model.
- Use actual model/media integration evidence for the main path when available; it
  complements the focused deterministic checks and must not be reported as unit-test proof.

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
