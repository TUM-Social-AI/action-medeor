import pytest

from app.matching.ranking.features import search_similarity_components


@pytest.mark.parametrize("components,expected", [
    ({"lexical": 0.3, "vector": 0.6, "lexical_weight": 1, "vector_weight": 2}, 50),
    ({"lexical": 0.2}, 20),
    ({"vector": 0.7, "vector_weight": 2}, 70),
    ({"lexical": 0.4, "vector": 0.8}, 60),
    ({"vector": -0.2}, 0),
    ({"lexical": 1, "vector": 1}, 100),
])
def test_similarity_uses_actual_channel_scores_not_candidate_position(components, expected):
    assert search_similarity_components(components)["search_similarity"] == pytest.approx(expected)
    assert search_similarity_components({**components, "rrf": 100, "ranking_score": 100}) == search_similarity_components(components)


def test_history_or_exact_evidence_does_not_invent_similarity():
    assert search_similarity_components({"history": 0.9, "exact_reference": 1}) == {}
