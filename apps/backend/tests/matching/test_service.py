from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.matching.adapters.in_memory import (
    InMemoryCatalogRepository,
    InMemoryHistoryRepository,
    InMemoryMatchRunRepository,
    InMemoryVectorRepository,
)
from app.matching.constraints.engine import load_default_policy
from app.matching.contracts import (
    AvailabilityStatus,
    CandidateType,
    DecisionType,
    MatchDecisionRequestV1,
    MatchRequestV1,
    MatchRunResponseV1,
    QuantityValue,
    RuleOutcome,
    SourceType,
)
from app.matching.service import MatchingService
from tests.matching.factories import historical_offer, item, line


@pytest.mark.parametrize("request_unit", ["piece", "packs", "unknown-unit"])
async def test_package_metadata_is_preserved_independently_of_conversion(request_unit):
    product = item("410001001", "Foley catheter sterile CH18", on_hand=Decimal("60"))
    product = product.model_copy(update={
        "package": product.package.model_copy(update={"stock_unit": "PAKET"}),
    })
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([product]),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(), policy=load_default_policy(),
    )
    inquiry = line(description=product.descriptions[0]).model_copy(update={
        "quantity": QuantityValue(value=50, unit=request_unit),
    })
    result = await service.match(MatchRequestV1(inquiry_line=inquiry))
    assert result.candidates[0].package == product.package
    payload = result.model_dump(mode="json")
    assert MatchRunResponseV1.model_validate(payload).candidates[0].package == product.package
    payload["candidates"][0].pop("package")
    assert MatchRunResponseV1.model_validate(payload).candidates[0].package is None


@pytest.mark.parametrize(
    "request_unit,expected", [("packs", AvailabilityStatus.ON_HAND_SUFFICIENT),
                             ("pieces", AvailabilityStatus.UNKNOWN)]
)
async def test_known_stock_is_preserved_when_request_conversion_is_unknown(request_unit, expected):
    candidate = item("410001001", "Foley catheter sterile CH18", on_hand=Decimal("60"))
    candidate = candidate.model_copy(update={
        "package": None,
        "stock": candidate.stock.model_copy(update={
            "unit": "PAKET", "incoming_purchase_order": Decimal("15"),
            "committed_order": Decimal("5"),
        }),
    })
    inquiry = line(description="Foley catheter sterile CH18")
    inquiry = inquiry.model_copy(update={
        "quantity": inquiry.quantity.model_copy(update={"unit": request_unit}),
    })
    runs = InMemoryMatchRunRepository()
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([candidate]),
        history_repository=InMemoryHistoryRepository([]), run_repository=runs,
        policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(inquiry_line=inquiry))
    matched = result.candidates[0]
    assert matched.available_quantity == Decimal("50")
    assert matched.stock_unit == "PAKET"
    assert matched.availability_status is expected
    assert matched.required_stock_quantity == (
        Decimal("50") if expected is AvailabilityStatus.ON_HAND_SUFFICIENT else None
    )
    assert len(matched.warnings) == (1 if expected is AvailabilityStatus.UNKNOWN else 0)
    payload = result.model_dump(mode="json")
    assert MatchRunResponseV1.model_validate(payload).candidates[0].available_quantity == Decimal("50")
    assert MatchRunResponseV1.model_validate(payload).candidates[0].required_stock_quantity == matched.required_stock_quantity
    payload["candidates"][0].pop("available_quantity")
    payload["candidates"][0].pop("required_stock_quantity")
    payload["candidates"][0].pop("stock_unit")
    assert MatchRunResponseV1.model_validate(payload).candidates[0].available_quantity is None
    assert MatchRunResponseV1.model_validate(payload).candidates[0].required_stock_quantity is None


