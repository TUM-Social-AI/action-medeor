"""Dependency-free lexical baseline using character and token similarity."""

from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

from app.matching.contracts import InventoryItemV1
from app.matching.domain import RetrievalHit, SearchRepresentation
from app.matching.representation import represent_inventory_item


def lexical_similarity(query: SearchRepresentation, candidate: SearchRepresentation) -> float:
    if not query.canonical_text or not candidate.canonical_text:
        return 0.0
    character_score = SequenceMatcher(
        None, query.canonical_text, candidate.canonical_text, autojunk=False
    ).ratio()
    union = query.tokens | candidate.tokens
    token_score = len(query.tokens & candidate.tokens) / len(union) if union else 0.0
    containment = len(query.tokens & candidate.tokens) / len(query.tokens) if query.tokens else 0.0
    return max(character_score, (0.55 * token_score) + (0.45 * containment))


class LexicalRetriever:
    name = "lexical"

    def search(
        self,
        *,
        query: SearchRepresentation,
        catalog: Sequence[InventoryItemV1],
        limit: int,
    ) -> list[RetrievalHit]:
        scored: list[tuple[float, str]] = []
        for item in catalog:
            candidate = represent_inventory_item(item)
            score = lexical_similarity(query, candidate)
            if score > 0:
                scored.append((score, item.item_number))
        scored.sort(key=lambda match: (-match[0], match[1]))
        return [
            RetrievalHit(
                item_number=item_number,
                retriever=self.name,
                rank=rank,
                score=score,
            )
            for rank, (score, item_number) in enumerate(scored[:limit], start=1)
        ]
