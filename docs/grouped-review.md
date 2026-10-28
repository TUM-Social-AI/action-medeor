# Guided review and bulk operations

Review keeps each source item independent. The overview, guided tasks, and full table consume
the same persisted request. The existing item-detail form, request details, manual-entry flow,
column renaming, and custom-column extraction are retained.

The application mounts `ReviewWorkspace` directly. Guided review includes a persistent task
timeline above the task card, with current, resolved, and deferred steps and a remaining-task
picker. Skipping every remaining task shows a
deferred-task summary instead of wrapping back to the first task. Task changes animate out
and in; successfully resolved tasks first hold a success check for 340ms, followed by the
prototype's 200ms exit and 230ms entry. Skipping has no success state. Motion respects
reduced-motion preferences. Notifications dismiss after five seconds;
the separate permanent Undo last action control remains available independently of the toast.

Overview initially previews three problems. View all expands the remaining problems inside
a height-limited, keyboard-scrollable list within the white card; Show fewer restores the
preview and resets its scroll position. The action footer remains outside that scroll area,
so Start guided review stays visible. Wheel scrolling is contained within the problem list.

The workspace uses a compact title/source header and navigation row. The table toolbar keeps
search and readiness on one line; state, type, and issue filters open from Filters. Optional
column extraction lives under Extraction details rather than in a permanent table toolbar.
Additional attributes are still used: `to_inquiry_line` passes them to matching, the search
representation includes their values, and recognized policy keys participate in compatibility
checks. Existing attributes, column renaming, and custom extraction remain available.

Request details is a separate guided step after item problems, reachable directly from the
header. Partner, region, and contact are optional, including an all-empty confirmed submission;
the system request ID remains immutable. This metadata step does not change item issue counts,
item verification, or existing matching eligibility. Drafts survive view switching and failed
saves. If saving succeeds but confirmation fails, retry only confirms the saved values.
Errors appear inside the request-details step. Confirmed details can be reopened and edited.

The shared item-detail form keeps its submit button enabled until a save is in flight. Clicking
submit or pressing Enter validates the required name, positive whole-number quantity, and
Medicine/Equipment type before making a request. Invalid fields receive red labels, borders,
and inline messages; the footer names the missing fields, and focus/scroll moves to the first
error. Errors clear as values are corrected and reset when the dialog reopens. Valid edits
continue through the existing preview/apply flow. Optional item and request-metadata fields
retain their existing rules.

The final table uses backend readiness to distinguish items needing human review from items
already checked by AI or reviewed by a person. Field and source-layout decisions say
"Human reviewed"; only explicit whole-item verification says "Human verified". Historical
rows with no recorded verifier say "Checks passed" rather than inventing provenance. Ready
rows have no Verify button. Optional additional human verification remains under the selection
toolbar's More actions menu. Confidence remains available in item details instead of taking a
separate table column. Matching stays disabled until every active item is ready.

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

An unchecked item's confirmation issue survives refresh and unrelated edits. A successful
subsequent AI check or an explicit source acceptance satisfies it. Missing quantities and
invalid quantities use separate codes; correcting an invalid source zero does not introduce
a new conflict against that zero.

## Comprehensive example request

Run explicitly from `apps/backend` against the database you want to populate:

```sh
.venv/bin/python -m app.jobs.seed_review_example
```

This adds `EXAMPLE-REVIEW-ALL-CASES`, shown in Request History as
`EXAMPLE - All review cases.xlsx`. Re-running preserves saved progress. It is opt-in sample
data; no migration, startup seeding, or AI provider call is involved. The workbook is retained
as the request's source. Its illustrative extraction results and AI findings are labelled as
simulated; re-uploading the workbook runs normal extraction and may resolve these cases.

The sample has 21 active items and one removed item, with every supported issue code and
all seven categories represented. Cases include shared column mapping, a repeated header,
missing source coverage, missing/conflicting types, missing/invalid quantities, copied-total
and pack-total conflicts, unclear/conflicting units, packaging, missing/truncated names,
unexplained low confidence, unchecked items, and unknown findings. One item combines a type
problem with a pack-total conflict. Two items are already AI checked/human verified for
comparison. Expand the source attributes for per-row "Example case" and "Try this" hints.
The source also includes a missing blanket row to add manually, and a Storage conditions
column available for custom extraction. The removed item can be restored normally.

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

The top-timeline and final-table follow-up passed 244 backend tests, all 15 frontend test
files, TypeScript checks, and the production build. The comprehensive sample is also checked
for every issue code, correct source evidence, overlapping resolutions, and seed replay without
resetting progress. Browser verification covers the top timeline at 1440px/1024px, the task
picker's keyboard dismissal, failure/retry, success/exit/entry motion, all issue categories,
manual reconciliation, restoration, review-state badges, matching readiness, and reduced motion.

The compact-layout follow-up passed 48 relevant backend tests, all 15 frontend test files,
TypeScript checks, and the production build. A browser walkthrough using an isolated copy of
the screenshot's 12-item `49-86 RfQ.pdf` request placed the table at 318px from the top at both
1440px and 1024px widths. It checked collapsed extraction/filters, empty metadata persistence,
failed-save and failed-confirmation retries, draft retention, reload, and matching eligibility.
Additional browser checks retained grouped-task confirmation/undo and manual entry, including
confirming empty metadata before adding the first item.

The item-submit validation follow-up passed all 15 frontend test files, TypeScript checks,
and the production build. Browser checks at 1440px and 1024px exercised existing and manual
items, guided and table entry points, click/Enter submission, focus/scroll, zero/fractional
quantities, valid preview/apply, cancellation, and optional metadata/unit behavior.

The overview-list follow-up passed all 15 frontend test files, TypeScript checks, and the
production build. Read-only browser checks with the comprehensive example covered preview,
expansion/collapse, reaching the final problem, contained wheel scrolling, and the guided-review
action at 1440×900, 1024×900, 1024×768, and 768×900. The action remained visible in every case.
