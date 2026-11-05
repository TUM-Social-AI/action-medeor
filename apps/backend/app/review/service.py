"""One preview/apply path for individual and bulk review decisions."""

import copy
import datetime as dt
import logging
import time
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RequestReviewIssueRow, RequestReviewOperationRow
from app.review.column_mapping import apply_mapping
from app.review.contracts import ReviewOperation, UndoOperation
from app.review.engine import EDIT_FIELDS, digest, parsed_item, source_facts, synchronize

logger = logging.getLogger(__name__)
PUBLIC = {"itemNumber": "item_number", "shelfLife": "shelf_life"}
SNAPSHOT_FIELDS = (
    *EDIT_FIELDS,
    "attributes",
    "status",
    "confidence",
    "verification_source",
    "protected_fields",
    "inferred_fields",
    "field_reviews",
    "review_findings",
    "review_reasons",
    "removed_at",
    "removed_by",
    "source_active",
)


class State(SimpleNamespace):
    @property
    def active_items(self):
        return [i for i in self.items if i.removed_at is None and i.source_active]


def clone(request):
    state = State(
        **{
            k: copy.deepcopy(getattr(request, k))
            for k in (
                "request_id",
                "ai_review",
                "selected_sheet",
                "selected_sheets",
                "parser_warnings",
            )
        }
    )
    state.items = [
        SimpleNamespace(
            **{
                **{k: copy.deepcopy(getattr(i, k)) for k in SNAPSHOT_FIELDS},
                "id": i.id,
                "manual": i.manual,
                "source_reference": i.source_reference,
            }
        )
        for i in request.items
    ]
    state.review_issues = [
        SimpleNamespace(
            id=i.id,
            item_id=i.item_id,
            detail=copy.deepcopy(i.detail),
            resolution=copy.deepcopy(i.resolution),
        )
        for i in request.review_issues
    ]
    return state


def check_revision(request, revision):
    if request.workflow_status != "review":
        raise HTTPException(409, "Review is locked after matching starts")
    if request.review_revision != revision:
        raise HTTPException(409, "Request changed. Refresh and preview this operation again.")


def validate_changes(changes):
    normalized = {PUBLIC.get(k, k): v for k, v in changes.items()}
    if set(normalized) - set(EDIT_FIELDS):
        raise HTTPException(422, "Unsupported editable field")
    for field, value in normalized.items():
        if field == "quantity":
            valid = type(value) is int and value > 0
        elif field == "domain":
            valid = value in {"medicine", "equipment"}
        elif field == "priority":
            valid = value in {"critical", "high", "medium", "low"}
        else:
            valid = isinstance(value, str)
            if field in {"name", "unit"}:
                valid = valid and bool(value.strip()) and any(c.isalpha() for c in value)
        if not valid:
            raise HTTPException(422, f"Invalid {field}: required fields cannot be cleared")
    return normalized


def snapshot(request, ids, issue_ids=(), *, source_data=False):
    selected = set(ids)
    result = {
        "items": {
            str(i.id): {
                k: (
                    getattr(i, k).isoformat()
                    if k == "removed_at" and getattr(i, k)
                    else copy.deepcopy(getattr(i, k))
                )
                for k in SNAPSHOT_FIELDS
            }
            for i in request.items
            if i.id in selected
        },
        "issues": {
            i.id: {
                "detail": copy.deepcopy(i.detail),
                "resolution": copy.deepcopy(i.resolution),
                "itemId": i.item_id,
            }
            for i in request.review_issues
            if i.item_id in selected or i.id in issue_ids
        },
        "sources": {
            str(i): digest((request.ai_review or {}).get("sources", {}).get(str(i), {}))
            for i in ids
        },
    }
    if source_data:
        result["sourceData"] = {str(i): copy.deepcopy((request.ai_review or {}).get("sources", {}).get(str(i), {})) for i in ids}
    return result