@pytest.mark.asyncio
async def test_complete_hybrid_match_is_reproducible_and_excludes_inactive_item() -> None:
    correct = item("410001001", "Foley urinary catheter sterile CH18", on_hand=Decimal("80"))
    wrong_size = item(
        "410001002", "Foley urinary catheter sterile CH12", charriere=12, on_hand=Decimal("500")
    )
    inactive = item(
        "410001003", "Foley urinary catheter sterile CH18", active=False, on_hand=Decimal("500")
    )
    catalog = InMemoryCatalogRepository([wrong_size, inactive, correct])
    history = InMemoryHistoryRepository([historical_offer("410001003")])
    vectors = InMemoryVectorRepository()
    vectors.add(
        item_number="410001001",
        model_id="model-v1",
        domain=correct.domain,
        embedding=(1.0, 0.0),
    )
    vectors.add(
        item_number="410001002",
        model_id="model-v1",
        domain=correct.domain,
        embedding=(0.5, 0.5),
    )
    vectors.add(
        item_number="410001003",
        model_id="model-v1",
        domain=correct.domain,
        embedding=(1.0, 0.0),
    )
    runs = InMemoryMatchRunRepository()
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=catalog,
        history_repository=history,
        run_repository=runs,
        vector_repository=vectors,
        policy=load_default_policy(),
    )

    result = await service.match(
        MatchRequestV1(
            inquiry_line=line(),
            query_embedding=(1.0, 0.0),
            embedding_model_id="model-v1",
        )
    )

    assert [candidate.item_number for candidate in result.candidates] == [
        "410001001",
        "410001002",
    ]
    assert result.candidates[0].review_status is RuleOutcome.PASS
    assert result.candidates[1].review_status is RuleOutcome.REVIEW
    assert "410001003" not in {candidate.item_number for candidate in result.candidates}
    assert await service.get_run(result.match_run_id) == result

    decision = await service.save_decision(
        MatchDecisionRequestV1(
            match_run_id=result.match_run_id,
            inquiry_line_id="line-1",
            decision_type=DecisionType.ACCEPT_SUGGESTION,
            candidate_id=result.candidates[0].candidate_id,
            selected_item_number="410001001",
            offered_quantity=Decimal("60"),
            actor="tester",
        )
    )
    assert decision.match_run_id == result.match_run_id
    assert len(runs.decisions) == 1


@pytest.mark.asyncio
async def test_sharepoint_offer_source_is_attached_only_to_its_matched_article() -> None:
    offer = historical_offer("410001001")
    offer = offer.model_copy(update={"source": offer.source.model_copy(update={
        "uri": "https://medeor.sharepoint.com/sites/test/offer.xlsx",
    })})
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([
            item("410001001", "Foley urinary catheter sterile CH18"),
            item("410001002", "Foley urinary catheter sterile CH12", charriere=12),
        ]),
        history_repository=InMemoryHistoryRepository([offer]),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )

    result = await service.match(MatchRequestV1(inquiry_line=line()))
    candidates = {candidate.item_number: candidate for candidate in result.candidates}

    assert [source.source_type for source in candidates["410001001"].provenance] == [
        SourceType.ERP, SourceType.SHAREPOINT,
    ]
    assert candidates["410001001"].provenance[1].uri == (
        "https://medeor.sharepoint.com/sites/test/offer.xlsx"
    )
    assert all(source.source_type != "sharepoint" for source in candidates["410001002"].provenance)


@pytest.mark.asyncio
async def test_supplier_offer_without_erp_number_is_selectable_and_links_to_source() -> None:
    offer = historical_offer("410001001")
    offer = offer.model_copy(update={
        "record_id": "offer-without-sku",
        "item_number": None,
        "offered_description": "Sterile Foley urinary catheter CH18",
        "supplier": "Example supplier",
        "unit_price": Decimal("0.42"),
        "unit_price_unit": "piece",
        "currency": "EUR",
        "valid_until": date(2026, 12, 31),
        "offer_date": datetime(2026, 4, 2, tzinfo=UTC),
        "source": offer.source.model_copy(update={
            "uri": "https://medeor.sharepoint.com/sites/test/new-offer.pdf",
        }),
    })
    runs = InMemoryMatchRunRepository()
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository(),
        history_repository=InMemoryHistoryRepository([offer]),
        run_repository=runs,
        policy=load_default_policy(),
    )

    result = await service.match(MatchRequestV1(inquiry_line=line()))

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.candidate_type is CandidateType.HISTORICAL_OFFER
    assert candidate.item_number is None
    assert candidate.supplier == "Example supplier"
    assert candidate.unit_price == Decimal("0.42")
    assert candidate.unit_price_unit == "piece"
    assert candidate.currency == "EUR"
    assert candidate.offer_valid_until == date(2026, 12, 31)
    assert candidate.offer_date == datetime(2026, 4, 2, tzinfo=UTC)
    assert candidate.review_status is RuleOutcome.REVIEW
    assert candidate.provenance == (offer.source,)
    assert candidate.provenance[0].uri == "https://medeor.sharepoint.com/sites/test/new-offer.pdf"
    assert candidate.rank == 1

    decision = await service.save_decision(MatchDecisionRequestV1(
        match_run_id=result.match_run_id,
        inquiry_line_id=result.inquiry_line_id,
        decision_type=DecisionType.ACCEPT_SUGGESTION,
        candidate_id=candidate.candidate_id,
    ))
    assert decision.match_run_id == result.match_run_id
    assert runs.decisions[decision.decision_id].selected_item_number is None


