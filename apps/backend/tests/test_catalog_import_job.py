import sys
from pathlib import Path

import httpx
import pytest

from app.catalog import embedding_worker
from app.catalog.parser import parse_catalog_files
from app.jobs import import_catalog as import_job
from app.jobs.import_catalog import create_subset, post_import

ARTICLE_HEADER = (
    "Nr.;Nummer 2;Beschreibung;Beschreibung 2;Basiseinheit;Artikelkategoriencode;"
    "Zollware (T1);Lagerbestand;Menge in Bestellung;Menge in Auftrag;"
    "Wiederbeschaffungsverfahren\n"
)
TRANSLATION_HEADER = "Artikelnr.;Sprachcode;Beschreibung;Beschreibung 2\n"


def test_subset_keeps_only_translations_of_selected_articles(tmp_path: Path) -> None:
    articles = tmp_path / "source-articles.csv"
    translations = tmp_path / "source-translations.csv"
    articles.write_text(
        ARTICLE_HEADER
        + "410001001;;Foley catheter CH18;;STÜCK;404;nein;10;0;0;2\n"
        + "410001002;;Foley catheter CH12;;STÜCK;404;nein;20;0;0;2\n",
        encoding="utf-8-sig",
    )
    translations.write_text(
        TRANSLATION_HEADER
        + "410001002;FRS;Sonde CH12;;\n"
        + "410001001;FRS;Sonde CH18;;\n"
        + "410001001;ENU;Catheter CH18;;\n",
        encoding="utf-8-sig",
    )
    output = tmp_path / "shortened"
    output.mkdir()

    article_subset, translation_subset, article_count, translation_count = create_subset(
        articles, translations, 1, output
    )

    assert (article_count, translation_count) == (1, 2)
    parsed = parse_catalog_files(article_subset.read_bytes(), translation_subset.read_bytes())
    assert [item.item_number for item in parsed.items] == ["410001001"]
    assert {translation.raw_language_code for translation in parsed.items[0].translations} == {
        "FRS",
        "ENU",
    }


def test_subset_rejects_invalid_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        create_subset(tmp_path / "articles.csv", tmp_path / "translations.csv", 0, tmp_path)


def test_post_import_uploads_pair_to_catalog_api(tmp_path: Path) -> None:
    articles = tmp_path / "articles.csv"
    translations = tmp_path / "translations.csv"
    articles.write_text(ARTICLE_HEADER, encoding="utf-8")
    translations.write_text(TRANSLATION_HEADER, encoding="utf-8")

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/catalog-imports"
        body = request.read()
        assert b'name="article_data"' in body
        assert b'name="article_translations"' in body
        assert ARTICLE_HEADER.encode() in body
        assert TRANSLATION_HEADER.encode() in body
        return httpx.Response(201, json={"inserted_items": 1})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = post_import(client, "http://localhost:8000/", articles, translations)

    assert result == {"inserted_items": 1}


@pytest.mark.parametrize("skip_embeddings", [False, True])
def test_main_runs_worker_after_successful_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip_embeddings: bool
) -> None:
    articles = tmp_path / "articles.csv"
    translations = tmp_path / "translations.csv"
    articles.write_text(ARTICLE_HEADER, encoding="utf-8")
    translations.write_text(TRANSLATION_HEADER, encoding="utf-8")
    events: list[str] = []

    def fake_post_import(*_: object) -> dict[str, object]:
        events.append("import")
        return {"inserted_items": 1}

    def fake_worker() -> None:
        events.append("worker")

    monkeypatch.setattr(import_job, "post_import", fake_post_import)
    monkeypatch.setattr(import_job, "run_embedding_worker", fake_worker)
    arguments = [
        "import_catalog",
        "--articles",
        str(articles),
        "--translations",
        str(translations),
    ]
    if skip_embeddings:
        arguments.append("--skip-embeddings")
    monkeypatch.setattr(sys, "argv", arguments)

    import_job.main()

    assert events == (["import"] if skip_embeddings else ["import", "worker"])


def test_main_does_not_run_worker_after_failed_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    articles = tmp_path / "articles.csv"
    translations = tmp_path / "translations.csv"
    articles.write_text(ARTICLE_HEADER, encoding="utf-8")
    translations.write_text(TRANSLATION_HEADER, encoding="utf-8")
    worker_called = False

    def failed_import(*_: object) -> dict[str, object]:
        request = httpx.Request("POST", "http://localhost:8000/api/v1/catalog-imports")
        response = httpx.Response(422, text="invalid catalog", request=request)
        raise httpx.HTTPStatusError("invalid catalog", request=request, response=response)

    def fake_worker() -> None:
        nonlocal worker_called
        worker_called = True

    monkeypatch.setattr(import_job, "post_import", failed_import)
    monkeypatch.setattr(import_job, "run_embedding_worker", fake_worker)
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_catalog", "--articles", str(articles), "--translations", str(translations)],
    )

    with pytest.raises(SystemExit) as exit_info:
        import_job.main()

    assert exit_info.value.code == 1
    assert worker_called is False


@pytest.mark.parametrize("failed", [0, 2])
def test_embedding_worker_exits_nonzero_for_failed_jobs(
    monkeypatch: pytest.MonkeyPatch, failed: int
) -> None:
    async def fake_run() -> dict[str, object]:
        return {"queued": 2, "completed": 2 - failed, "failed": failed}

    monkeypatch.setattr(embedding_worker, "run", fake_run)
    if failed:
        with pytest.raises(SystemExit) as exit_info:
            embedding_worker.main()
        assert exit_info.value.code == 1
    else:
        embedding_worker.main()
