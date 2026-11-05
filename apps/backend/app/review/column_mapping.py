"""Apply a reviewed source layout without another extraction or provider call."""

import datetime as dt

from fastapi import HTTPException

from app.parsing.table_mapping import strict_quantity
from app.parsing.text_heuristics import (
    build_item,
    detect_priority_from_column_value,
    extract_quantity_and_unit,
)
from app.review.taxonomy import classify

ROLES = {
    "name",
    "quantity",
    "quantity_packs",
    "units_per_pack",
    "unit",
    "domain",
    "notes",
    "item_number",
    "shelf_life",
    "priority",
    "translation",
    "attribute",
    "ordinal",
}
FIELDS = ("name", "quantity", "unit", "domain", "notes", "item_number", "shelf_life")


def apply_mapping(state, issue, roles, actor):
    columns = {column["key"] for column in issue["columns"]}
    if set(roles) != columns or set(roles.values()) - ROLES:
        raise HTTPException(422, "Assign a supported role to each supplied source column")
    core = [role for role in roles.values() if role not in {"attribute", "ordinal"}]
    if "name" not in core or len(core) != len(set(core)):
        raise HTTPException(422, "Choose one product-name column and use each field only once")
    sources = state.ai_review.get("sources", {})
    now = dt.datetime.now(dt.UTC).isoformat()
    for item in state.items:
        if item.id not in issue["itemIds"]:
            continue
        if item.manual:
            raise HTTPException(422, "Manual items do not have a source-column mapping")
        source = sources.get(str(item.id), {})
        if set(source.get("headers", {})) != columns:
            raise HTTPException(409, "Source columns changed; refresh the review")
        cells = source.get("cells", {})
        values = {
            role: str(cells.get(col, "")) for col, role in roles.items() if role != "attribute"
        }
        raw_quantity = values.get("quantity", "")
        quantity = strict_quantity(raw_quantity)
        packs, per_pack = (
            strict_quantity(values.get(role, "")) for role in ("quantity_packs", "units_per_pack")
        )
        if not raw_quantity and packs is not None and per_pack is not None:
            quantity = packs * per_pack
        unit = values.get("unit", "") or extract_quantity_and_unit(raw_quantity)[1] or ""
        item.inferred_fields = dict(item.inferred_fields or {})
        item.field_reviews = dict(item.field_reviews or {})
        notes = values.get("notes", "")
        if values.get("translation"):
            notes = f"Translation: {values['translation']}" + (f" · {notes}" if notes else "")
        parsed = build_item(
            name=values.get("name", ""),
            quantity=quantity,
            unit=unit,
            source_type=values.get("domain", ""),
            notes=notes,
            item_number=values.get("item_number", ""),
            shelf_life=values.get("shelf_life", ""),
        )
        protected = (
            set(item.protected_fields)
            if item.protected_fields is not None
            else {field for field in FIELDS if getattr(item, field) not in (None, "")}
        )
        priority = detect_priority_from_column_value(values.get("priority", ""))
        if priority and "priority" not in protected:
            item.priority = priority
            item.field_reviews["priority"] = {"source": "column_mapping", "actor": actor, "at": now}
        item.attributes = {
            **(item.attributes or {}),
            **{
                source["headers"][col]: str(cells.get(col, ""))
                for col, role in roles.items()
                if role == "attribute" and cells.get(col)
            },
        }
        for field in FIELDS:
            if field in protected:
                continue
            setattr(item, field, getattr(parsed, field))
            public = {"domain": "type", "item_number": "itemNumber", "shelf_life": "shelfLife"}.get(
                field, field
            )
            item.inferred_fields.pop(public, None)
            if public in parsed.inferred_fields:
                item.inferred_fields[public] = parsed.inferred_fields[public]
            # Reviewing a table layout does not review each copied item value.
            item.field_reviews[field] = {"source": "column_mapping", "actor": actor, "at": now}
        source["roles"] = {col: role for col, role in roles.items() if role != "attribute"}
        source["mappingUncertain"] = False
        item.review_findings = [
            finding
            for finding in item.review_findings or []
            if classify(finding.get("message", ""), finding.get("code")) != "mapping_uncertain"
            and not (
                classify(finding.get("message", ""), finding.get("code")) == "low_confidence"
                and not finding.get("fields")
            )
        ]
        item.review_reasons = [
            reason
            for reason in item.review_reasons or []
            if classify(reason) not in {"mapping_uncertain", "low_confidence"}
        ]
        item.status, item.confidence, item.verification_source = (
            "verified",
            max(item.confidence or 0, 80),
            None,
        )