@pytest.mark.asyncio
async def test_supplier_offer_is_ranked_alongside_catalog_article() -> None:
    offer = historical_offer("410001001").model_copy(update={
        "record_id": "standalone-offer",
        "item_number": None,
        "offered_description": "Foley urinary catheter sterile CH18",
    })
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([
            item("410001001", "Foley urinary catheter sterile CH18")
        ]),
        history_repository=InMemoryHistoryRepository([offer]),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )

    result = await service.match(MatchRequestV1(inquiry_line=line()))

    assert {candidate.candidate_type for candidate in result.candidates} == {
        CandidateType.CATALOG, CandidateType.HISTORICAL_OFFER,
    }
    assert [candidate.rank for candidate in result.candidates] == [1, 2]
    assert result.candidates[0].score_components["ranking_score"] > (
        result.candidates[1].score_components["ranking_score"]
    )


@pytest.mark.asyncio
async def test_lower_relevance_supplier_offer_does_not_displace_catalog_top_k() -> None:
    offer = historical_offer("410001001").model_copy(update={
        "record_id": "standalone-offer",
        "item_number": None,
        "offered_description": "Foley catheter",
    })
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([
            item("410001001", "Foley urinary catheter sterile CH18"),
            item("410001002", "Foley sterile urinary catheter CH18"),
        ]),
        history_repository=InMemoryHistoryRepository([offer]),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )

    result = await service.match(MatchRequestV1(inquiry_line=line(), top_k=2))

    assert len(result.candidates) == 2
    assert [candidate.item_number for candidate in result.candidates] == [
        "410001001", "410001002",
    ]


@pytest.mark.asyncio
async def test_unrelated_supplier_offer_is_not_suggested() -> None:
    offer = historical_offer("410001001").model_copy(update={
        "item_number": None,
        "raw_request_text": "Adjustable examination table",
        "offered_description": "Adjustable examination table",
    })
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository(),
        history_repository=InMemoryHistoryRepository([offer]),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(inquiry_line=line()))
    assert result.candidates == ()


@pytest.mark.asyncio
async def test_fallback_without_vectors_or_history_still_returns_lexical_candidates() -> None:
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository(
            [item("410001001", "Foley urinary catheter sterile CH18")]
        ),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(inquiry_line=line()))
    assert result.candidates[0].item_number == "410001001"
    assert {evidence.retriever for evidence in result.candidates[0].retrieval_evidence} == {
        "lexical"
    }


@pytest.mark.asyncio
async def test_pinned_catalog_snapshot_is_also_used_for_vector_retrieval() -> None:
    snapshot_id = "snapshot-a"
    catalog_item = item("410001001", "Foley urinary catheter sterile CH18")
    vectors = InMemoryVectorRepository()
    vectors.add(
        item_number=catalog_item.item_number,
        model_id="model-v1",
        domain=catalog_item.domain,
        embedding=(1.0, 0.0),
        snapshot_id=snapshot_id,
    )
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([catalog_item]),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        vector_repository=vectors,
        policy=load_default_policy(),
    )

    result = await service.match(
        MatchRequestV1(
            inquiry_line=line(),
            catalog_snapshot_id=snapshot_id,
            query_embedding=(1.0, 0.0),
            embedding_model_id="model-v1",
        )
    )

    assert "vector" in {
        evidence.retriever for evidence in result.candidates[0].retrieval_evidence
    }


