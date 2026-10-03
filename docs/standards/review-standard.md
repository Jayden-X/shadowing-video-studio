# Review & Quality Gates

## Review objective

Review should verify behavior, boundaries, maintainability, and evidence—not formatting preferences already enforced by tools.

## Current MVP review scope

For the current MVP, focus OCR and code review on backend production logic and critical
code: workflow transitions, provider/process boundaries, media bindings, data safety and
failure recovery. Frontend code and frontend/backend unit-test files are excluded from
OCR and code review under the owner's selected scope; existing test/build/CI checks remain.
Use the selected GPT-6 Luna/max reviewer. Report coverage for the selected critical scope,
and identify excluded areas without expanding the review to cover low-impact details.

## Required review questions

### Product
- Does this implement the requested behavior?
- Did scope expand?
- Are acceptance criteria satisfied?

### Architecture
- Are vendor details kept behind boundaries?
- Is the canonical domain model still project-owned?
- Was a major architectural choice made without an ADR/human decision?
- Is new complexity justified?

### Code
- Is the implementation understandable?
- Are names domain-specific?
- Is duplicated logic introduced?
- Are error paths safe?
- Are dependencies justified?

### Tests
- Is changed behavior tested?
- Are regression cases covered?
- Are tests deterministic?
- Were relevant checks actually executed?

### Security/data
- Are credentials absent?
- Could private user data be logged or committed?
- Are generated media/model files excluded?

### Delivery
- Is the PR task-focused?
- Are docs/task notes synchronized?
- Will main receive one meaningful squash commit?

## Severity model

Review findings may be classified as:

- **Blocker** — correctness, security, data loss, broken architecture contract
- **Required** — acceptance criterion, maintainability, missing validation
- **Follow-up** — useful but outside current task
- **Nit** — non-blocking readability preference

Agents must not ignore Blocker/Required findings.

## Completion gate

Do not mark a task done until:

- acceptance criteria are checked
- required validation passes
- blocker/required review findings are resolved
- documentation is updated where necessary
