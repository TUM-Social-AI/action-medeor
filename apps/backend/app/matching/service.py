"""Application service orchestrating one reproducible match run."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.matching.constraints.engine import ConstraintEngine, MatchingPolicy
from app.matching.contracts import (
    AvailabilityStatus,
    CandidateType,
    ConstraintResult,
    MatchCandidateV1,
    MatchDecisionRequestV1,
    MatchDecisionResponseV1,
    MatchRequestV1,
    MatchRunResponseV1,
    MatchRunStatus,
    PackagingResult,
    RetrievalEvidence,
    RuleOutcome,
    ValidationStatus,
)
from app.matching.domain import CandidateState
from app.matching.packaging import calculate_packaging, observed_availability
from app.matching.ports import (
    CatalogRepository,
    EmbeddingProvider,
    HistoryRepository,
    MatchRunRepository,
    VectorRepository,
)
from app.matching.ranking.features import description_similarity
from app.matching.ranking.ranker import calculate_ranking_scores, rank_candidates
from app.matching.representation import represent_inquiry
from app.matching.retrieval.exact import ExactRetriever
from app.matching.retrieval.fusion import reciprocal_rank_fusion
from app.matching.retrieval.history import HistoryRetriever
from app.matching.retrieval.lexical import LexicalRetriever
from app.matching.retrieval.vector import VectorRetriever
from app.matching.validation import validate_inquiry

ALGORITHM_VERSION = "allocura-matching-v1"


class MatchingService:
    def __init__(
        self,
        *,
        catalog_repository: CatalogRepository,
        history_repository: HistoryRepository,
        run_repository: MatchRunRepository,
        policy: MatchingPolicy,
        vector_repository: VectorRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._catalog = catalog_repository
        self._history = history_repository
        self._runs = run_repository
        self._constraints = ConstraintEngine(policy)
        self._policy = policy
        self._vectors = VectorRetriever(vector_repository) if vector_repository else None
        self._embedding_provider = embedding_provider
        self._exact = ExactRetriever()
        self._lexical = LexicalRetriever()
        self._historical = HistoryRetriever()

    async def match(self, request: MatchRequestV1) -> MatchRunResponseV1:
        run_id = uuid4()
        created_at = datetime.now(UTC)
        await self._runs.create_run(
            run_id=run_id,
            request=request,
            algorithm_version=ALGORITHM_VERSION,
            policy_version=self._policy.version,
        )

        try:
            validation = validate_inquiry(request.inquiry_line)
            if validation.status is ValidationStatus.INVALID:
                raise ValueError("Inquiry failed validation")

            catalog = list(
                await self._catalog.list_items(
                    domain=request.inquiry_line.domain,
                    snapshot_id=request.catalog_snapshot_id,
                )
            )
            item_by_number = {item.item_number: item for item in catalog}
            query = represent_inquiry(request.inquiry_line)

            result_sets = [
                self._exact.search(
                    line=request.inquiry_line,
                    query=query,
                    catalog=catalog,
                    limit=request.retrieval_limit,
                ),
                self._lexical.search(
                    query=query,
                    catalog=catalog,
                    limit=request.retrieval_limit,
                ),
            ]

            offers = await self._history.list_offers(
                partner_id=request.inquiry_line.partner_id,
                destination_country=request.inquiry_line.destination_country,
                limit=request.retrieval_limit,
            )
            offers_by_id = {offer.record_id: offer for offer in offers}
            result_sets.append(
                self._historical.search(
                    query=query,
                    offers=offers,
                    limit=request.retrieval_limit,
                )
            )

            embedding = request.query_embedding
            model_id = request.embedding_model_id
            if embedding is None and self._embedding_provider is not None:
                generated = await self._embedding_provider.embed_queries([query.canonical_text])
                if len(generated) != 1:
                    raise ValueError("Embedding provider returned an unexpected batch size")
                embedding = tuple(generated[0])
                model_id = self._embedding_provider.model_id
            if embedding is not None and model_id and self._vectors is not None:
                result_sets.append(
                    await self._vectors.search(
                        embedding=embedding,
                        model_id=model_id,
                        domain=request.inquiry_line.domain,
                        limit=request.retrieval_limit,
                        snapshot_id=request.catalog_snapshot_id,
                    )
                )

            states: list[CandidateState] = []
            for item_number, fused_score, evidence in reciprocal_rank_fusion(result_sets):
                item = item_by_number.get(item_number)
                if item is None:
                    continue
                state = CandidateState(item=item, fused_score=fused_score, evidence=evidence)
                state.constraints = self._constraints.evaluate(request.inquiry_line, item)
                state.packaging = calculate_packaging(request.inquiry_line.quantity, item)
                state.warnings.extend(state.packaging.warnings)
                states.append(state)

            availability: dict[str, AvailabilityStatus] = {}
            for state in states:
                assert state.packaging is not None
                status, warning = observed_availability(
                    request.inquiry_line.quantity, state.item, state.packaging
                )
                availability[state.item.item_number] = status
                if warning:
                    state.warnings.append(warning)

            ranked_catalog = rank_candidates(states, availability)
            candidate_rows: list[tuple[str, MatchCandidateV1]] = []
            for state in ranked_catalog:
                candidate_rows.append((state.item.item_number, MatchCandidateV1(
                    candidate_id=uuid5(
                        NAMESPACE_URL, f"allocura:{run_id}:{state.item.item_number}"
                    ),
                    item_number=state.item.item_number,
                    rank=1,
                    descriptions=state.item.descriptions,
                    manufacturer=state.item.manufacturer,
                    review_status=state.review_status,
                    availability_status=availability[state.item.item_number],
                    retrieval_evidence=tuple(hit.as_evidence() for hit in state.evidence),
                    score_components={
                        **state.score_components,
                        "name_similarity": description_similarity(
                            request.inquiry_line.raw_description, state.item.descriptions
                        ),
                    },
                    constraints=tuple(state.constraints),
                    packaging=state.packaging,
                    warnings=tuple(dict.fromkeys(state.warnings)),
                    provenance=(
                        state.item.source,
                        *(
                            offers_by_id[record_id].source
                            for hit in state.evidence
                            if hit.retriever == "history"
                            for record_id in [hit.details.get("record_id")]
                            if isinstance(record_id, str) and record_id in offers_by_id
                        ),
                    ),
                )))

            for offer_rank, (offer, similarity) in enumerate(
                self._historical.search_standalone(
                    query=query, offers=offers, limit=request.retrieval_limit
                ), start=1
            ):
                description = offer.offered_description or offer.raw_request_text
                candidate_rows.append((f"offer:{offer.record_id}", MatchCandidateV1(
                    candidate_id=uuid5(NAMESPACE_URL, f"allocura:{run_id}:offer:{offer.record_id}"),
                    item_number=None,
                    candidate_type=CandidateType.HISTORICAL_OFFER,
                    supplier=offer.supplier,
                    price=offer.price,
                    currency=offer.currency,
                    price_basis=offer.price_basis,
                    unit_price=offer.unit_price,
                    unit_price_unit=offer.unit_price_unit,
                    offer_valid_until=offer.valid_until,
                    offer_date=offer.offer_date,
                    rank=1,
                    descriptions=(description,),
                    review_status=RuleOutcome.REVIEW,
                    availability_status=AvailabilityStatus.UNKNOWN,
                    retrieval_evidence=(RetrievalEvidence(
                        retriever="sharepoint_offer",
                        rank=offer_rank,
                        score=similarity,
                        details={"record_id": offer.record_id},
                    ),),
                    score_components={
                        "rrf": 1 / (60 + offer_rank),
                        "offer_similarity": similarity,
                        "name_similarity": description_similarity(
                            request.inquiry_line.raw_description, (description,)
                        ),
                    },
                    constraints=(ConstraintResult(
                        code="supplier_offer_unverified",
                        outcome=RuleOutcome.REVIEW,
                        message="Supplier offer details require review; product attributes and stock are not verified.",
                    ),),
                    packaging=PackagingResult(status="unknown"),
                    warnings=("Supplier offer availability is not confirmed.",),
                    provenance=(offer.source,),
                )))

            scores = calculate_ranking_scores([
                (key, candidate.review_status, candidate.availability_status,
                 candidate.score_components)
                for key, candidate in candidate_rows
            ])
            candidate_rows.sort(key=lambda row: (-scores[row[0]], row[0]))
            visible_rows = candidate_rows[: request.top_k]
            # A catalog-heavy result can otherwise hide every matching supplier
            # offer, since unverified offers rank below confirmed catalog items.
            if request.top_k > 1 and not any(
                candidate.candidate_type is CandidateType.HISTORICAL_OFFER
                for _, candidate in visible_rows
            ):
                best_offer = next((
                    row for row in candidate_rows
                    if row[1].candidate_type is CandidateType.HISTORICAL_OFFER
                ), None)
                if best_offer is not None:
                    visible_rows = [*visible_rows[: request.top_k - 1], best_offer]
            candidates = tuple(
                candidate.model_copy(update={
                    "rank": rank,
                    "score_components": {
                        **candidate.score_components,
                        "ranking_score": scores[key],
                        "ranking_score_normalized": 1.0,
                    },
                })
                for rank, (key, candidate) in enumerate(visible_rows, start=1)
            )
            completed_at = datetime.now(UTC)
            result = MatchRunResponseV1(
                match_run_id=run_id,
                status=MatchRunStatus.COMPLETED,
                inquiry_id=request.inquiry_line.inquiry_id,
                inquiry_line_id=request.inquiry_line.line_id,
                algorithm_version=ALGORITHM_VERSION,
                policy_version=self._policy.version,
                embedding_model_id=model_id,
                validation=validation,
                candidates=candidates,
                created_at=created_at,
                completed_at=completed_at,
            )
            await self._runs.complete_run(result)
            return result
        except Exception as exc:
            await self._runs.fail_run(run_id=run_id, error=str(exc))
            raise

    async def get_run(self, run_id: UUID) -> MatchRunResponseV1 | None:
        return await self._runs.get_run(run_id)

    async def save_decision(self, decision: MatchDecisionRequestV1) -> MatchDecisionResponseV1:
        return await self._runs.save_decision(decision)