@pytest.mark.asyncio
async def test_completed_run_may_return_no_candidate_instead_of_padding_top_ten() -> None:
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository(
            [item("410001001", "Foley urinary catheter sterile CH18", active=False)]
        ),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )

    result = await service.match(MatchRequestV1(inquiry_line=line()))

    assert result.candidates == ()


@pytest.mark.asyncio
async def test_suggested_decision_must_reference_an_exposed_candidate() -> None:
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository(
            [item("410001001", "Foley urinary catheter sterile CH18")]
        ),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(inquiry_line=line()))

    with pytest.raises(ValueError, match="not part of the match run"):
        await service.save_decision(
            MatchDecisionRequestV1(
                match_run_id=result.match_run_id,
                inquiry_line_id=result.inquiry_line_id,
                decision_type=DecisionType.ACCEPT_SUGGESTION,
                selected_item_number="not-exposed",
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_until", [date(2020, 1, 1), None])
async def test_old_supplier_offer_remains_matchable_and_selectable(valid_until: date | None) -> None:
    offer = historical_offer("410001001").model_copy(update={
        "item_number": None,
        "offered_description": "Foley urinary catheter sterile CH18",
        "valid_until": valid_until,
        "offer_date": datetime(2019, 12, 1, tzinfo=UTC),
    })
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository(),
        history_repository=InMemoryHistoryRepository([offer]),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(inquiry_line=line()))
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.offer_valid_until == valid_until
    assert candidate.offer_date == datetime(2019, 12, 1, tzinfo=UTC)
    assert candidate.candidate_type is CandidateType.HISTORICAL_OFFER
    decision = await service.save_decision(MatchDecisionRequestV1(
        match_run_id=result.match_run_id,
        inquiry_line_id=result.inquiry_line_id,
        decision_type=DecisionType.ACCEPT_SUGGESTION,
        candidate_id=candidate.candidate_id,
    ))
    assert decision.match_run_id == result.match_run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("top_k", [1, 2, 10])
async def test_better_offer_can_rank_first_on_lexical_and_vector_relevance(top_k) -> None:
    from app.matching.domain import RetrievalHit
    from app.matching.representation import (
        represent_inquiry,
        represent_inventory_item,
        represent_offer,
    )
    from app.matching.retrieval.lexical import lexical_similarity

    inquiry = line(description="Foley urinary catheter sterile CH18").model_copy(
        update={"attributes": {}}
    )
    erp = item("410001001", "Foley urinary catheter sterile", on_hand=Decimal("500"))
    offer = historical_offer(erp.item_number).model_copy(
        update={
            "record_id": "best-offer",
            "item_number": None,
            "offered_description": inquiry.raw_description,
        }
    )
    query = represent_inquiry(inquiry)
    assert lexical_similarity(query, represent_offer(offer)) > lexical_similarity(
        query, represent_inventory_item(erp)
    )

    class Offers:
        async def search_offers(self, **kwargs):
            assert kwargs["embedding"] == (1.0, 0.0)
            return [
                (
                    offer,
                    [
                        RetrievalHit(
                            "offer:best-offer",
                            "lexical",
                            1,
                            lexical_similarity(query, represent_offer(offer)),
                        ),
                        RetrievalHit("offer:best-offer", "vector", 1, 0.99),
                    ],
                )
            ]

    vectors = InMemoryVectorRepository()
    vectors.add(
        item_number=erp.item_number, model_id="model-v1", domain=erp.domain, embedding=(0.8, 0.6)
    )
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([erp]),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
        vector_repository=vectors,
        offer_search_repository=Offers(),
    )
    result = await service.match(
        MatchRequestV1(
            inquiry_line=inquiry,
            query_embedding=(1.0, 0.0),
            embedding_model_id="model-v1",
            top_k=top_k,
        )
    )
    assert result.candidates[0].candidate_type is CandidateType.HISTORICAL_OFFER
    assert result.candidates[0].review_status is RuleOutcome.REVIEW
    assert {hit.retriever for hit in result.candidates[0].retrieval_evidence} == {
        "lexical",
        "vector",
    }
    assert all(hit.rank == 1 for hit in result.candidates[0].retrieval_evidence)
    if top_k > 1:
        assert result.candidates[1].candidate_type is CandidateType.CATALOG
        assert all(hit.rank == 2 for hit in result.candidates[1].retrieval_evidence)
        assert (
            result.candidates[0].score_components["ranking_score"]
            > (result.candidates[1].score_components["ranking_score"])
        )


