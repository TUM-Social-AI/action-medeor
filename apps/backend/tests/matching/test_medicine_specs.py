import pytest

from app.matching.adapters.in_memory import (
    InMemoryCatalogRepository,
    InMemoryHistoryRepository,
    InMemoryMatchRunRepository,
)
from app.matching.constraints.engine import load_default_policy
from app.matching.constraints.medicine_specs import medicine_checks
from app.matching.contracts import AttributeValue, MatchRequestV1, ProductDomain, RuleOutcome
from app.matching.service import MatchingService
from tests.matching.factories import historical_offer, item, line


@pytest.mark.parametrize(
    "requested,candidate,expected",
    [
        ("Ibuprofen 200 mg tablets", "Ibuprofen 400 mg suspension, 100", RuleOutcome.PASS),
        ("Ibuprofen 200 mg tablets", "Paracetamol 200 mg tablets", RuleOutcome.EXCLUDE),
        ("Vitamin B12 1 mg tablets", "Vitamin B6 1 mg tablets", RuleOutcome.EXCLUDE),
        (
            "Amoxicillin 250 mg + Clavulanic acid 62.5 g/5 ml",
            "Clavulanic acid 125 mg + Amoxicillin 500 mg tablets",
            RuleOutcome.PASS,
        ),
        (
            "Amoxicillin 500 mg + Clavulanic acid 125 mg tablets",
            "Amoxicillin 500 mg tablets",
            RuleOutcome.EXCLUDE,
        ),
        (
            "Amoxicillin 500 mg + Clavulanic acid 125 mg tablets",
            "Ferrous sulphate 200 mg + 0,4 mg Folic acid tablets",
            RuleOutcome.EXCLUDE,
        ),
        ("Ibuprofen 200 mg tablets", "Unknown brand", RuleOutcome.EXCLUDE),
        (
            "Amoxicillin 250 mg tablets",
            "Benzathine benzylpenicillin 2,4 mega powder for injection",
            RuleOutcome.EXCLUDE,
        ),
    ],
)
def test_only_ingredient_identity_is_checked(requested, candidate, expected):
    checks = medicine_checks(line(description=requested), (candidate,))
    assert len(checks) == 1
    assert checks[0].attribute == "active_ingredient"
    assert checks[0].outcome is expected


def test_structured_ingredient_and_form_hint_are_supported():
    inquiry = line(description="Ibuprofen").model_copy(
        update={
            "quantity": line().quantity.model_copy(update={"unit": "tablet"}),
        }
    )
    assert medicine_checks(inquiry, ("Ibuprofen 400 mg suspension",))[0].outcome is RuleOutcome.PASS
    inquiry = inquiry.model_copy(
        update={"attributes": {"active_ingredient": AttributeValue(value="ibuprofen")}}
    )
    assert (
        medicine_checks(
            inquiry, ("Brand",), {"active_ingredient": AttributeValue(value="ibuprofen")}
        )[0].outcome
        is RuleOutcome.PASS
    )


async def test_ingredient_gate_applies_to_medicines_only():
    products = [
        item("same", "Ibuprofen 400 mg suspension"),
        item("wrong", "Paracetamol 200 mg tablets"),
        item("unknown", "Unknown brand tablets"),
    ]
    for domain, expected in [
        (ProductDomain.MEDICINE, {"same"}),
        (ProductDomain.EQUIPMENT, {"same", "wrong", "unknown"}),
    ]:
        service = MatchingService(
            catalog_repository=InMemoryCatalogRepository(
                [
                    product.model_copy(update={"domain": domain, "attributes": {}})
                    for product in products
                ]
            ),
            history_repository=InMemoryHistoryRepository(),
            run_repository=InMemoryMatchRunRepository(),
            policy=load_default_policy(),
            min_semantic_score=0,
        )
        inquiry = line(description="Ibuprofen 200 mg tablets").model_copy(
            update={"domain": domain, "attributes": {}}
        )
        result = await service.match(MatchRequestV1(inquiry_line=inquiry))
        assert {candidate.item_number for candidate in result.candidates} == expected


async def test_wrong_ingredient_historical_offer_requires_fallback_review():
    offer = historical_offer("unused").model_copy(
        update={
            "item_number": None,
            "domain": ProductDomain.MEDICINE,
            "offered_description": "Paracetamol 200 mg tablets",
        }
    )
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository([]),
        history_repository=InMemoryHistoryRepository([offer]),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
        min_semantic_score=0,
    )
    inquiry = line(description="Ibuprofen 200 mg tablets").model_copy(
        update={"domain": ProductDomain.MEDICINE, "attributes": {}}
    )
    result = await service.match(MatchRequestV1(inquiry_line=inquiry))
    assert len(result.candidates) == 1
    assert result.candidates[0].review_status is RuleOutcome.REVIEW
    assert result.candidates[0].score_components["ingredient_fallback"] == 1
