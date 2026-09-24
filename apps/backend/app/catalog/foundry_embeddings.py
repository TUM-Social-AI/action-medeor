"""Azure OpenAI embedding deployments exposed through Microsoft Foundry."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence

import httpx

from app.catalog.embeddings import EmbeddingModelSpec

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _normalize(vector: Sequence[float], *, dimensions: int) -> list[float]:
    if len(vector) != dimensions:
        raise ValueError(
            f"Embedding provider returned {len(vector)} dimensions; expected {dimensions}"
        )
    values = [float(value) for value in vector]
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("Embedding provider returned an empty or non-finite vector")
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude == 0:
        raise ValueError("Embedding provider returned a zero vector")
    return [value / magnitude for value in values]


class AzureOpenAIEmbeddingProvider:
    """Call an Azure OpenAI embedding deployment hosted by a Foundry resource."""

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        model_name: str,
        model_version: str,
        dimensions: int,
        api_key: str,
        batch_size: int = 32,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        required = {
            "Azure Foundry endpoint": endpoint,
            "Azure Foundry deployment": deployment,
            "embedding model name": model_name,
            "embedding model version": model_version,
            "Azure Foundry API key": api_key,
        }
        for label, value in required.items():
            if not value.strip():
                raise ValueError(f"{label} is required")
        if dimensions < 1:
            raise ValueError("Embedding dimensions must be positive")
        if batch_size < 1:
            raise ValueError("Embedding batch size must be positive")
        if max_retries < 0:
            raise ValueError("Embedding max retries cannot be negative")
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._model_name = model_name
        self._model_version = model_version
        self._dimensions = dimensions
        self._api_key = api_key
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._client = client
        self._input_tokens_used = 0
        self._requests_attempted = 0
        self._successful_requests = 0
        self._batches_attempted = 0
        self._batches_completed = 0
        self._texts_embedded = 0
        self._current_operation: str | None = None
        self._current_batch: int | None = None
        self._total_batches: int | None = None
        self._last_http_error: dict[str, object] | None = None

    @property
    def model_id(self) -> str:
        return (
            f"azure-openai:{self._model_name}@{self._model_version}"
            f":dimensions={self._dimensions}"
        )

    @property
    def input_tokens_used(self) -> int:
        return self._input_tokens_used

    @property
    def diagnostics(self) -> dict[str, object]:
        """Return progress that remains useful when a multi-batch run fails."""
        return {
            "requests_attempted": self._requests_attempted,
            "successful_requests": self._successful_requests,
            "batches_attempted": self._batches_attempted,
            "batches_completed": self._batches_completed,
            "texts_embedded": self._texts_embedded,
            "input_tokens": self._input_tokens_used,
            "current_operation": self._current_operation,
            "current_batch": self._current_batch,
            "total_batches": self._total_batches,
            "last_http_error": self._last_http_error,
        }

    async def spec(self) -> EmbeddingModelSpec:
        return EmbeddingModelSpec(
            model_id=self.model_id,
            provider="azure-openai",
            name=self._model_name,
            version=self._model_version,
            dimensions=self._dimensions,
        )

    async def _post(self, texts: Sequence[str]) -> list[list[float]]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30, read=60, write=30, pool=30)
        )
        try:
            for attempt in range(self._max_retries + 1):
                try:
                    self._requests_attempted += 1
                    response = await client.post(
                        f"{self._endpoint}/openai/v1/embeddings",
                        headers={"api-key": self._api_key, "Content-Type": "application/json"},
                        json={
                            "model": self._deployment,
                            "input": list(texts),
                            "dimensions": self._dimensions,
                            "encoding_format": "float",
                        },
                    )
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == self._max_retries:
                        raise
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                if response.status_code not in _RETRYABLE_STATUS_CODES:
                    if response.is_error:
                        self._record_http_error(response)
                    response.raise_for_status()
                    break
                if attempt == self._max_retries:
                    self._record_http_error(response)
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2**attempt, 8)
                await asyncio.sleep(delay)

            self._successful_requests += 1
            body = response.json()
            data = sorted(body.get("data", []), key=lambda item: item["index"])
            if len(data) != len(texts):
                raise ValueError("Embedding provider returned an unexpected batch size")
            self._input_tokens_used += int(body.get("usage", {}).get("prompt_tokens", 0))
            return [
                _normalize(item["embedding"], dimensions=self._dimensions) for item in data
            ]
        finally:
            if owns_client:
                await client.aclose()

    async def _embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors: list[list[float]] = []
        self._total_batches = math.ceil(len(texts) / self._batch_size)
        for batch_number, start in enumerate(
            range(0, len(texts), self._batch_size), start=1
        ):
            batch = texts[start : start + self._batch_size]
            self._current_batch = batch_number
            self._batches_attempted += 1
            vectors.extend(await self._post(batch))
            self._batches_completed += 1
            self._texts_embedded += len(batch)
        return vectors

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self._current_operation = "catalog"
        return await self._embed(texts)

    async def embed_queries(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self._current_operation = "queries"
        return await self._embed(texts)

    def _record_http_error(self, response: httpx.Response) -> None:
        try:
            response_body: object = response.json()
        except (ValueError, UnicodeDecodeError):
            response_body = response.text[:2000]
        self._last_http_error = {
            "status_code": response.status_code,
            "reason_phrase": response.reason_phrase,
            "response_body": response_body,
        }


class AzureCohereEmbeddingProvider:
    """Call a Cohere embedding deployment through the Foundry model inference API."""

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        model_name: str,
        model_version: str,
        dimensions: int,
        api_key: str,
        batch_size: int = 32,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        required = {
            "Azure Foundry endpoint": endpoint,
            "Azure Foundry deployment": deployment,
            "embedding model name": model_name,
            "embedding model version": model_version,
            "Azure Foundry API key": api_key,
        }
        for label, value in required.items():
            if not value.strip():
                raise ValueError(f"{label} is required")
        if dimensions < 1:
            raise ValueError("Embedding dimensions must be positive")
        if batch_size < 1:
            raise ValueError("Embedding batch size must be positive")
        if max_retries < 0:
            raise ValueError("Embedding max retries cannot be negative")
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._model_name = model_name
        self._model_version = model_version
        self._dimensions = dimensions
        self._api_key = api_key
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._client = client
        self._input_tokens_used = 0
        self._requests_attempted = 0
        self._successful_requests = 0
        self._batches_attempted = 0
        self._batches_completed = 0
        self._texts_embedded = 0
        self._current_operation: str | None = None
        self._current_batch: int | None = None
        self._total_batches: int | None = None
        self._last_http_error: dict[str, object] | None = None

    @property
    def model_id(self) -> str:
        return (
            f"azure-cohere:{self._model_name}@{self._model_version}"
            f":dimensions={self._dimensions}"
        )

    @property
    def input_tokens_used(self) -> int:
        return self._input_tokens_used

    @property
    def diagnostics(self) -> dict[str, object]:
        """Return progress that remains useful when a multi-batch run fails."""
        return {
            "requests_attempted": self._requests_attempted,
            "successful_requests": self._successful_requests,
            "batches_attempted": self._batches_attempted,
            "batches_completed": self._batches_completed,
            "texts_embedded": self._texts_embedded,
            "input_tokens": self._input_tokens_used,
            "current_operation": self._current_operation,
            "current_batch": self._current_batch,
            "total_batches": self._total_batches,
            "last_http_error": self._last_http_error,
        }

    async def spec(self) -> EmbeddingModelSpec:
        return EmbeddingModelSpec(
            model_id=self.model_id,
            provider="azure-cohere",
            name=self._model_name,
            version=self._model_version,
            dimensions=self._dimensions,
        )

    async def _post(
        self, texts: Sequence[str], *, input_type: str
    ) -> list[list[float]]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30, read=60, write=30, pool=30)
        )
        try:
            for attempt in range(self._max_retries + 1):
                try:
                    self._requests_attempted += 1
                    response = await client.post(
                        f"{self._endpoint}/models/embeddings",
                        params={"api-version": "2024-05-01-preview"},
                        headers={"api-key": self._api_key, "Content-Type": "application/json"},
                        json={
                            "model": self._deployment,
                            "input": list(texts),
                            "input_type": input_type,
                            "encoding_format": "float",
                        },
                    )
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == self._max_retries:
                        raise
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                if response.status_code not in _RETRYABLE_STATUS_CODES:
                    if response.is_error:
                        self._record_http_error(response)
                    response.raise_for_status()
                    break
                if attempt == self._max_retries:
                    self._record_http_error(response)
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2**attempt, 8)
                await asyncio.sleep(delay)

            self._successful_requests += 1
            body = response.json()
            data = sorted(body.get("data", []), key=lambda item: item["index"])
            if len(data) != len(texts):
                raise ValueError("Embedding provider returned an unexpected batch size")
            usage = body.get("usage", {})
            self._input_tokens_used += int(
                usage.get("prompt_tokens", usage.get("input_tokens", 0))
            )
            return [
                _normalize(item["embedding"], dimensions=self._dimensions) for item in data
            ]
        finally:
            if owns_client:
                await client.aclose()

    async def _embed(
        self, texts: Sequence[str], *, input_type: str
    ) -> Sequence[Sequence[float]]:
        vectors: list[list[float]] = []
        self._current_operation = "catalog" if input_type == "document" else "queries"
        self._total_batches = math.ceil(len(texts) / self._batch_size)
        for batch_number, start in enumerate(
            range(0, len(texts), self._batch_size), start=1
        ):
            batch = texts[start : start + self._batch_size]
            self._current_batch = batch_number
            self._batches_attempted += 1
            batch_vectors = await self._post(batch, input_type=input_type)
            vectors.extend(batch_vectors)
            self._batches_completed += 1
            self._texts_embedded += len(batch)
        return vectors

    def _record_http_error(self, response: httpx.Response) -> None:
        try:
            response_body: object = response.json()
        except (ValueError, UnicodeDecodeError):
            response_body = response.text[:2000]
        self._last_http_error = {
            "status_code": response.status_code,
            "reason_phrase": response.reason_phrase,
            "response_body": response_body,
        }

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return await self._embed(texts, input_type="document")

    async def embed_queries(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return await self._embed(texts, input_type="query")