def accept(state, issues, ids, actor):
    rows = {i.id: i for i in state.review_issues}
    for issue in issues:
        if issue["id"] not in ids:
            continue
        if not issue["canAccept"]:
            raise HTTPException(422, "Missing or invalid required values must be corrected")
        rows[issue["id"]].resolution = {
            "fingerprint": issue["fingerprint"],
            "actor": actor,
            "at": dt.datetime.now(dt.UTC).isoformat(),
        }


def evaluate(request, operation: ReviewOperation, actor="local"):
    check_revision(request, operation.expectedRevision)
    if len(set(operation.itemIds)) != len(operation.itemIds) or len(set(operation.issueIds)) != len(
        operation.issueIds
    ):
        raise HTTPException(422, "Select each item and issue only once")
    state = clone(request)
    initial = synchronize(state)
    by_id = {i.id: i for i in state.items}
    issue_by_id = {i["id"]: i for i in initial["issues"] if i["state"] == "open"}
    if any(i not in issue_by_id for i in operation.issueIds):
        raise HTTPException(409, "Selected issues changed. Refresh the review.")
    ids = set(operation.itemIds)
    mapping_issue = None
    if operation.action == "column_mapping":
        if len(operation.issueIds) != 1:
            raise HTTPException(422, "Choose one source table to remap")
        mapping_issue = issue_by_id[operation.issueIds[0]]
        if mapping_issue.get("scope") != "table" or mapping_issue["code"] != "mapping_uncertain":
            raise HTTPException(422, "Column changes require a source-column issue")
        if ids and ids != set(mapping_issue["itemIds"]):
            raise HTTPException(422, "Column changes apply to every affected item in this source table")
        ids = set(mapping_issue["itemIds"])
    if operation.action == "accept":
        ids |= {
            issue_by_id[i]["itemId"]
            for i in operation.issueIds
            if issue_by_id[i]["itemId"] is not None
        }
    if not ids and not operation.issueIds:
        raise HTTPException(422, "Select at least one item or issue")
    if ids - by_id.keys():
        raise HTTPException(404, "Selected item does not belong to this request")
    if set(operation.itemChanges) - ids:
        raise HTTPException(422, "Individual changes must reference selected items")
    explicit_quantity = operation.action == "quantity_rule" and operation.rule == "explicit"
    if explicit_quantity and (set(operation.changes) != {"quantity"} or operation.itemChanges):
        raise HTTPException(422, "An explicit quantity choice requires only one positive quantity")
    if operation.action != "edit" and not explicit_quantity and (operation.changes or operation.itemChanges):
        raise HTTPException(422, "Field changes require an edit operation")
    if operation.rule is not None and operation.action != "quantity_rule":
        raise HTTPException(422, "Quantity rules require a quantity-rule operation")
    if operation.columnRoles and operation.action != "column_mapping":
        raise HTTPException(422, "Column roles require a column-mapping operation")
    if operation.issueIds and operation.action not in {"accept", "column_mapping"}:
        raise HTTPException(422, "Issue decisions require an acceptance operation")
    if len(ids) > 1 and any(
        PUBLIC.get(field, field) in {"name", "item_number"}
        for patch in [operation.changes, *operation.itemChanges.values()]
        for field in patch
    ):
        raise HTTPException(422, "Names and item numbers must be edited individually")
    for i in ids:
        item = by_id[i]
        if not item.source_active or (operation.action == "restore") != (
            item.removed_at is not None
        ):
            raise HTTPException(409, "Selection contains removed or inactive items")
    before = snapshot(state, ids, operation.issueIds, source_data=mapping_issue is not None)
    if mapping_issue:
        apply_mapping(state, mapping_issue, operation.columnRoles, actor)
    eligible = [i for i in operation.itemIds if i in initial["readyIds"]]
    blockers = []
    if operation.action == "verify":
        blockers = [
            {"itemId": i, "message": "Resolve this item's issues before verification"}
            for i in operation.itemIds
            if i not in eligible
        ]
    if blockers:
        return (
            state,
            before,
            before,
            {"eligibleItemIds": eligible, "blockers": blockers, "changes": []},
        )
    if operation.action == "accept":
        if not operation.issueIds:
            raise HTTPException(422, "Select the specific issues to accept")
        accept(state, initial["issues"], operation.issueIds, actor)
    now = dt.datetime.now(dt.UTC)
    for item_id in sorted(ids):
        item = by_id[item_id]
        if operation.action in {"edit", "quantity_rule"}:
            submitted = {**operation.changes, **operation.itemChanges.get(item_id, {})}
            if submitted.get("unit") == item.unit == "":
                submitted.pop("unit", None)  # optional empty unit on existing manual rows
            changes = validate_changes(submitted)
            if operation.action == "quantity_rule" and not explicit_quantity:
                facts = source_facts(parsed_item(state, item))
                key = {
                    "requested_total": "requestedTotal",
                    "pack_calculation": "calculatedTotal",
                }.get(operation.rule)
                value = facts.get(key) if key else None
                if type(value) is not int or value <= 0:
                    raise HTTPException(
                        422, f"Item {item_id} has no valid source value for this rule"
                    )
                changes = {"quantity": value}
            if not changes:
                raise HTTPException(422, "Choose a field to change")
            inferred = dict(item.inferred_fields or {})
            reviews = dict(item.field_reviews or {})
            for field, value in changes.items():
                if isinstance(value, str):
                    value = value.strip() if field != "notes" else value
                setattr(item, field, value)
                inferred.pop(
                    {"domain": "type", "item_number": "itemNumber", "shelf_life": "shelfLife"}.get(
                        field, field
                    ),
                    None,
                )
                reviews[field] = {"source": "human", "actor": actor, "at": now.isoformat()}
            item.inferred_fields = inferred
            item.field_reviews = reviews
            protected = (
                set(item.protected_fields)
                if item.protected_fields is not None
                else {f for f in EDIT_FIELDS if getattr(item, f) not in (None, "")}
            )
            item.protected_fields = sorted(protected | set(changes))
            # A field edit is not a whole-item human confirmation.
            if item.verification_source == "ai":
                item.verification_source = None
            item.status = "verified"  # projection below retains every remaining issue
            updated = synchronize(state)
            resolvable = [
                i
                for i in updated["issues"]
                if i["itemId"] == item_id
                and i["canAccept"]
                and (
                    i["category"] in {"type", "unit", "description"}
                    or i["category"] == "other"
                    and i["fields"]
                    and any(
                        before["items"][str(item_id)].get(field) != getattr(item, field, None)
                        for field in i["fields"]
                    )
                )
                and set(i["fields"]) <= set(changes)
            ]
            if operation.action == "quantity_rule":
                resolvable += [
                    i
                    for i in updated["issues"]
                    if i["itemId"] == item_id and i["category"] == "totals"
                ]
            accept(state, resolvable, {i["id"] for i in resolvable}, actor)
        elif operation.action == "verify":
            item.verification_source = "human"
            item.protected_fields = sorted(set(item.protected_fields or []) | set(EDIT_FIELDS))
            item.field_reviews = {
                f: {"source": "human", "actor": actor, "at": now.isoformat()} for f in EDIT_FIELDS
            }
        elif operation.action == "remove":
            item.removed_at, item.removed_by = now, actor
        elif operation.action == "restore":
            item.removed_at, item.removed_by = None, None
    final = synchronize(state)
    after = snapshot(state, ids, operation.issueIds, source_data=mapping_issue is not None)
    previews = []
    for item_id in sorted(ids):
        old, new = before["items"][str(item_id)], after["items"][str(item_id)]
        changes = {
            k: {"before": old[k], "after": new[k]}
            for k in (*EDIT_FIELDS, "removed_at", "verification_source")
            if old[k] != new[k] or operation.action == "quantity_rule" and k == "quantity"
        }
        preview = {"itemId": item_id, "name": by_id[item_id].name, "fields": changes}
        if operation.action == "accept":
            fields = {
                field
                for issue in initial["issues"]
                if issue["id"] in operation.issueIds and issue["itemId"] == item_id
                for field in (issue["fields"] or ("name", "quantity", "unit", "domain"))
                if field in EDIT_FIELDS
            }
            preview["keptValues"] = {field: old[field] for field in sorted(fields)}
        previews.append(preview)
    return (
        state,
        before,
        after,
        {
            "eligibleItemIds": sorted(ids),
            "blockers": [],
            "changes": previews,
            "reviewCounts": final["reviewCounts"],
            "tableDecision": next(
                (
                    {
                        "worksheet": issue.get("worksheet"),
                        "columns": [{**col, "role": operation.columnRoles.get(col["key"], col["role"])}
                            for col in issue.get("columns", [])] if mapping_issue else issue.get("columns", []),
                        "affectedItems": len(issue.get("itemIds", [])),
                    }
                    for issue in initial["issues"]
                    if issue["id"] in operation.issueIds and issue.get("scope") == "table"
                ),
                None,
            ),
        },
    )


