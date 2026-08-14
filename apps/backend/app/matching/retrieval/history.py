"""Historical decisions and offers as a recall channel, never as an override."""

from __future__ import annotations

from collections.abc import Sequence

from app.matching.contracts import HistoricalOfferV1
from app.matching.domain import RetrievalHit, SearchRepresentation
from app.matching.representation import normalize_text, tokenize


def _history_score(query: SearchRepresentation, offer: HistoricalOfferV1) -> float:
    history_tokens = tokenize(offer.raw_request_text)
    union = query.tokens | history_tokens
    return len(query.tokens & history_tokens) / len(union) if union else 0.0


class HistoryRetriever:
    name = "history"

    def search(
        self,
        *,
        query: SearchRepresentation,
        offers: Sequence[HistoricalOfferV1],
        limit: int,
    ) -> list[RetrievalHit]:
        scored: list[tuple[float, str, HistoricalOfferV1]] = []
        for offer in offers:
            if not offer.item_number:
                continue
            score = _history_score(query, offer)
            if score > 0:
                scored.append((score, offer.item_number, offer))
        scored.sort(key=lambda value: (-value[0], value[1], value[2].record_id))
        return [
            RetrievalHit(
                item_number=item_number,
                retriever=self.name,
                rank=rank,
                score=score,
                details={
                    "record_id": offer.record_id,
                    "source_document_id": offer.source.document_id,
                    "offer_date": offer.offer_date.isoformat() if offer.offer_date else None,
                    "normalized_request": normalize_text(offer.raw_request_text),
                },
            )
            for rank, (score, item_number, offer) in enumerate(scored[:limit], start=1)
        ]
