# Documentation & Decision Standard

## Repository is shared memory

Chat context is temporary. Repository documentation is durable context for future humans and AI agents.

Important decisions must end up in the repository.

## Where information belongs

- Product behavior → `docs/requirements/`
- Architecture → `docs/architecture/`
- Significant decisions → `docs/architecture/decisions/`
- Engineering/agent rules → `docs/standards/`
- Development commands → `docs/development/`
- Planned executable work → `tasks/`
- Runtime AI prompts → `prompts/`

Avoid duplicating the same source of truth in multiple places.

## ADR requirements

Create an ADR for decisions with durable architectural consequences.

A short ADR should contain:

- status
- context
- decision
- alternatives considered
- consequences

Do not create ADRs for trivial implementation choices.

## Documentation with code changes

Update docs in the same task when the change alters:

- setup commands
- architecture
- product behavior
- public/local API contracts
- important operating procedures
- agent standards

## Standards changes

When adding a standard:

- explain the problem it prevents
- write a concrete rule
- avoid vague language
- include an example if agents could interpret it differently

Prefer refining an existing document over adding many overlapping files.
