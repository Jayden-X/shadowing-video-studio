# 014 — Delete local projects with explicit resource choices

## Priority and status

- Priority: **P3**.
- Status: **backlog — deletion modes confirmed; lifecycle design required**.

## Goal

Let the owner remove unwanted local projects and choose which associated files to keep.

## Context

Task008 preserves project/history metadata and immutable local media without deletion or
automatic pruning. On 2026-10-04 the owner requested three deletion choices. They belong
to this follow-up rather than expanding Task008's accepted persistence scope.

## Requirements

Offer exactly these owner-confirmed choices:

1. **Delete project only** — retain intermediate resources and final outputs.
2. **Delete project and intermediate resources** — retain final outputs.
3. **Delete project and all resources** — include final outputs in the deletion scope.

Before deletion, show which project and resource categories will be affected, the selected
mode, file counts/size and what will be retained. Request explicit confirmation. Never
interpret "all resources" as every file in the shared workspace or visual library.

Only delete trusted, application-owned resources attributable to this project. Protect
resources still referenced by another project, generation attempt or historical output;
report retained/shared resources in the result. Do not infer ownership from filenames.
Block destructive cleanup of active work. Preserve unrelated projects and media.

Define incomplete/crashed deletion recovery and idempotency before implementation. Report
partial failure accurately; avoid orphaning metadata through a false success response.
Resources retained by a deletion mode must remain locatable through a defined mechanism,
even when their project is no longer listed.

## Architecture constraints

Use Task008's project commands and authoritative storage/registration boundaries. Deletion
must not expose arbitrary filesystem paths or bypass local request guards. Any schema or
resource-lifecycle change requires an accepted ADR/owner decision first.

## Acceptance criteria

- [ ] UI exposes the three choices with a clear scope preview and confirmation.
- [ ] Project-only deletion retains all associated resource bytes.
- [ ] Intermediate cleanup retains final MP4s and defines how to find them afterward.
- [ ] All-resource cleanup deletes only eligible resources associated with the project.
- [ ] Shared resources and unrelated project/history files remain intact.
- [ ] Active-work rejection, cancellation, partial failure and interrupted cleanup give
  accurate feedback without silently losing unrelated data.
- [ ] Critical reference/ownership and recovery checks pass; validate the main workflow
  on the authorized Mac with synthetic projects before using real user projects.

## Out of scope

Automatic/background pruning, cloud sync, bulk deletion, arbitrary folder deletion,
and deletion of shared library resources without a separate explicit policy.

## Human decisions required

The three modes above are confirmed. Before implementation, present the lifecycle plan:

- Define intermediate files: generated WAVs, frozen render inputs and owned temporary
  render files are candidate categories; decide whether unshared uploaded background/
  illustration originals participate or stay in the reusable global library.
- Decide how retained files remain discoverable after project deletion and how trusted
  media registrations/history references are retained or removed.
- Select metadata migration, reference accounting and partial-deletion recovery semantics.

No destructive deletion has been authorized against any particular existing project by
the feature request. Implementing a confirmed deletion UI does not authorize agents to
clean user projects automatically.

## Validation

Keep existing checks. Use a small representative set of critical ownership/shared-resource,
mode-selection and failure-recovery scenarios. Delegate frontend/unit-test work to GPT-6
Luna with max reasoning, following the owner's current focused-testing policy.

## Implementation notes

Requirement recorded on 2026-10-04. No deletion code or user-data cleanup has run.