def restore_snapshot(request, value):
    if "sourceData" in value:
        request.ai_review = {**(request.ai_review or {}), "sources": {
            **(request.ai_review or {}).get("sources", {}), **copy.deepcopy(value["sourceData"]),
        }}
    by_id = {i.id: i for i in request.items}
    for item_id, fields in value["items"].items():
        item = by_id[int(item_id)]
        for field, data in fields.items():
            setattr(
                item,
                field,
                dt.datetime.fromisoformat(data)
                if field == "removed_at" and data
                else copy.deepcopy(data),
            )
    rows = {i.id: i for i in request.review_issues}
    selected = {int(i) for i in value["items"]}
    for row in request.review_issues:
        if row.item_id in selected and row.id not in value["issues"]:
            row.resolution = None
    for issue_id, saved in value["issues"].items():
        if issue_id not in rows:
            row = RequestReviewIssueRow(
                id=issue_id,
                request_id=request.request_id,
                item_id=saved["itemId"],
                detail=saved["detail"],
            )
            request.review_issues.append(row)
            rows[issue_id] = row
        rows[issue_id].detail = saved["detail"]
        rows[issue_id].resolution = saved["resolution"]


async def apply(session: AsyncSession, request, operation: ReviewOperation, actor="local"):
    started = time.monotonic()
    prior = await session.get(RequestReviewOperationRow, operation.operationId)
    payload = operation.model_dump(mode="json")
    if prior:
        if prior.request_id != request.request_id or {"columnRoles": {}, **prior.payload} != payload:
            raise HTTPException(409, "Operation ID has already been used")
        return prior
    state, before, after, preview = evaluate(request, operation, actor)
    if preview["blockers"]:
        raise HTTPException(422, preview)
    restore_snapshot(request, after)
    synchronize(request)
    record = RequestReviewOperationRow(
        id=operation.operationId,
        request_id=request.request_id,
        actor=actor,
        action=operation.action,
        payload=payload,
        before=before,
        after=after,
    )
    session.add(record)
    request.review_revision += 1
    await session.flush()
    await session.commit()
    logger.info(
        "Review operation action=%s items=%d seconds=%.3f",
        operation.action,
        len(after["items"]),
        time.monotonic() - started,
    )
    return record


