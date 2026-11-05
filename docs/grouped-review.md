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

Automatically selected guided tasks are saved as the current task. Individual corrections
refresh the group's remaining items without changing that selection when the server reorders
tasks by affected-item count or source order. Preview/cancel and failed saves stay on the same
task. Completing the group advances normally; skipping and explicit task/request-details
navigation take priority. The current unfinished group is retained after reload.

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

Quantity tasks show pack arithmetic only when positive pack counts, units per pack, and a
calculated total are available. Resolution buttons reflect the current selection: unavailable
source rules and pack calculations identical to the source total are omitted. For one selected
item the action names its value, such as "Use source quantity (12)"; batches keep per-row source
values. Source choices appear before the optional explicit-quantity input. Preview/apply still
uses the existing server rules and never converts quantities through a unit-label change.

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

For a separate example of the guided-review cases, run:

```sh
.venv/bin/python -m app.jobs.seed_review_example --highlights
```

This creates `EXAMPLE-REVIEW-HIGHLIGHTS` / `EXAMPLE - Review highlights.xlsx` with 22 active
items, including a simulated AI discrepancy flag, plus one removed item. It includes two
independent missing-item warnings and preserves the
original example and its decisions; re-running also preserves this sample's progress.

Guided review labels each extracted field and shows the source value or the expected decision
beside it. When no replacement is supported, that uncertainty is explicit: a unit check shows
"Expected unit: Not established". General confidence checks show the row's labelled values
on the right. The original source remains available per row.
The All items table retains its original layout.

Keeping values or confirming a source-column mapping uses one explicit action. There is no
separate inspection checkbox or acceptance dialog, and the action label stays constant while
saving. The server validates the same issue-scoped operation, and Undo remains available.
Network retries reuse the operation ID; stale revisions refresh the review before a new attempt.
Changing values still uses preview/apply. Paired actions use teal for keeping a value or
interpretation, blue for changing it, red for removal, and a neutral Skip control. Quantity
inputs remain visible; source type conflicts offer direct keep/source buttons. Pack checks
keep the extracted quantity separate from the red pack-total comparison and offer an update
to the calculation. Description tasks have individual edit/source-copy actions and no selection
checkboxes. Item names and prominent Edit item buttons open the same editor; guided edits
immediately highlight invalid required fields and focus the relevant input.

Source-column checks name their worksheet/table and affected count. The two-item example is
the separate Column check worksheet. Every supplied column has an editable role. Changes use
the stored request cells, preserve protected human values, and preview the copied-field changes.
Undo restores the source roles, copied values, provenance, and issue decisions together.

Coverage tasks resolve each missing-product warning individually. Adding a filled item or
linking an existing manual item atomically resolves that warning and displays the filled
product in its place. Other warnings stay open; one item cannot resolve multiple warnings.
Undo restores the warning and removes only the newly added item, while linking Undo keeps
the existing item. A per-warning dismissal handles false positives. Keeping a suspected repeated header
treats it as a product but exposes any missing required fields before it can become ready.
Acceptance previews used by API clients include `keptValues` so the
preserved fields and values are visible rather than only the product names.

Completing or skipping a task advances forward from the selected timeline position, including
when an earlier task remains unfinished. At the end, remaining tasks are offered explicitly.
Unit checks without a source unit offer Use Stück (default), preserving the requested quantity.
The item editor saves field changes; review acceptance stays on the guided review screen.

Source references separate literal original cells from generated findings and deterministic
validation checks. Illustrative workbooks label simulated AI and put Example case/Try this
columns in a separate annotations disclosure. Page zero is not displayed as a real page.

AI verification never changes an existing copied value, default or inference. The provider
schema exposes issues and missing-field inferences, with no correction/source-column patches.
Only empty product type and unit fields can be filled, at confidence >=90 with literal source
evidence; ambiguous packaging remains empty for human review. Existing-value discrepancies
become field-specific review issues. Summary counts distinguish fields filled from corrections.

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

`POST /api/requests/{id}/review/missing-items` accepts `operationId`, `expectedRevision`,
`issueId`, and exactly one of `item` (a complete manual item) or `itemId` (an existing manual
item). It returns the updated `review`, `operationId`, and filled `itemId`. The operation is
idempotent, revision checked, and reversible through the standard Undo endpoint.

Actions are `edit`, `quantity_rule`, `verify`, `accept`, `remove`, `restore`, and `column_mapping`. Optional
`itemChanges` maps selected item IDs to individual field patches. `accept` requires explicit
`issueIds`. Quantity rules are `requested_total` and `pack_calculation`; each uses that row's
own source value. Rule `explicit` requires `changes: {quantity: <positive integer>}` and records
the custom quantity interpretation. Setting a unit label does not convert a quantity.
`column_mapping` requires one table-scoped `issueId` in `issueIds` and `columnRoles` mapping every
supplied column key to its role; it applies to all affected items in that table. Duplicate core
roles, unknown columns, and partial-table changes are rejected. This updates retained review
evidence; an explicit future worksheet re-extraction runs the extraction mapping workflow again.

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
Merge migration `20261105_0001` joins this feature's `20261028_0001` revision with the
translation feature's `20261104_0001` revision. `alembic upgrade head` works from either
feature history or their common ancestor without rewriting applied revisions. Run the upgrade
manually against the production database before deploying the updated application. See the
[release instructions](../README.md#deploy-translation-and-guided-review-together).
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

The individual-edit navigation regression failed before the fix when a partial type correction
made quantity sort first. Component lifecycle tests now cover that refresh, next-task selection,
skipping, explicit navigation, and first-entry request-details priority. All 15 frontend test
files, TypeScript checks, and the production build passed. Browser checks with a disposable
three-item request at 1440px/1024px verified actual server reordering, preview/cancel,
failure/retry, refreshed group membership, session reload, and normal completion transitions.

Quantity-choice coverage passed all 15 frontend test files, TypeScript checks, and the build.
Component tests cover absent/incomplete/zero pack data, valid and duplicate calculations,
and mixed selections. Browser checks at 1440px/1024px reproduced the copied 9 versus source 12
case and a genuine 800 versus 1000 pack conflict, including real preview/apply, selected-row
updates, unchanged units, and retention of the unfinished guided group.
