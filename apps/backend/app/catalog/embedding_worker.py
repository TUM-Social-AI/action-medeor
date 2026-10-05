"""Cloud-job entry point for incremental open-model embeddings."""

from __future__ import annotations

import asyncio
import json
import logging

from app.catalog.embedding_factory import create_embedding_provider
from app.catalog.embeddings import CatalogEmbeddingJobService
from app.core.config import get_settings
from app.db.session import async_session

logger = logging.getLogger(__name__)


async def run_forever() -> None:
    """Drain durable jobs without doing provider work in an upload request."""
    initialized = False
    provider = None
    while True:
        try:
            settings = get_settings()
            if provider is None:
                provider = create_embedding_provider(settings)
            if provider is None:
                return
            async with async_session() as session:
                service = CatalogEmbeddingJobService(session)
                if not initialized:
                    await service.register_and_activate(provider, preserve_active=True)
                    initialized = True
                error = await service.configuration_error(provider)
                if error:
                    raise ValueError(error)
                result = await service.process_pending(
                    provider, batch_size=settings.embedding_batch_size
                )
                if result["failed"]:
                    logger.error("Catalog embedding jobs failed: %s", result["failed"])
        except Exception:
            logger.exception("Catalog embedding worker could not process jobs")
        await asyncio.sleep(5)


async def run() -> dict[str, object]:
    settings = get_settings()
    provider = create_embedding_provider(settings)
    if provider is None:
        raise RuntimeError("No embedding provider is configured")
    async with async_session() as session:
        service = CatalogEmbeddingJobService(session)
        spec, queued = await service.register_and_activate(provider)
        result = await service.process_pending(provider, batch_size=settings.embedding_batch_size)
    return {"model": spec.__dict__, "queued": queued, **result}


def main() -> None:
    result = asyncio.run(run())
    print(json.dumps(result, default=str), flush=True)
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