async def resolve_missing_item(session: AsyncSession, request, payload, actor="local"):
    """Create/link one filled row and resolve exactly its missing-row warning atomically."""
    from app.db.repository import append_manual_item

    submitted = payload.model_dump(mode="json")
    prior = await session.get(RequestReviewOperationRow, payload.operationId)
    if prior:
        original = {key: value for key, value in prior.payload.items() if key != "resolvedItemId"}
        if prior.request_id != request.request_id or prior.action != "add_missing" or original != submitted:
            raise HTTPException(409, "Operation ID has already been used")
        return prior
    check_revision(request, payload.expectedRevision)
    if (payload.item is None) == (payload.itemId is None):
        raise HTTPException(422, "Provide the filled item or select an existing manual item")
    initial = synchronize(request)
    issue = next((issue for issue in initial["issues"] if issue["id"] == payload.issueId
        and issue["code"] == "coverage_uncertain" and issue["state"] == "open"), None)
    if issue is None:
        raise HTTPException(409, "This missing-row warning changed or was already resolved")
    created = payload.item is not None
    if created:
        item = append_manual_item(request, payload.item)
        item.source_reference = None
        await session.flush()
        item.removed_at, item.removed_by = dt.datetime.now(dt.UTC), actor
    else:
        item = next((item for item in request.active_items if item.id == payload.itemId and item.manual), None)
        if item is None:
            raise HTTPException(422, "Select an active manual item from this request")
        if any(other["id"] != issue["id"] and other["state"] == "accepted"
            and other.get("addedItemId") == item.id for other in initial["issues"]):
            raise HTTPException(422, "This item already fills another missing-row warning")
    affected = {item.id} | ({issue["itemId"]} if issue["itemId"] is not None else set())
    before = snapshot(request, affected, [issue["id"]])
    if created:
        item.removed_at, item.removed_by = None, None
    accept(request, initial["issues"], {issue["id"]}, actor)
    saved = next(row for row in request.review_issues if row.id == issue["id"])
    saved.resolution = {**saved.resolution, "addedItemId": item.id}
    synchronize(request)
    after = snapshot(request, affected, [issue["id"]])
    record = RequestReviewOperationRow(
        id=payload.operationId, request_id=request.request_id, actor=actor, action="add_missing",
        payload={**submitted, "resolvedItemId": item.id}, before=before, after=after,
    )
    session.add(record)
    if not created:
        request.review_revision += 1
    await session.commit()
    return record


