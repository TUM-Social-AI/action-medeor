"""Pure review projection: no provider calls, writes, or dependence on UI state."""

import hashlib
import json
from collections import defaultdict

from app.parsing.ai_review import FIELDS, deterministic_issues, source_quantity
from app.parsing.domain_inference import suggest_domain
from app.parsing.table_mapping import strict_quantity
from app.parsing.types import ParsedLineItem
from app.review.taxonomy import CATEGORIES, classify
from app.review.taxonomy import FIELDS as ISSUE_FIELDS

LABELS = {
    "type": "Choose product types",
    "quantity": "Complete quantities",
    "totals": "Resolve conflicting quantities",
    "unit": "Check requested units",
    "description": "Check product descriptions",
    "source": "Check source extraction",
    "other": "Review other uncertainty",
}
HARD = {"name_required", "type_required", "quantity_required", "quantity_invalid"}
EDIT_FIELDS = (*FIELDS, "priority")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def parsed_item(request, item) -> ParsedLineItem:
    reference = item.source_reference
    return ParsedLineItem(
        **{field: getattr(item, field) for field in FIELDS},
        attributes=dict(item.attributes or {}),
        priority=item.priority,
        confidence=item.confidence,
        status=item.status,
        manual=item.manual,
        inferred_fields=dict(item.inferred_fields or {}),
        review_source=(request.ai_review or {}).get("sources", {}).get(str(item.id), {}),
        excerpt=reference.excerpt if reference else "",
    )


def source_facts(parsed) -> dict:
    source = parsed.review_source

    def role_value(role):
        return " ".join(
            str(source.get("cells", {}).get(c, ""))
            for c, assigned in source.get("roles", {}).items()
            if assigned == role
        )

    packs = strict_quantity(role_value("quantity_packs"))
    per_pack = strict_quantity(role_value("units_per_pack"))
    return {
        "requestedTotal": source_quantity(parsed),
        "packs": packs,
        "unitsPerPack": per_pack,
        "calculatedTotal": packs * per_pack if packs is not None and per_pack is not None else None,
    }


def issue_fingerprint(item, fields, source) -> str:
    dependencies = set(fields or EDIT_FIELDS)
    if "domain" in dependencies:
        dependencies |= {"unit", "name"}
    if "quantity" in dependencies:
        dependencies.add("unit")
    if set(fields) == {"unit"}:
        dependencies |= {"quantity", "domain", "name"}
    return digest(
        {"values": {f: getattr(item, f, None) for f in sorted(dependencies)}, "source": source}
    )


