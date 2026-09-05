import json

import httpx
import pytest

from app.catalog.embedding_factory import create_embedding_provider
from app.catalog.foundry_embeddings import (
    AzureCohereEmbeddingProvider,
    AzureOpenAIEmbeddingProvider,
)
from app.core.config import Settings


@pytest.mark.asyncio
async def test_azure_openai_provider_orders_normalizes_and_tracks_usage() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 3.0]},
                    {"index": 0, "embedding": [4.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 7},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureOpenAIEmbeddingProvider(
            endpoint="https://foundry.example.test/",
            deployment="allocura-small",
            model_name="text-embedding-3-small",
            model_version="2024-01-01",
            dimensions=2,
            api_key="secret-key",
            client=client,
        )
        vectors = await provider.embed_queries(["first", "second"])

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert provider.input_tokens_used == 7
    assert provider.model_id == (
        "azure-openai:text-embedding-3-small@2024-01-01:dimensions=2"
    )
    assert requests[0].url == "https://foundry.example.test/openai/v1/embeddings"
    assert requests[0].headers["api-key"] == "secret-key"
    assert json.loads(requests[0].content) == {
        "model": "allocura-small",
        "input": ["first", "second"],
        "dimensions": 2,
        "encoding_format": "float",
    }


@pytest.mark.asyncio
async def test_azure_openai_provider_retries_throttling() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureOpenAIEmbeddingProvider(
            endpoint="https://foundry.example.test",
            deployment="allocura-small",
            model_name="text-embedding-3-small",
            model_version="2024-01-01",
            dimensions=2,
            api_key="secret-key",
            client=client,
        )
        assert await provider.embed_documents(["catalog"]) == [[1.0, 0.0]]

    assert calls == 2


@pytest.mark.asyncio
async def test_azure_openai_provider_retries_connection_timeout() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("connection timed out", request=request)
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureOpenAIEmbeddingProvider(
            endpoint="https://foundry.example.test",
            deployment="allocura-small",
            model_name="text-embedding-3-small",
            model_version="2024-01-01",
            dimensions=2,
            api_key="secret-key",
            client=client,
        )
        assert await provider.embed_queries(["query"]) == [[1.0, 0.0]]

    assert calls == 2


@pytest.mark.asyncio
async def test_azure_openai_provider_rejects_wrong_dimensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureOpenAIEmbeddingProvider(
            endpoint="https://foundry.example.test",
            deployment="allocura-small",
            model_name="text-embedding-3-small",
            model_version="2024-01-01",
            dimensions=2,
            api_key="secret-key",
            client=client,
        )
        with pytest.raises(ValueError, match="1 dimensions; expected 2"):
            await provider.embed_queries(["query"])


def test_factory_builds_azure_openai_provider() -> None:
    provider = create_embedding_provider(
        Settings(
            embedding_provider="azure-openai",
            embedding_model_name="text-embedding-3-small",
            embedding_model_version="2024-01-01",
            embedding_deployment="allocura-small",
            embedding_dimensions=2,
            azure_foundry_endpoint="https://foundry.example.test",
            azure_foundry_api_key="secret-key",
        )
    )

    assert provider is not None
    assert provider.model_id.endswith(":dimensions=2")


@pytest.mark.asyncio
async def test_azure_cohere_provider_uses_document_and_query_roles() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [3.0, 4.0]}],
                "usage": {"prompt_tokens": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureCohereEmbeddingProvider(
            endpoint="https://foundry.example.test/",
            deployment="cohere-multilingual",
            model_name="Cohere-embed-v3-multilingual",
            model_version="1",
            dimensions=2,
            api_key="secret-key",
            client=client,
        )
        assert await provider.embed_documents(["catalog"]) == [[0.6, 0.8]]
        assert await provider.embed_queries(["request"]) == [[0.6, 0.8]]

    assert provider.input_tokens_used == 10
    assert provider.model_id == "azure-cohere:Cohere-embed-v3-multilingual@1:dimensions=2"
    assert requests[0].url == (
        "https://foundry.example.test/models/embeddings?api-version=2024-05-01-preview"
    )
    assert json.loads(requests[0].content) == {
        "model": "cohere-multilingual",
        "input": ["catalog"],
        "input_type": "document",
        "encoding_format": "float",
    }
    assert json.loads(requests[1].content)["input_type"] == "query"


@pytest.mark.asyncio
async def test_azure_cohere_provider_preserves_partial_failure_diagnostics() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"index": 0, "embedding": [1.0, 0.0]}],
                    "usage": {"prompt_tokens": 4},
                },
            )
        return httpx.Response(
            404,
            headers={"x-ms-error-code": "DeploymentNotFound"},
            json={"error": {"code": "DeploymentNotFound", "message": "missing"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureCohereEmbeddingProvider(
            endpoint="https://foundry.example.test",
            deployment="cohere-multilingual",
            model_name="Cohere-embed-v3-multilingual",
            model_version="1",
            dimensions=2,
            api_key="secret-key",
            batch_size=1,
            client=client,
        )
        with pytest.raises(httpx.HTTPStatusError, match="404"):
            await provider.embed_documents(["first", "second"])

    assert provider.diagnostics == {
        "requests_attempted": 2,
        "successful_requests": 1,
        "batches_attempted": 2,
        "batches_completed": 1,
        "texts_embedded": 1,
        "input_tokens": 4,
        "current_operation": "catalog",
        "current_batch": 2,
        "total_batches": 2,
        "last_http_error": {
            "status_code": 404,
            "reason_phrase": "Not Found",
            "response_body": {
                "error": {"code": "DeploymentNotFound", "message": "missing"}
            },
        },
    }


def test_factory_builds_azure_cohere_provider() -> None:
    provider = create_embedding_provider(
        Settings(
            embedding_provider="azure-cohere",
            embedding_model_name="Cohere-embed-v3-multilingual",
            embedding_model_version="1",
            embedding_deployment="Cohere-embed-v3-multilingual",
            embedding_dimensions=1024,
            azure_foundry_endpoint="https://foundry.example.test",
            azure_foundry_api_key="secret-key",
        )
    )

    assert provider is not None
    assert provider.model_id.startswith("azure-cohere:")