async def undo(
    session: AsyncSession, request, operation_id: str, payload: UndoOperation, actor="local"
):
    prior = await session.get(RequestReviewOperationRow, payload.operationId)
    if prior:
        if prior.request_id != request.request_id or prior.payload != {
            **payload.model_dump(),
            "undo": operation_id,
        }:
            raise HTTPException(409, "Operation ID has already been used")
        return prior
    check_revision(request, payload.expectedRevision)
    original = await session.get(RequestReviewOperationRow, operation_id)
    if not original or original.request_id != request.request_id:
        raise HTTPException(404, "Operation not found")
    if original.undone_by or original.action == "undo":
        raise HTTPException(409, "This operation cannot be undone")
    state = clone(request)
    synchronize(state)
    current = snapshot(state, {int(i) for i in original.after["items"]}, original.after["issues"], source_data="sourceData" in original.after)
    # Newly detected issues after a real edit are included; unrelated rows are not.
    if current != original.after:
        raise HTTPException(
            409, "Affected items or evidence changed; this operation cannot be undone"
        )
    restore_snapshot(request, original.before)
    synchronize(request)
    record = RequestReviewOperationRow(
        id=payload.operationId,
        request_id=request.request_id,
        actor=actor,
        action="undo",
        payload={**payload.model_dump(), "undo": operation_id},
        before=original.after,
        after=original.before,
    )
    original.undone_by = record.id
    session.add(record)
    request.review_revision += 1
    await session.flush()
    await session.commit()
    return record


def undo_available(request, operation) -> bool:
    """Do not offer an old/conflicting operation merely because it is the latest record."""
    if request.workflow_status != "review" or operation.action == "undo" or operation.undone_by:
        return False
    state = clone(request)
    synchronize(state)
    current = snapshot(state, {int(i) for i in operation.after["items"]}, operation.after["issues"], source_data="sourceData" in operation.after)
    return current == operation.after
