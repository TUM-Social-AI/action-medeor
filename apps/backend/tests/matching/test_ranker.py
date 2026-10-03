"""All sources compete on retrieval relevance regardless of review or stock."""

from app.matching.contracts import AvailabilityStatus, RuleOutcome
from app.matching.ranking.ranker import calculate_ranking_scores


def test_ranking_score_uses_relevance_without_review_or_stock_preference() -> None:
    rows = [
        (
            "plain",
            RuleOutcome.PASS,
            AvailabilityStatus.UNKNOWN,
            {"rrf": 0.03, "attribute_match_ratio": 0.7},
        ),
        (
            "retrieved",
            RuleOutcome.PASS,
            AvailabilityStatus.UNKNOWN,
            {"rrf": 0.04, "attribute_match_ratio": 0.7},
        ),
        (
            "attributes",
            RuleOutcome.PASS,
            AvailabilityStatus.ON_HAND_SUFFICIENT,
            {"rrf": 0.06, "attribute_match_ratio": 0.6},
        ),
        (
            "exact",
            RuleOutcome.PASS,
            AvailabilityStatus.UNKNOWN,
            {"rrf": 0.01, "exact_reference": 1.0},
        ),
        (
            "review",
            RuleOutcome.REVIEW,
            AvailabilityStatus.ON_HAND_SUFFICIENT,
            {"rrf": 0.08, "exact_reference": 1.0, "attribute_match_ratio": 1.0},
        ),
    ]
    scores = calculate_ranking_scores(rows)

    assert scores["review"] > scores["attributes"] > scores["retrieved"] > scores["plain"]
    assert scores["plain"] > scores["exact"]
    assert max(scores.values()) == 100.0
    assert min(scores.values()) == 0.0
    assert calculate_ranking_scores(list(reversed(rows))) == scores
    assert calculate_ranking_scores(rows[:1])["plain"] == 100.0


def test_equal_relevance_has_equal_score_across_sources() -> None:
    scores = calculate_ranking_scores(
        [
            (
                "erp",
                RuleOutcome.PASS,
                AvailabilityStatus.ON_HAND_SUFFICIENT,
                {"rrf": 0.03, "attribute_match_ratio": 1.0},
            ),
            ("offer:test", RuleOutcome.REVIEW, AvailabilityStatus.UNKNOWN, {"rrf": 0.03}),
        ]
    )
    assert scores["erp"] == scores["offer:test"]
