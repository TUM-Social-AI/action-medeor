import pytest

from app.catalog.embeddings import SentenceTransformerEmbeddingProvider


def test_e5_instruct_uses_query_instruction_but_plain_documents() -> None:
    provider = SentenceTransformerEmbeddingProvider(
        "intfloat/multilingual-e5-large-instruct"
    )

    assert provider._role_texts(["Foley CH18"], query=False) == ["Foley CH18"]
    assert provider._role_texts(["Sonde CH18"], query=True) == [
        "Instruct: Given a multilingual medical procurement request, retrieve the matching "
        "medical catalog item.\nQuery: Sonde CH18"
    ]


def test_plain_e5_uses_query_and_passage_prefixes() -> None:
    provider = SentenceTransformerEmbeddingProvider("intfloat/multilingual-e5-base")

    assert provider._role_texts(["catalog"], query=False) == ["passage: catalog"]
    assert provider._role_texts(["request"], query=True) == ["query: request"]


def test_embedding_batch_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        SentenceTransformerEmbeddingProvider("example/model", batch_size=0)
