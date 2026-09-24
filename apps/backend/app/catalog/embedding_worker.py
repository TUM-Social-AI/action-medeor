"""Cloud-job entry point for incremental open-model embeddings."""

from __future__ import annotations

import asyncio
import json

from app.catalog.embedding_factory import create_embedding_provider
from app.catalog.embeddings import CatalogEmbeddingJobService
from app.core.config import get_settings
from app.db.session import async_session


async def run() -> dict[str, object]:
    settings = get_settings()
    provider = create_embedding_provider(settings)
    if provider is None:
        raise RuntimeError("No embedding provider is configured")
    async with async_session() as session:
        service = CatalogEmbeddingJobService(session)
        spec, queued = await service.register_and_activate(provider)
        result = await service.process_pending(
            provider, batch_size=settings.embedding_batch_size
        )
    return {"model": spec.__dict__, "queued": queued, **result}


def main() -> None:
    print(json.dumps(asyncio.run(run()), default=str))


if __name__ == "__main__":
    main()
