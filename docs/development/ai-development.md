# AI Development Workflow

## Goal

Make routine product work executable by Codex/AI agents with minimal repeated explanation while preserving human control over product and architecture decisions.

## Workflow

1. **Read context**
   - `AGENTS.md`
   - relevant requirements
   - relevant architecture docs
   - selected task

2. **Understand before editing**
   - inspect existing implementation and tests
   - identify the smallest coherent change
   - do not invent missing product decisions

3. **Implement**
   - keep changes task-scoped
   - preserve extension seams
   - add/update tests with behavior changes

4. **Validate**
   - run the task's explicit validation
   - run repository lint/test/build commands once they exist
   - inspect failures rather than bypassing checks

5. **Report**
   - what changed
   - what was verified
   - any remaining limitation
   - any human decision still required

## Good AI tasks

A good task:
- has one clear goal
- includes acceptance criteria
- names out-of-scope behavior
- includes validation
- can usually be reviewed as one focused PR

Prefer 1–4 hour human-sized units over broad epics.

## Bad AI tasks

Avoid:
- "build the whole app"
- "make it production ready"
- "improve architecture"
- open-ended refactors without acceptance criteria
- combining unrelated UI/backend/media changes

## Human decision gates

AI should stop and ask for a decision when a task requires:
- choosing the primary application framework
- replacing a major framework
- changing MVP scope
- changing persistence compatibility
- introducing cloud/account/multi-user behavior
- committing to a new paid/external service as a required dependency

## Validation philosophy

Vibe coding still requires verification.

Every implemented feature should have the cheapest reliable validation appropriate to it:
- unit tests for deterministic logic
- integration tests for adapters
- smoke tests for FFmpeg/TTS integration
- UI tests for critical user flows
- fixture/sample-based regression tests for rendering where useful

Do not accept "looks plausible" as validation.