@pytest.mark.asyncio
async def test_identical_product_text_receives_equal_scores_for_erp_and_offer() -> None:
    description = "Sterile Foley urinary catheter CH18"
    inquiry = line(description=description).model_copy(update={"attributes": {}})
    erp = item("410001001", description, on_hand=Decimal("500")).model_copy(update={
        "manufacturer": None, "attributes": {},
    })
    offer = historical_offer(erp.item_number).model_copy(update={
        "item_number": None, "offered_description": description,
    })
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([erp]),
        history_repository=InMemoryHistoryRepository([offer]),
        run_repository=InMemoryMatchRunRepository(), policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(inquiry_line=inquiry))
    assert len(result.candidates) == 2
    assert {candidate.candidate_type for candidate in result.candidates} == {
        CandidateType.CATALOG, CandidateType.HISTORICAL_OFFER,
    }
    erp_candidate, offer_candidate = result.candidates
    assert erp_candidate.review_status is RuleOutcome.PASS
    assert offer_candidate.review_status is RuleOutcome.REVIEW
    assert erp_candidate.score_components["lexical"] == offer_candidate.score_components["lexical"]
    assert erp_candidate.score_components["rrf"] == offer_candidate.score_components["rrf"]
    assert erp_candidate.score_components["ranking_score"] == (
        offer_candidate.score_components["ranking_score"]
    )


@pytest.mark.asyncio
async def test_erp_restrictions_cannot_fill_retrieval_slots():
    description = "Foley urinary catheter sterile CH18"
    restricted = [
        item("410001001", description, on_hand=Decimal("100")).model_copy(update={"blocked": True}),
        item("410001002", description, on_hand=Decimal("100")).model_copy(
            update={"sales_blocked": True}
        ),
        item("410001003", description, on_hand=Decimal("49")).model_copy(
            update={"purchasing_blocked": True}
        ),
        item("410001100", description, on_hand=Decimal("100")),
    ]
    allowed = item("410001004", description, on_hand=Decimal("50")).model_copy(
        update={"purchasing_blocked": True}
    )
    vectors = InMemoryVectorRepository()
    for candidate in [*restricted, allowed]:
        vectors.add(
            item_number=candidate.item_number,
            model_id="test",
            domain=candidate.domain,
            embedding=(1.0, 0.0),
        )
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([*restricted, allowed]),
        history_repository=InMemoryHistoryRepository([historical_offer("410001001")]),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
        vector_repository=vectors,
    )
    result = await service.match(
        MatchRequestV1(
            inquiry_line=line(),
            retrieval_limit=1,
            query_embedding=(1.0, 0.0),
            embedding_model_id="test",
        )
    )
    assert [candidate.item_number for candidate in result.candidates] == [allowed.item_number]
    assert {hit.retriever for hit in result.candidates[0].retrieval_evidence} >= {
        "lexical",
        "vector",
    }


