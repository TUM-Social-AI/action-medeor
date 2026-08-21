"""Exact identifiers and normalized-text retrieval."""

from __future__ import annotations

from collections.abc import Sequence

from app.matching.contracts import InquiryLineV1, InventoryItemV1
from app.matching.domain import RetrievalHit, SearchRepresentation
from app.matching.representation import represent_inventory_item


class ExactRetriever:
    name = "exact"

    def search(
        self,
        *,
        line: InquiryLineV1,
        query: SearchRepresentation,
        catalog: Sequence[InventoryItemV1],
        limit: int,
    ) -> list[RetrievalHit]:
        matches: list[tuple[int, str, dict[str, object]]] = []
        for item in catalog:
            reasons: list[str] = []
            priority = 99
            if line.requested_item_number == item.item_number:
                reasons.append("requested_item_number")
                priority = 0
            representation = represent_inventory_item(item)
            if query.semantic_core and query.semantic_core == representation.semantic_core:
                reasons.append("normalized_description")
                priority = min(priority, 1)
            if reasons:
                matches.append((priority, item.item_number, {"reasons": reasons}))

        matches.sort(key=lambda match: (match[0], match[1]))
        return [
            RetrievalHit(
                item_number=item_number,
                retriever=self.name,
                rank=rank,
                score=1.0,
                details=details,
            )
            for rank, (_, item_number, details) in enumerate(matches[:limit], start=1)
        ]
