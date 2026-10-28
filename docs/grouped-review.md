# Guided review and bulk operations

Review keeps each source item independent. The overview, guided tasks, and full table consume
the same persisted request. The existing item-detail form, request details, manual-entry flow,
column renaming, and custom-column extraction are retained.

The application mounts `ReviewWorkspace` directly. Guided review includes a persistent task
timeline with current, resolved, and deferred steps. Skipping every remaining task shows a
deferred-task summary instead of wrapping back to the first task. Task changes animate out
and in, respecting reduced-motion preferences. Notifications dismiss after five seconds;
the separate permanent Undo last action control remains available independently of the toast.

## Problems and grouping

The backend combines deterministic checks with categorized findings from the existing Balanced
AI review. Grouping makes no additional provider calls. Categories cover product type,
quantity validity, conflicting totals, units/packaging, descriptions, source uncertainty, and
other uncertainty. Compatible problems share a task; different suggestions and source layouts
stay separate. Unknown findings retain their explanation and require individual inspection.

An item can have several issues. Editing one field does not confirm the whole item. Required
values must be corrected; ambiguous source interpretations can be explicitly accepted. Human
decisions are tied to relevant values and source evidence and reopen when those dependencies
change. The application-approved Stück default remains informational.

Column-mapping uncertainty is one table-scoped issue, identified by worksheet, source headers,
and mapped column roles. Review shows the mapped columns and five representative copied rows;
one confirmation covers every affected row without changing its values. Generic low-confidence
flags caused by the same mapping uncertainty are not separate per-item tasks. Genuine field
exceptions remain visible. Repeated header rows are excluded during extraction; existing saved
header rows receive a single reversible removal task rather than missing-product-field tasks.

## API

`GET /api/requests/{id}/review` retains the existing response and adds `reviewRevision`,
`issues`, `tasks`, `reviewCounts`, `removedItems`, and `canStartMatching`. Item responses include
`fieldReviews` and `readyForMatching`. Open issue explanations also appear in `reviewReasons`.
Active-item, affected-item, open-issue, and removed-item counts have separate meanings.
`lastUndoOperationId` identifies the latest compatible undo operation after reload; it is null
when no action can safely be undone. Table-scoped issues have `itemId: null`, affected `itemIds`,
`columns`, and `sampleRows`. Accept their explicit issue IDs once with an empty `itemIds` list.

`POST /api/requests/{id}/review/operations/preview` and
`POST /api/requests/{id}/review/operations` accept the same payload:

```json
{
  "operationId": "a-client-generated-uuid",
  "expectedRevision": 3,
  "action": "edit",
  "itemIds": [12, 13],
  "changes": {"domain": "equipment"}
}
```

Actions are `edit`, `quantity_rule`, `verify`, `accept`, `remove`, and `restore`. Optional
`itemChanges` maps selected item IDs to individual field patches. `accept` requires explicit
`issueIds`. Quantity rules are `requested_total` and `pack_calculation`; each uses that row's
own source value. Setting a unit label does not convert a quantity.

Preview returns before/after changes, `eligibleItemIds`, and `blockers`. It does not persist
changes. Mixed verification selections must be resubmitted with the explicitly chosen eligible
subset. Apply revalidates under the request lock, saves one atomic transaction, and returns
`{review, operationId}`. Retry the identical payload and operation ID after a network failure.
Reusing an operation ID for different input is rejected.

Stale revisions return 409. Invalid operations return 422 without partial changes. All review
mutations are locked once matching starts. Individual edit, verify, and remove routes share
the operation service.

## Removal and undo

Removed items keep their IDs, evidence, provenance, and history. They are excluded from AI
review, matching, matching completion, history counts, summaries, and exports. Source row counts
remain separate from active-item counts. Worksheet reparsing uses stable source keys and retains
human edits and removal decisions when the same source rows return.

`POST /api/requests/{id}/review/operations/{operationId}/undo` accepts a new `operationId` and
the current `expectedRevision`. Undo compares the affected items and source evidence against
the operation's saved after-state. Unrelated changes are allowed; conflicting changes return
409. Undo restores values, provenance, field protection, issue decisions, and removal state.
Undo is recorded and cannot itself be undone. Removed items can also be restored explicitly.

## Migration and verification

Apply `alembic upgrade head` before starting the updated application. Migration
`20261028_0001` adds review state and operation history without changing old extracted values
or matching results. Existing requests are read using available evidence; no historical AI
backfill is triggered.

The existing `20261012_0002` migration creates `import_progress` during a normal upgrade.
No additional repair migration is required by this feature. Databases previously migrated
on branches with different migration ancestry may need a one-time schema reconciliation;
`alembic upgrade head` does not recreate missing tables from already-recorded ancestors.
The application database's schema and recorded revision must agree before normal upgrades.

Automated coverage includes the 48-item/17-issue/six-task fixture, overlapping issues, source
rules, atomic failure, idempotency, undo conflicts, removal, restoration, and existing request
and matching regressions. Browser verification uses the real API and checks 1440px/1024px
layouts, the original detail modal, failed-save retry, undo, removal/restoration, and reduced
motion. Prototype fixture data and simulated failures are not included in production code.

The streamlined-workspace verification passed 239 backend tests (including PostgreSQL
integration tests), all 15 frontend test files, TypeScript checks, and the production build.
Browser checks on an isolated copy of `DCE_P00994.xlsx` covered the four-task timeline,
skip-all persistence, one shared column decision, repeated-header removal, five-second toast
expiry, Undo after reload, task animations, reduced motion, and final matching eligibility.
The original uploaded request was not edited or automatically accepted during these checks.