def project(request) -> dict:
    issues = []
    saved = {row.id: row for row in request.review_issues}
    saved_codes = defaultdict(set)
    for row in request.review_issues:
        saved_codes[row.item_id].add(row.detail.get("code"))
    item_order = {item.id: index for index, item in enumerate(request.active_items)}
    for item in request.active_items:
        parsed = parsed_item(request, item)
        source = parsed.review_source
        facts = source_facts(parsed)
        source_scope = digest(
            {
                "worksheet": source.get("worksheet", request.selected_sheet),
                "page": item.source_reference.page if item.source_reference else 0,
                "headers": source.get("headers", {}),
                "roles": source.get("roles", {}),
            }
        )[:16]
        findings = {}

        def add(reason, origin="rules", code=None, fields=None):
            code = classify(reason, code)
            category = CATEGORIES[code]
            fields = (
                ISSUE_FIELDS[category]
                if category in {"type", "quantity", "totals", "unit", "description"}
                else fields or ISSUE_FIELDS[category]
            )
            key = (code, tuple(sorted(fields)))
            if key in findings:
                findings[key]["origins"] = sorted(set(findings[key]["origins"] + [origin]))
                return
            findings[key] = {
                "code": code,
                "category": category,
                "fields": fields,
                "message": reason,
                "origins": [origin],
            }

        for reason in deterministic_issues(parsed):
            if item.manual and not item.unit and reason == "Requested unit is unclear":
                continue
            add(reason)
        # Parser-specific findings which cannot be recovered from final copied values.
        for finding in item.review_findings or []:
            code = classify(finding.get("message", ""), finding.get("code"))
            if code in {"name_required", "type_required", "quantity_required", "quantity_invalid"}:
                continue  # current values, rather than stale initial findings, decide validity
            if code == "type_conflict" and "type_conflict" not in {k[0] for k in findings}:
                if finding.get("origin") == "rules":
                    continue
            add(
                finding.get("message", "Check the source"),
                finding.get("origin", "ai"),
                code,
                finding.get("fields"),
            )
        for reason in item.review_reasons or []:
            code = classify(reason)
            if code == "other":
                add(reason, "legacy")
        if not findings and item.verification_source != "human" and not item.manual:
            had_specific_issue = bool(
                saved_codes[item.id] - {"low_confidence", "confirmation_required", "other"}
            )
            if not had_specific_issue and (
                item.status == "low_confidence"
                or item.confidence is not None
                and item.confidence < 80
            ):
                add("Confidence is low; inspect the source", code="low_confidence")
            elif item.status != "verified":
                add("Confirm this item against the source", code="confirmation_required")
        for finding in findings.values():
            code = finding["code"]
            issue_id = digest([request.request_id, item.id, code, sorted(finding["fields"])])[:32]
            evidence_hash = issue_fingerprint(item, finding["fields"], source)
            prior = saved.get(issue_id)
            resolution = prior.resolution if prior is not None else None
            accepted = bool(resolution and resolution.get("fingerprint") == evidence_hash)
            suggested = suggest_domain(item.name, item.unit) if code == "type_required" else None
            issue = {
                **finding,
                "id": issue_id,
                "itemId": item.id,
                "blocking": True,
                "canAccept": code not in HARD,
                "fingerprint": evidence_hash,
                "state": "accepted" if accepted else "open",
                "sourceScope": source_scope,
                "suggestedValue": suggested,
                "evidence": parsed.excerpt,
                **facts,
            }
            issues.append(issue)
    # Only known extraction-structure notes block; service availability is informational.
    for warning in request.parser_warnings or []:
        if "No requested line items" in warning:
            issue_id = digest([request.request_id, "document", warning])[:32]
            prior = saved.get(issue_id)
            fp = digest([warning, request.selected_sheets])
            accepted = bool(
                prior and prior.resolution and prior.resolution.get("fingerprint") == fp
            )
            issues.append(
                {
                    "id": issue_id,
                    "itemId": None,
                    "code": "coverage_uncertain",
                    "category": "source",
                    "fields": [],
                    "message": warning,
                    "origins": ["rules"],
                    "blocking": True,
                    "canAccept": True,
                    "fingerprint": fp,
                    "state": "accepted" if accepted else "open",
                    "sourceScope": "document",
                    "suggestedValue": None,
                    "evidence": warning,
                }
            )
    open_issues = [issue for issue in issues if issue["state"] == "open"]
    grouped = defaultdict(list)
    for issue in open_issues:
        category = issue["category"]
        # Freeform exceptions need individual inspection, not a blanket acceptance.
        individual = issue["itemId"] if category in {"other", "description"} else None
        key = (
            category,
            issue["code"],
            tuple(issue["fields"]),
            issue["sourceScope"],
            issue["suggestedValue"],
            individual,
        )
        grouped[key].append(issue)
    tasks = []
    for key, members in grouped.items():
        item_ids = list(dict.fromkeys(i["itemId"] for i in members if i["itemId"] is not None))
        rank = (
            0
            if key[0] == "source"
            else 1
            if members[0]["code"] in HARD
            else 2
            if key[0] in {"totals", "unit", "type"}
            else 3
        )
        tasks.append(
            {
                "id": digest(key)[:24],
                "category": key[0],
                "code": key[1],
                "title": LABELS[key[0]],
                "itemIds": item_ids,
                "issueIds": [i["id"] for i in members],
                "suggestedValue": key[4],
                "canAccept": all(i["canAccept"] for i in members),
                "rank": rank,
            }
        )
    tasks.sort(
        key=lambda t: (
            t["rank"],
            -len(t["itemIds"]),
            min((item_order[i] for i in t["itemIds"]), default=-1),
            t["id"],
        )
    )
    affected = {i["itemId"] for i in open_issues if i["itemId"] is not None}
    ready = [item.id for item in request.active_items if item.id not in affected]
    return {
        "issues": issues,
        "tasks": tasks,
        "readyIds": ready,
        "canStartMatching": bool(ready)
        and len(ready) == len(request.active_items)
        and not open_issues,
        "reviewCounts": {
            "active": len(request.active_items),
            "ready": len(ready),
            "affected": len(affected),
            "issues": len(open_issues),
            "removed": sum(i.removed_at is not None and i.source_active for i in request.items),
        },
    }


def synchronize(request):
    """Persist the current projection inside the caller's transaction."""
    from app.db.models import RequestReviewIssueRow

    projection = project(request)
    saved = {row.id: row for row in request.review_issues}
    present = {detail["id"] for detail in projection["issues"]}
    for row in request.review_issues:
        if row.id not in present:
            row.detail = {**row.detail, "state": "inactive"}
    for detail in projection["issues"]:
        row = saved.get(detail["id"])
        if row is None:
            row = RequestReviewIssueRow(
                id=detail["id"],
                request_id=request.request_id,
                item_id=detail["itemId"],
                detail=detail,
            )
            request.review_issues.append(row)
        row.detail = detail
    open_by_item = defaultdict(list)
    for issue in projection["issues"]:
        if issue["state"] == "open" and issue["itemId"] is not None:
            open_by_item[issue["itemId"]].append(issue["message"])
    for item in request.active_items:
        item.review_reasons = open_by_item[item.id]
        item.status = (
            "missing"
            if not item.name.strip() or item.quantity is None
            else "needs_review"
            if item.review_reasons
            else "verified"
        )
    return projection
