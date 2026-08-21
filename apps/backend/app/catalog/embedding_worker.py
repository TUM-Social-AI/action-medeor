"""Cloud-job entry point for incremental open-model embeddings."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.catalog.embeddings import CatalogEmbeddingJobService, SentenceTransformerEmbeddingProvider
from app.db.session import async_session


async def run(model_name: str, revision: str, batch_size: int) -> dict[str, object]:
    provider = SentenceTransformerEmbeddingProvider(model_name, revision=revision)
    async with async_session() as session:
        service = CatalogEmbeddingJobService(session)
        spec, queued = await service.register_and_activate(provider)
        result = await service.process_pending(provider, batch_size=batch_size)
    return {"model": spec.__dict__, "queued": queued, **result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Hugging Face model name")
    parser.add_argument("--revision", default="main", help="Pinned model revision")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.model, args.revision, args.batch_size)), default=str))


if __name__ == "__main__":
    main()
