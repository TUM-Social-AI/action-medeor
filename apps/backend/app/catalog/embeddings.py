"""Incremental embedding model adapter and durable database worker."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class EmbeddingModelSpec:
    model_id: str
    provider: str
    name: str
    version: str
    dimensions: int


class SentenceTransformerEmbeddingProvider:
    """Optional open-model provider, loaded only inside a cloud benchmark/worker."""

    def __init__(
        self,
        model_name: str,
        *,
        revision: str = "main",
        batch_size: int = 32,
    ) -> None:
        if batch_size < 1:
            raise ValueError("Embedding batch size must be positive")
        self._model_name = model_name
        self._revision = revision
        self._batch_size = batch_size
        self._model: object | None = None

    @property
    def model_id(self) -> str:
        return f"sentence-transformers:{self._model_name}@{self._revision}"

    def _load(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - depends on optional cloud extra
                raise RuntimeError(
                    "Install the 'embeddings' optional dependency to run open embedding models."
                ) from exc
            self._model = SentenceTransformer(self._model_name, revision=self._revision)
        return self._model

    async def spec(self) -> EmbeddingModelSpec:
        model = await asyncio.to_thread(self._load)
        dimensions = int(model.get_sentence_embedding_dimension())  # type: ignore[attr-defined]
        return EmbeddingModelSpec(
            model_id=self.model_id,
            provider="sentence-transformers",
            name=self._model_name,
            version=self._revision,
            dimensions=dimensions,
        )

    def _role_texts(self, texts: Sequence[str], *, query: bool) -> list[str]:
        """Apply the retrieval format required by E5-family models."""
        model_name = self._model_name.casefold()
        if "e5" not in model_name:
            return list(texts)
        if "instruct" in model_name:
            if not query:
                return list(texts)
            instruction = (
                "Given a multilingual medical procurement request, retrieve the matching "
                "medical catalog item."
            )
            return [f"Instruct: {instruction}\nQuery: {value}" for value in texts]
        prefix = "query: " if query else "passage: "
        return [f"{prefix}{value}" for value in texts]

    async def _embed(
        self,
        texts: Sequence[str],
        *,
        query: bool,
    ) -> Sequence[Sequence[float]]:
        model = await asyncio.to_thread(self._load)
        role_texts = self._role_texts(texts, query=query)

        def encode() -> list[list[float]]:
            vectors = model.encode(  # type: ignore[attr-defined]
                role_texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return [vector.tolist() for vector in vectors]

        return await asyncio.to_thread(encode)

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return await self._embed(texts, query=False)

    async def embed_queries(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return await self._embed(texts, query=True)


def _vector_literal(vector: Sequence[float]) -> str:
    if not vector or not all(math.isfinite(float(value)) for value in vector):
        raise ValueError("Embedding vectors must be non-empty and finite")
    return "[" + ",".join(format(float(value), ".17g") for value in vector) + "]"


class CatalogEmbeddingJobService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_and_activate(
        self, provider: SentenceTransformerEmbeddingProvider
    ) -> tuple[EmbeddingModelSpec, int]:
        spec = await provider.spec()
        await self._session.execute(text("UPDATE embedding_models SET active = FALSE"))
        await self._session.execute(
            text(
                """
                INSERT INTO embedding_models (
                    id, provider, name, version, dimensions, distance_metric, active
                ) VALUES (
                    :id, :provider, :name, :version, :dimensions, 'cosine', TRUE
                )
                ON CONFLICT (id) DO UPDATE SET
                    provider = EXCLUDED.provider,
                    name = EXCLUDED.name,
                    version = EXCLUDED.version,
                    dimensions = EXCLUDED.dimensions,
                    active = TRUE
                """
            ),
            {
                "id": spec.model_id,
                "provider": spec.provider,
                "name": spec.name,
                "version": spec.version,
                "dimensions": spec.dimensions,
            },
        )
        job_ids = list(
            (
                await self._session.scalars(
                    text(
                        """
                        WITH latest_versions AS (
                            SELECT DISTINCT ON (v.item_number) v.id
                            FROM catalog_item_versions v
                            JOIN catalog_items c ON c.item_number = v.item_number
                            WHERE c.active = TRUE
                              AND c.matching_eligible = TRUE
                              AND c.source_missing = FALSE
                            ORDER BY v.item_number, v.valid_from DESC, v.id DESC
                        ), missing AS (
                            SELECT lv.id
                            FROM latest_versions lv
                            LEFT JOIN product_embeddings pe
                              ON pe.catalog_item_version_id = lv.id AND pe.model_id = :model_id
                            WHERE pe.catalog_item_version_id IS NULL
                        )
                        INSERT INTO catalog_embedding_jobs (
                            id, catalog_item_version_id, model_id, status
                        )
                        SELECT gen_random_uuid(), missing.id, :model_id, 'pending'
                        FROM missing
                        ON CONFLICT (catalog_item_version_id, model_id) DO UPDATE SET
                            status = CASE
                                WHEN catalog_embedding_jobs.status = 'completed'
                                THEN catalog_embedding_jobs.status
                                ELSE 'pending'
                            END,
                            error = NULL
                        RETURNING id
                        """
                    ),
                    {"model_id": spec.model_id},
                )
            ).all()
        )
        await self._session.commit()
        return spec, len(job_ids)

    async def process_pending(
        self,
        provider: SentenceTransformerEmbeddingProvider,
        *,
        batch_size: int = 32,
    ) -> dict[str, int]:
        spec = await provider.spec()
        completed = 0
        failed = 0
        stale_before = datetime.now(UTC) - timedelta(hours=1)
        await self._session.execute(
            text(
                """
                UPDATE catalog_embedding_jobs
                SET status = 'pending', error = 'Recovered stale worker job'
                WHERE model_id = :model_id AND status = 'running' AND started_at < :stale_before
                """
            ),
            {"model_id": spec.model_id, "stale_before": stale_before},
        )
        await self._session.commit()

        while True:
            result = await self._session.execute(
                text(
                    """
                    SELECT j.id, j.catalog_item_version_id, v.canonical_text, v.content_hash
                    FROM catalog_embedding_jobs j
                    JOIN catalog_item_versions v ON v.id = j.catalog_item_version_id
                    WHERE j.model_id = :model_id AND j.status = 'pending'
                    ORDER BY j.created_at, j.id
                    LIMIT :batch_size
                    FOR UPDATE OF j SKIP LOCKED
                    """
                ),
                {"model_id": spec.model_id, "batch_size": batch_size},
            )
            rows = list(result.mappings())
            if not rows:
                await self._session.rollback()
                break
            job_ids = [row["id"] for row in rows]
            await self._session.execute(
                text(
                    """
                    UPDATE catalog_embedding_jobs
                    SET status = 'running', attempts = attempts + 1,
                        started_at = CURRENT_TIMESTAMP, error = NULL
                    WHERE id = ANY(CAST(:job_ids AS uuid[]))
                    """
                ),
                {"job_ids": job_ids},
            )
            await self._session.commit()

            try:
                vectors = list(
                    await provider.embed_documents([row["canonical_text"] for row in rows])
                )
                if len(vectors) != len(rows):
                    raise ValueError("Embedding provider returned an unexpected batch size")
                if any(len(vector) != spec.dimensions for vector in vectors):
                    raise ValueError("Embedding provider returned an unexpected vector dimension")
                embedding_rows = [
                    {
                        "version_id": row["catalog_item_version_id"],
                        "model_id": spec.model_id,
                        "content_hash": row["content_hash"],
                        "embedding": _vector_literal(vector),
                    }
                    for row, vector in zip(rows, vectors, strict=True)
                ]
                await self._session.execute(
                    text(
                        """
                        INSERT INTO product_embeddings (
                            catalog_item_version_id, model_id, content_hash, embedding
                        ) VALUES (
                            :version_id, :model_id, :content_hash, CAST(:embedding AS vector)
                        )
                        ON CONFLICT (catalog_item_version_id, model_id) DO NOTHING
                        """
                    ),
                    embedding_rows,
                )
                await self._session.execute(
                    text(
                        """
                        UPDATE catalog_embedding_jobs
                        SET status = 'completed', completed_at = CURRENT_TIMESTAMP, error = NULL
                        WHERE id = ANY(CAST(:job_ids AS uuid[]))
                        """
                    ),
                    {"job_ids": job_ids},
                )
                await self._session.commit()
                completed += len(rows)
            except Exception as exc:
                await self._session.rollback()
                await self._session.execute(
                    text(
                        """
                        UPDATE catalog_embedding_jobs
                        SET status = 'failed', error = :error
                        WHERE id = ANY(CAST(:job_ids AS uuid[]))
                        """
                    ),
                    {"job_ids": job_ids, "error": str(exc)[:4000]},
                )
                await self._session.commit()
                failed += len(rows)
        return {"completed": completed, "failed": failed}