@pytest.mark.parametrize("vector_weight,expected", [(0.1, "a-lexical"), (1.0, "b-semantic"), (2.0, "b-semantic")])
async def test_configurable_weight_orders_by_displayed_similarity(vector_weight, expected):
    products = [
        item("a-lexical", "Surgical gloves 100 pieces"),
        item("b-semantic", "Surgical examination handwear 50 pieces"),
    ]
    vectors = InMemoryVectorRepository()
    for product, embedding in zip(products, [(0.5, 0.5), (1.0, 0.0)], strict=True):
        vectors.add(item_number=product.item_number, model_id="test-model",
                    domain=product.domain, embedding=embedding)
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository(products),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(), vector_repository=vectors,
        vector_weight=vector_weight,
    )
    result = await service.match(MatchRequestV1(
        inquiry_line=line(description="Surgical gloves 100 pieces"),
        query_embedding=(1.0, 0.0), embedding_model_id="test-model",
    ))
    assert result.candidates[0].item_number == expected
    by_item = {candidate.item_number: candidate for candidate in result.candidates}
    assert by_item["a-lexical"].score_components["rrf"] == pytest.approx(
        1 / 61 + vector_weight / 62
    )
    assert by_item["b-semantic"].score_components["rrf"] == pytest.approx(
        1 / 62 + vector_weight / 61
    )
    for candidate in result.candidates:
        components = candidate.score_components
        assert components["ranking_score"] == components["search_similarity"]
        assert components["search_similarity"] == pytest.approx(
            100 * (components["lexical"] + vector_weight * components["vector"])
            / (1 + vector_weight)
        )
    saved = await service.get_run(result.match_run_id)
    assert saved is not None
    assert saved.candidates == result.candidates
    assert all(candidate.score_components["vector_weight"] == vector_weight
               for candidate in result.candidates)


@pytest.mark.parametrize("weight", [0, -1, float("inf"), float("nan")])
def test_invalid_retrieval_weights_are_rejected(weight):
    for channel in ("lexical", "vector"):
        with pytest.raises(ValueError, match="finite and positive"):
            MatchingService(
                min_semantic_score=0,
                catalog_repository=InMemoryCatalogRepository([]),
                history_repository=InMemoryHistoryRepository(),
                run_repository=InMemoryMatchRunRepository(), policy=load_default_policy(),
                **{f"{channel}_weight": weight},
            )


@pytest.mark.parametrize('top_k', [1, 10])
async def test_equal_relevance_prefers_stock_covering_request_before_top_k(top_k):
    products = [
        item('a-partial', 'Foley urinary catheter sterile CH18', on_hand=Decimal('3000')),
        item('z-sufficient', 'Foley urinary catheter sterile CH18', on_hand=Decimal('7600')),
        item('b-empty', 'Foley urinary catheter sterile CH18', on_hand=Decimal('0')),
        item('c-unknown', 'Foley urinary catheter sterile CH18'),
    ]
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository(products),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(), policy=load_default_policy(),
        min_semantic_score=0,
    )
    inquiry = line(description='Foley urinary catheter sterile CH18')
    inquiry = inquiry.model_copy(update={'quantity': inquiry.quantity.model_copy(update={'value': Decimal('5000')})})
    result = await service.match(MatchRequestV1(inquiry_line=inquiry, top_k=top_k))
    assert [candidate.item_number for candidate in result.candidates] == [
        'z-sufficient', 'a-partial', 'b-empty', 'c-unknown',
    ][:top_k]
    assert len({candidate.score_components['ranking_score'] for candidate in result.candidates}) == 1


@pytest.mark.parametrize("description", ["Surgical examination handwear", "Absaugpumpe"])
async def test_vector_only_retrieval_gets_lexical_score_before_ranking(description):
    products = [item("a", "Surgical gloves"), item("b", description)]
    products = [product.model_copy(update={"attributes": {}, "manufacturer": None}) for product in products]
    vectors = InMemoryVectorRepository()
    for product, embedding in zip(products, [(0.5, 0.5), (1.0, 0.0)], strict=True):
        vectors.add(item_number=product.item_number, model_id="test-model",
                    domain=product.domain, embedding=embedding)
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository(products),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(), vector_repository=vectors,
    )
    result = await service.match(MatchRequestV1(
        inquiry_line=line(description="Surgical gloves").model_copy(update={"attributes": {}}), retrieval_limit=1,
        query_embedding=(1.0, 0.0), embedding_model_id="test-model",
    ))
    candidate = next(candidate for candidate in result.candidates if candidate.item_number == "b")
    assert not any(hit.retriever == "lexical" for hit in candidate.retrieval_evidence)
    assert candidate.score_components["lexical"] >= 0
    if description == "Absaugpumpe":
        assert candidate.score_components["lexical"] == 0
    scores = [candidate.score_components["search_similarity"] for candidate in result.candidates]
    assert scores == sorted(scores, reverse=True)
