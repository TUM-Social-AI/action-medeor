"""Construct the configured embedding provider without coupling callers to vendors."""

from __future__ import annotations

from app.catalog.embeddings import CatalogEmbeddingProvider, SentenceTransformerEmbeddingProvider
from app.catalog.foundry_embeddings import (
    AzureCohereEmbeddingProvider,
    AzureOpenAIEmbeddingProvider,
)
from app.core.config import Settings


def create_embedding_provider(settings: Settings) -> CatalogEmbeddingProvider | None:
    provider = settings.embedding_provider.strip().casefold()
    if not provider:
        return None
    if provider == "sentence-transformers":
        if not settings.embedding_model_name:
            raise ValueError("EMBEDDING_MODEL_NAME is required")
        return SentenceTransformerEmbeddingProvider(
            settings.embedding_model_name,
            revision=settings.embedding_model_revision,
            batch_size=settings.embedding_batch_size,
        )
    if provider == "azure-openai":
        if settings.embedding_dimensions is None:
            raise ValueError("EMBEDDING_DIMENSIONS is required")
        return AzureOpenAIEmbeddingProvider(
            endpoint=settings.azure_foundry_endpoint,
            deployment=settings.embedding_deployment,
            model_name=settings.embedding_model_name,
            model_version=settings.embedding_model_version,
            dimensions=settings.embedding_dimensions,
            api_key=settings.azure_foundry_api_key,
            batch_size=settings.embedding_batch_size,
        )
    if provider == "azure-cohere":
        if settings.embedding_dimensions is None:
            raise ValueError("EMBEDDING_DIMENSIONS is required")
        return AzureCohereEmbeddingProvider(
            endpoint=settings.azure_foundry_endpoint,
            deployment=settings.embedding_deployment,
            model_name=settings.embedding_model_name,
            model_version=settings.embedding_model_version,
            dimensions=settings.embedding_dimensions,
            api_key=settings.azure_foundry_api_key,
            batch_size=settings.embedding_batch_size,
        )
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")
