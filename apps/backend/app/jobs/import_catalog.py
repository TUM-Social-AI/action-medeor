"""Upload a full or small ERP catalog snapshot through the catalog import API.

Run from apps/backend with ``uv run python -m app.jobs.import_catalog --limit 25``.
The default input files live in the repository's data/ directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from app.catalog.parser import ARTICLE_HEADERS, TRANSLATION_HEADERS

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ARTICLES = REPOSITORY_ROOT / "data" / "Artikeldaten.csv"
DEFAULT_TRANSLATIONS = REPOSITORY_ROOT / "data" / "Artikeluebersetzungen.csv"
DEFAULT_API_URL = "http://localhost:8000"


def _read_header(reader: csv.reader, path: Path, required: set[str]) -> tuple[list[str], int]:
    header = next(reader, None)
    if header is None:
        raise ValueError(f"{path} is empty")
    names = [name.strip() for name in header]
    missing = required - set(names)
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
    identity = "Nr." if "Nr." in required else "Artikelnr."
    return header, names.index(identity)


def create_subset(
    articles: Path, translations: Path, limit: int, destination: Path
) -> tuple[Path, Path, int, int]:
    """Keep the first N nonempty article records and only their translations."""
    if limit < 1:
        raise ValueError("--limit must be at least 1")

    article_subset = destination / "Artikeldaten.csv"
    translation_subset = destination / "Artikeluebersetzungen.csv"
    item_numbers: set[str] = set()
    article_count = 0
    with articles.open(encoding="utf-8-sig", newline="") as source:
        with article_subset.open("w", encoding="utf-8", newline="") as target:
            reader = csv.reader(source, delimiter=";")
            writer = csv.writer(target, delimiter=";")
            header, identity_index = _read_header(reader, articles, ARTICLE_HEADERS)
            writer.writerow(header)
            for row in reader:
                if not any(cell.strip() for cell in row):
                    continue
                writer.writerow(row)
                article_count += 1
                if len(row) > identity_index:
                    item_numbers.add(row[identity_index].strip())
                if article_count == limit:
                    break

    if article_count == 0:
        raise ValueError(f"{articles} contains no article rows")

    translation_count = 0
    with translations.open(encoding="utf-8-sig", newline="") as source:
        with translation_subset.open("w", encoding="utf-8", newline="") as target:
            reader = csv.reader(source, delimiter=";")
            writer = csv.writer(target, delimiter=";")
            header, identity_index = _read_header(reader, translations, TRANSLATION_HEADERS)
            writer.writerow(header)
            for row in reader:
                if len(row) > identity_index and row[identity_index].strip() in item_numbers:
                    writer.writerow(row)
                    translation_count += 1

    return article_subset, translation_subset, article_count, translation_count


def post_import(
    client: httpx.Client, api_url: str, articles: Path, translations: Path
) -> dict[str, object]:
    endpoint = f"{api_url.rstrip('/')}/api/v1/catalog-imports"
    with articles.open("rb") as article_file, translations.open("rb") as translation_file:
        response = client.post(
            endpoint,
            files={
                "article_data": ("Artikeldaten.csv", article_file, "text/csv"),
                "article_translations": (
                    "Artikeluebersetzungen.csv",
                    translation_file,
                    "text/csv",
                ),
            },
        )
    response.raise_for_status()
    return response.json()


def run_embedding_worker() -> None:
    """Process pending catalog vectors with this backend's configured model and database."""
    subprocess.run([sys.executable, "-m", "app.catalog.embedding_worker"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=Path, default=DEFAULT_ARTICLES)
    parser.add_argument("--translations", type=Path, default=DEFAULT_TRANSLATIONS)
    parser.add_argument(
        "--limit", type=int, help="Import only the first N article rows (for a fresh test catalog)"
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("CATALOG_IMPORT_API_URL", DEFAULT_API_URL),
        help="Base URL of the running backend API",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Upload without running the embedding worker (for lexical-only tests)",
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    try:
        with TemporaryDirectory(prefix="allocura-catalog-") as temporary_directory:
            article_path, translation_path = args.articles, args.translations
            if args.limit is not None:
                article_path, translation_path, article_count, translation_count = create_subset(
                    args.articles, args.translations, args.limit, Path(temporary_directory)
                )
                print(f"Uploading {article_count} articles and {translation_count} translations")
            else:
                print(f"Uploading full CSV files: {article_path} and {translation_path}")

            with httpx.Client(timeout=120.0) as client:
                result = post_import(client, args.api_url, article_path, translation_path)

        print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
        if not args.skip_embeddings:
            print("Running embedding worker...", flush=True)
            run_embedding_worker()
    except subprocess.CalledProcessError as exc:
        parser.exit(
            1,
            f"Catalog import succeeded, but embedding worker exited with code "
            f"{exc.returncode}. Check its output above.\n",
        )
    except httpx.HTTPStatusError as exc:
        parser.exit(
            1,
            f"Catalog import failed (HTTP {exc.response.status_code}): "
            f"{exc.response.text}\n",
        )
    except (OSError, UnicodeError, csv.Error, ValueError, httpx.HTTPError) as exc:
        parser.exit(1, f"Catalog import failed: {exc}\n")


if __name__ == "__main__":
    main()
