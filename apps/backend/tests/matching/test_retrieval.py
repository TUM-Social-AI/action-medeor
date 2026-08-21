from app.matching.domain import RetrievalHit
from app.matching.representation import represent_inquiry
from app.matching.retrieval.exact import ExactRetriever
from app.matching.retrieval.fusion import reciprocal_rank_fusion
from app.matching.retrieval.lexical import LexicalRetriever
from tests.matching.factories import item, line


def test_exact_item_number_is_found() -> None:
    catalog = [
        item("410001001", "Foley urinary catheter CH18 sterile"),
        item("410001002", "Foley urinary catheter CH12 sterile", charriere=12),
    ]
    request_line = line(item_number="410001002")
    hits = ExactRetriever().search(
        line=request_line,
        query=represent_inquiry(request_line),
        catalog=catalog,
        limit=10,
    )
    assert hits[0].item_number == "410001002"
    assert hits[0].details["reasons"] == ["requested_item_number"]


def test_lexical_results_are_stably_ranked() -> None:
    catalog = [
        item("410001001", "Foley urinary catheter CH18 sterile"),
        item("410001002", "Examination table adjustable"),
    ]
    query = represent_inquiry(line())
    hits = LexicalRetriever().search(query=query, catalog=catalog, limit=10)
    assert hits[0].item_number == "410001001"
    assert hits[0].score is not None and hits[0].score > hits[1].score


def test_reciprocal_rank_fusion_deduplicates_and_rewards_multiple_channels() -> None:
    fused = reciprocal_rank_fusion(
        [
            [
                RetrievalHit("A", "lexical", 1, 0.9),
                RetrievalHit("B", "lexical", 2, 0.8),
            ],
            [
                RetrievalHit("B", "vector", 1, 0.95),
                RetrievalHit("C", "vector", 2, 0.8),
            ],
        ]
    )
    assert [item_number for item_number, _, _ in fused] == ["B", "A", "C"]
    assert {hit.retriever for hit in fused[0][2]} == {"lexical", "vector"}
