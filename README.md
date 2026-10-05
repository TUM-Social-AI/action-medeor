<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apps/frontend/public/brand/allocura-wordmark-dark.svg" />
    <img src="apps/frontend/public/brand/allocura-wordmark.svg" alt="Allocura" width="320" />
  </picture>
</p>

Full-stack monorepo for the Allocura procurement-matching prototype. Matching V1 now includes the
versioned PostgreSQL data model, repeatable ERP CSV synchronization, SharePoint-offer handoff,
incremental embedding jobs, and an explainable matching API. Source-document extraction remains a
separate workstream.

## Stack

- Frontend: Vite, React, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, SQLAlchemy asyncio
- Package managers: pnpm for frontend workspaces, uv for Python
- Local runtime: Docker Compose with separate frontend, backend, and Postgres services
- Production runtime: one FastAPI/Uvicorn container serving the compiled React application

## Project Layout

```text
apps/
  frontend/   Vite React app
  backend/    FastAPI app managed with uv
docker-compose.yml
Dockerfile
pnpm-workspace.yaml
```

## Local Development

Backend:

```bash
cd apps/backend
uv sync
uv run uvicorn app.main:app --reload
```

Frontend:

```bash
corepack enable
pnpm install
pnpm --filter @allocura/frontend dev
```

Database only for local development:

```bash
docker compose up -d db
cd apps/backend
uv run alembic upgrade head
```
This starts only Postgres on `localhost:5432`. When running the backend directly on your machine, use:
```bash
DATABASE_URL=postgresql+asyncpg://allocura:allocura@localhost:5432/allocura
```

Docker:

```bash
docker compose up --build
```

The database service uses PostgreSQL 16 with the pgvector extension and remains available as
`allocura` on `localhost:5432`. When running the backend directly on your machine, use:

```bash
DATABASE_URL=postgresql+asyncpg://allocura:allocura@localhost:5432/allocura
```

The frontend runs at `http://localhost:3000`, and the backend runs at `http://localhost:8000`.
FastAPI docs are available at `http://localhost:8000/docs`.

### Restore a database dump locally

From the repository root (overwrites local `allocura`; password: `allocura`):

```bash
docker compose stop backend
docker compose up -d db
docker compose exec -T db dropdb -U allocura --force --if-exists allocura
docker compose exec -T db createdb -U allocura -T template0 allocura
pg_restore -h localhost -U allocura -d allocura --no-owner --no-acl --exit-on-error /path/to/allocura-azure.dump
```

The dump includes embeddings. Set `DATABASE_URL=postgresql+asyncpg://allocura:allocura@localhost:5432/allocura`
for the local backend.

## Local Foundry extraction

For a backend started directly with uvicorn, use `apps/backend/.env.example` as a
template for the ignored `apps/backend/.env` file. Add these settings if they are missing:

```dotenv
LLM_PROVIDER=azure_openai
AZURE_OPENAI_DEPLOYMENT=<exact chat deployment name in Foundry>
```

The backend reuses `AZURE_FOUNDRY_ENDPOINT` and `AZURE_FOUNDRY_API_KEY` from the embedding
configuration. `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY` are optional overrides if
extraction uses another resource. The deployment name may differ from the model name
`gpt-6-luna`; no extraction model version or vector dimensions are needed.

Restart the backend after editing its `.env`, then upload a Word document in the app and review
the extracted items. Word documents use the configured LLM; spreadsheets are primarily parsed
with column rules. An upload can still produce items through basic parsing if an LLM call fails,
so an app upload alone does not prove that Foundry responded. The `import_requests` table stores
`used_llm_fallback` and `parser_warnings` for that check.

The example file is never loaded automatically. Docker Compose reads a separate root `.env`
if one exists, or uses exported environment variables and its defaults. The production Azure
Container App receives its settings as runtime environment variables and secret references.

## Start here: complete Matching V1 operating example

This section is the shortest complete path from an empty database to a testable matching system.
It includes the two real ERP exports; neither file is optional. Keep all real exports outside Git and
use a secure input directory or Azure storage.

### 1. Understand the two ERP files

| File | Role | Important fields used by V1 |
|---|---|---|
| `Artikeldaten.csv` | Product identity, German descriptions, classification and inventory | `Nr.`, `Nummer 2`, descriptions, base unit, category, T1, inventory quantities, replenishment method, `Gesperrt`, `Verkauf gesperrt`, `Einkauf gesperrt` |
| `Artikeluebersetzungen.csv` | Additional multilingual product text joined to the article number | `Artikelnr.`, language code and both description columns |

Both files must be UTF-8, semicolon-separated CSVs with the expected Business Central headers. The
translation file enriches the article text used for lexical and vector retrieval; it does not create
independent products. `Nr.` from `Artikeldaten.csv` remains the durable product identity. Parsing and
validation live in
[`apps/backend/app/catalog/parser.py`](apps/backend/app/catalog/parser.py), while the atomic database
update rules live in
[`apps/backend/app/catalog/service.py`](apps/backend/app/catalog/service.py).

### 2. Create the schema before importing data

For a local or staging database:

```bash
docker compose up -d db
cd apps/backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

`alembic upgrade head` creates tables and the pgvector extension; it never reads private CSV files.
The schema is defined by the migrations under
[`apps/backend/migrations/versions`](apps/backend/migrations/versions).

### 3. Upload `Artikeldaten.csv` and `Artikeluebersetzungen.csv` together

For a local test using the files already in `data/`, run the catalog upload job from
`apps/backend` while the API is running:

```bash
uv run python -m app.jobs.import_catalog --limit 25
```

`--limit` selects the first 25 nonempty article rows and includes every translation for those
articles. The job writes temporary CSVs and deletes them after the API request. Override the input
paths with `--articles` and `--translations`, and the server with `--api-url` (default:
`http://localhost:8000`). Omit `--limit` to upload both complete, unchanged files, as a scheduled
job should do:

```bash
uv run python -m app.jobs.import_catalog
```

After a successful upload, the job runs `python -m app.catalog.embedding_worker`. Configure the
embedding provider and `DATABASE_URL` in `apps/backend/.env` before running it; the worker must use
the same database as the API. If the worker fails, the command exits with an error, but the catalog
import has already succeeded and can be retried safely. For a lexical-only test without a configured
model, pass `--skip-embeddings`.

Run a limited import against a fresh test database. The catalog API treats every upload as a complete
snapshot: omitted articles in a later upload are marked missing, or a large drop is rejected. The API
already compares article identity and text versions, refreshes inventory quantities, and queues
embeddings only for new or text-changed eligible versions with an active model. The worker also
backfills missing embeddings on its first run. The web backend also drains durable catalogue
embedding jobs automatically using the configured provider and active model; it does not switch an
existing active model. The import CLI defaults to `Artikeldaten (2).csv` and
`Artikeluebersetzungen (2).csv`, which contain the current export format. Older files without the
three restriction columns cannot be uploaded; previously imported database records remain usable.

The Article Catalogue has a separate **Update ERP catalogue** upload dialog with import summaries
and real embedding progress. **Fetch new data** remains reserved for future SharePoint updates.
See [the catalogue documentation](docs/article-catalogue.md) for restriction rules and progress.

The easiest manual method is `http://localhost:8000/docs`: open
`POST /api/v1/catalog-imports`, choose **Try it out**, select both files in their matching form fields
and execute the request.

The equivalent command is:

```bash
curl --fail-with-body -X POST http://localhost:8000/api/v1/catalog-imports \
  -F article_data=@/secure-input/Artikeldaten.csv \
  -F article_translations=@/secure-input/Artikeluebersetzungen.csv \
  -F captured_at=2026-08-19T10:00:00Z \
  -F source_uri=business-central://catalog-export/2026-08-19
```

Each file is limited to 25 MB. The endpoint is implemented in
[`apps/backend/app/catalog/api.py`](apps/backend/app/catalog/api.py). The import is transactional,
serialized and checksum-idempotent: either both files are accepted as one snapshot or no catalogue
change is committed. Only an immediate repeat of the currently applied file pair is an idempotent
replay. If contents change from A to B and later back to A, the final A is deliberately applied as a
new audited import so catalogue and inventory state really return to A.

With the supplied current `(2)` exports and no active embedding model, the first response is similar
to:

```json
{
  "contract_version": "1",
  "catalog_snapshot_id": "6c2c36db-690c-4b27-b6e9-b62e0bd32c3b",
  "status": "completed",
  "idempotent_replay": false,
  "inserted_items": 3576,
  "text_updated_items": 0,
  "metadata_updated_items": 0,
  "unchanged_items": 0,
  "inventory_refreshed_items": 3576,
  "missing_items": 0,
  "reactivated_items": 0,
  "embedding_jobs_created": 0,
  "warnings": []
}
```

The response also contains `import_id`, `catalog_snapshot_id` and `completed_at`. Save the complete
response as an operational record. `catalog_snapshot_id` is the value that can later pin a match run
to this exact catalogue/inventory/vector source version. Counts can change when action medeor
supplies a newer export.

### 4. Verify the import before continuing

Read one known article:

```bash
curl --fail-with-body http://localhost:8000/api/v1/catalog-items/410001001
```

Check its descriptions, domain, base unit, `matching_eligible`, `source_missing`, `available_raw` and
`fulfillable_quantity`. Then upload the exact same pair again. The second response must contain
`"idempotent_replay": true` and must not duplicate catalogue versions or inventory snapshots.

Imports and catalogue/inventory versions use database-generated monotonic sequence numbers. This
makes “latest” deterministic even when two exports have the same `captured_at` timestamp; UUIDs are
identifiers only and are never used as chronological tie-breakers.

For the supplied files, the parser found 2,773 articles, 2,879 translations, 1,645 offerable variants,
1,124 master rows and 31 negative raw availability values. Investigate unexpected differences before
activating matching.

### 5. Understand every later ERP update

Always upload a fresh pair from the same ERP reporting time. Never combine old article data with a new
translation export. The response tells the operator what happened:

| Response field | Meaning and required check |
|---|---|
| `inserted_items` | New article numbers were added; eligible new versions need embeddings after a model is active |
| `text_updated_items` | Description, translation, category or base-unit text changed; a new immutable text version and embedding job are created |
| `metadata_updated_items` | Non-text metadata changed; the version is audited and an identical vector can be reused |
| `inventory_refreshed_items` | A current inventory snapshot was written for every article in the accepted report |
| `missing_items` | Previously known article numbers were absent for the first time and are immediately excluded from matching, not deleted |
| `reactivated_items` | Previously missing article numbers reappeared and became current again |
| `embedding_jobs_created` | New current text versions are waiting for the approved active model worker |

Quantity-only changes never trigger paid/model computation. A report with less than half of the
previous article count is rejected as probably truncated. Operators must still investigate any
unusually large `missing_items` count.

### 6. Test embeddings before activating any model

**Embedding evaluation is still mandatory work. The existence of pgvector and an embedding worker
does not mean a model has been selected or proven suitable.** Do not set a production model name and
do not describe semantic matching as validated until all of these gates pass:

1. Build the separate benchmark image from
   [`benchmarks/embeddings/Dockerfile`](benchmarks/embeddings/Dockerfile).
2. Run a small cloud smoke test, for example with `--limit-queries 25`, to verify file mounting,
   model download and report output.
3. Run both configured Foundry embedding deployments against the full automatically labelled French
   set generated from the same `Artikeldaten.csv` and `Artikeluebersetzungen.csv` pair.
4. Add manually reviewed, normalized real inquiry examples with an agreed correct article number and
   run the comparison again.
5. Compare Recall@1/3/10, MRR, latency, throughput, vector size and actual Azure compute cost.
6. Manually review failures involving active ingredient, strength, dosage form, size, sterility,
   packaging and medicine/equipment domain. Aggregate score alone is not an acceptance criterion.
7. Record the decision, verify model licence/privacy requirements and pin one immutable upstream
   revision. Never activate `main` as the production revision.
8. Run the embedding worker in staging, verify completed/failed job counts and execute known matching
   cases before approving production use.

The exact commands, label format, report fields and acceptance checklist are documented in the
[`embedding benchmark README`](benchmarks/embeddings/README.md). The benchmark logic lives in
[`benchmarks/embeddings/run.py`](benchmarks/embeddings/run.py); shared model formatting and the durable
worker live in
[`apps/backend/app/catalog/embeddings.py`](apps/backend/app/catalog/embeddings.py) and
[`apps/backend/app/catalog/embedding_worker.py`](apps/backend/app/catalog/embedding_worker.py).

After approval, configure the selected provider through the embedding environment variables and
initialize the catalogue vectors in a cloud worker with database access:

```bash
python -m app.catalog.embedding_worker
```

The worker registers the model, queues all missing current eligible product versions and writes
normalized vectors to pgvector. It is safe to rerun: completed `(product version, model)` pairs are
not recomputed. A separate decision is still required for where query embeddings run. The standard
web image deliberately excludes PyTorch; until a model-capable runtime or internal embedding service
is connected, matching falls back to exact, lexical and historical retrieval unless the caller sends
`query_embedding` with the matching `embedding_model_id`.

### 7. Register a SharePoint file, hand it to extraction and store the result

The repository does not yet parse SharePoint documents. The read-only Microsoft Graph job below
discovers each file and records its stable drive-item ID, version and live URL through the same
service exposed at:

```text
PUT /api/v1/sharepoint-offer-files/{graph-drive-item-id}
```

The extraction workstream requests its queue with:

```text
GET /api/v1/sharepoint-offer-files?needs_extraction=true
```

After extraction, it writes normalized output using the same external ID:

```text
PUT /api/v1/offers/{same-graph-drive-item-id}
```

File metadata behavior is implemented in
[`apps/backend/app/offers/files.py`](apps/backend/app/offers/files.py); normalized offer versioning is
implemented in [`apps/backend/app/offers/service.py`](apps/backend/app/offers/service.py); both HTTP
boundaries are in [`apps/backend/app/offers/api.py`](apps/backend/app/offers/api.py).

### Run the SharePoint folder sync job

The scheduled job now connects SharePoint discovery, Luna extraction, normalized offer storage,
offer embeddings and Smart Matching. Its processing switch defaults to **disabled**. See the
[operational runbook](docs/sharepoint-offer-pipeline.md) for configuration, retry procedures,
one-document validation and the remaining production gates.

Configure the Graph credentials, drive/root IDs and explicit domain-folder IDs from
`apps/backend/.env.example`. At least one domain folder must be configured; medication can stay
empty until uploaded. Configured domain folders must be immediate children of the permitted root.
Partner-request example folders are excluded from offer processing. Only `.xlsx`, `.xls` and
selectable-text `.pdf` files are eligible; `.eml`, Office temporary files and other formats are skipped.

From `apps/backend`:

```bash
uv run alembic upgrade head
uv run python -m app.jobs.sharepoint_sync inspect
uv run python -m app.jobs.sharepoint_sync inspect --folder-id FOLDER_ID
uv run python -m app.jobs.sharepoint_sync process-one --item-id DOCUMENT_ID --output ../../data/sharepoint-validation/one.json
uv run python -m app.jobs.sharepoint_sync sync
```

`inspect` lists one folder's immediate children without downloading; use `--folder-id` with a
folder ID from its output to browse deeper within the configured root. `process-one` checks a
selected document's ancestry, extracts and persists all supplier/item alternatives, embeds only
that file's eligible offers, and records a real matching check. Repeating unchanged completed work
skips another download/extraction and document-embedding call. It does not advance the discovery
cursor or reconcile other files. `--retry-failed` explicitly resets this file's failed jobs.
The JSON report lists each direct offer-repository write and its payload. It also reports zero
Catalog API HTTP calls, since this job uses the same database services as the API. A successfully
extracted document with no offers exits successfully, reports `no_offers_detected: true`, and skips
offer embedding and matching. See the runbook for Azure one-file execution and report details.

`sync` runs once and exits; retain that command in the existing scheduled Azure Container Apps
Job using the updated backend image. It commits complete discovery and durable pending work
before processing. With `SHAREPOINT_PROCESSING_ENABLED=false`, it performs metadata discovery
only. When enabled, the default processing limit is one document per run. Embedding failures retry
independently and never activate/requeue the ERP catalog model. Expired quotes remain searchable
supplier history with unconfirmed availability.

Missing offer dates use SharePoint file creation, with an estimate label. Relative validity is
calculated afterward from the resolved offer date; original validity wording, price amounts and
price bases remain preserved. Ambiguous periods remain unresolved. Successful empty extraction
batches count as processed, and incomplete extraction never replaces prior successful offers.

The older `test` command performs recursive metadata discovery and one eligible download;
`offer-smoke` performs one HTTP PUT with mock fields to test the public single-offer boundary.
They are distinct from the real `process-one` pipeline, and mock offers are excluded from matching.
For purely local experiments, see the [extraction benchmark](benchmarks/offer-extraction/README.md).

The job tries `GET /v1.0/drives/{drive_id}/items/{folder_id}/delta` on its first sync. If Graph
rejects or does not support this folder-scoped operation, it logs the endpoint, status, Graph code,
message, and response, then uses recursive `children` listing for the configured folder. Microsoft
currently documents `Files.Read.All` as the least privileged **application** permission for the
[driveItem delta endpoint](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0);
this job does not request it or any site-wide permission. A 403 on folder metadata, listing, or
file content fails the run with a selected-folder permission error. This behavior lets the live
`Files.SelectedOperations.Selected` grant determine which operations actually work.

### 8. Run and record a match

Once an external extraction has produced a validated `InquiryLineV1`, send it to
`POST /api/v1/match-runs`. Review the returned evidence, constraints, packaging and availability; then
store the employee's explicit choice through `POST /api/v1/match-decisions`. A complete worked Foley
catheter example is available in the matching [overview](apps/backend/app/matching/README.md), with
the full architecture in the [detailed walkthrough](apps/backend/app/matching/README_DETAILED.md).

### Code map for the new Matching V1 functions

| Function | Main implementation |
|---|---|
| ERP upload and response | [`apps/backend/app/catalog/api.py`](apps/backend/app/catalog/api.py), [`contracts.py`](apps/backend/app/catalog/contracts.py) |
| CSV validation and canonical text | [`apps/backend/app/catalog/parser.py`](apps/backend/app/catalog/parser.py) |
| Atomic first load and incremental updates | [`apps/backend/app/catalog/service.py`](apps/backend/app/catalog/service.py) |
| Embedding model adapter and durable jobs | [`apps/backend/app/catalog/embeddings.py`](apps/backend/app/catalog/embeddings.py), [`embedding_worker.py`](apps/backend/app/catalog/embedding_worker.py) |
| SharePoint metadata and normalized offers | [`apps/backend/app/offers`](apps/backend/app/offers) |
| Retrieval, rules, ranking and decisions | [`apps/backend/app/matching`](apps/backend/app/matching) |
| Database tables | [`apps/backend/migrations/versions`](apps/backend/migrations/versions) |
| Cloud model comparison | [`benchmarks/embeddings`](benchmarks/embeddings) |
| Frontend transport contracts | [`apps/frontend/src/api`](apps/frontend/src/api) |

## Product Matching

The backend contains an explainable matching engine for normalized medicine and equipment
inquiries. It combines exact, lexical, vector, and historical retrieval, applies versioned
constraints, calculates packaging and availability evidence, and stores match runs and human
decisions. Request Workflow opens the import screen without saving a row; submitting a file
creates the saved request and extracts its contents. Empty drafts from older clients are hidden
from request history. Extraction
suggests medicine or equipment from an explicit type column, specific units or item names; the
LLM extraction path returns a type too. Ambiguous lines need a manual choice. Once every line
is verified and classified, the UI queues matching for all lines. The backend worker runs while
the API is running and recovers expired jobs after a restart. Results, progress, and selections
remain available when the browser is closed or refreshed. Completed lines can be selected
while the worker processes other lines. The worker saves a default
selection when the top article has the exact requested article number, or its text similarity is
at least 0.78 with compatible numbers and product form. The UI shows the numeric ranking
score calculated from the matching criteria before candidates are sorted. It preserves
the lexicographic priority order and is normalized to 0–100 within each requested item:
the best available candidate scores 100. It is not a calibrated confidence percentage. Name similarity and retrieval evidence remain available
in candidate details. Other items wait for a person. Alternative
selections do not require a reason; saved decisions are retained for later offline evaluation and
do not update live ranking. Opening the summary explicitly finalizes the request. Finalized requests
open at the summary from history; returning to matching clears that final state while retaining the
decisions. Pricing and offer creation are not available in this workflow.

Apply the current migrations with `uv run alembic upgrade head` before using this workflow.
Requests can also start with **Create request manually**, which opens an empty review without
uploading or extracting a file. **Add item manually** is available below the review table for
both manual and uploaded requests. Manual items require a name, positive whole-number quantity,
and Medicine/Equipment type; they are saved as verified, marked **Manual**, and can be edited or
removed until matching starts. Manual requests remain available in request history.

Import a catalog first through `POST /api/v1/catalog-imports` or the catalog import job. The
catalog snapshot is fixed when request matching starts. If `EMBEDDING_PROVIDER` is configured,
the matching worker generates query embeddings and includes vector retrieval; with the setting
empty, exact and lexical retrieval still run.

```text
POST /api/requests                        create draft, or {"mode":"manual"} for review
POST /api/requests/{id}/file              upload and extract
GET  /api/requests                        list saved requests
GET  /api/requests/{id}/review            reopen extraction and review
POST /api/requests/{id}/items             add a verified manual item
DELETE /api/requests/{id}/items/{item}    remove a manual item during review
POST /api/requests/{id}/matching          queue or retry matching
GET  /api/requests/{id}/matching          progress, candidates, decisions
POST /api/requests/{id}/matching/auto-select  apply saved defaults to older runs
POST /api/requests/{id}/items/{item}/decision
POST /api/requests/{id}/finalize          save final summary state
POST /api/requests/{id}/reopen-matching   return to matching with saved decisions
GET  /api/requests/{id}/summary
```

The standalone matching API remains available:

```text
POST /api/v1/match-runs
GET  /api/v1/match-runs/{match_run_id}
POST /api/v1/match-decisions
```

## Matching V1 data flow

```mermaid
flowchart LR
    ERP["Business Central CSV exports"] --> CI["Catalog import API"]
    CI --> DB["PostgreSQL 16 + pgvector"]
    GS["Read-only Graph sync<br/>(separate scheduled job)"] --> SF["SharePoint file API"]
    SF --> DB
    SF --> EX["External extraction workstream"]
    EX --> OF["Normalized offer API"]
    OF --> DB
    DB --> M["Matching API"]
    BM["Cloud embedding benchmark"] --> W["Selected model + embedding worker"]
    W --> DB
```

The backend exposes these V1 boundaries:

```text
POST /api/v1/catalog-imports
GET  /api/v1/catalog-imports/{import_id}
GET  /api/v1/catalog-items/{item_number}

PUT  /api/v1/sharepoint-offer-files/{external_id}
GET  /api/v1/sharepoint-offer-files?needs_extraction=true
POST /api/v1/sharepoint-offer-files/{external_id}/archive

PUT  /api/v1/offers/{external_id}
GET  /api/v1/offers
POST /api/v1/offers/{external_id}/archive
```

`sharepoint-offer-files` contains only file metadata and the live SharePoint URL. A read-only
Microsoft Graph synchronization job supplies it. The separate extraction workstream can request only
files without structured output and subsequently send normalized results to `offers`. This repository
does not parse SharePoint documents.

Example handoffs:

```bash
curl -X POST http://localhost:8000/api/v1/catalog-imports \
  -F article_data=@Artikeldaten.csv \
  -F article_translations=@Artikeluebersetzungen.csv
```

```text
PUT /api/v1/sharepoint-offer-files/{graph-drive-item-id}
{
  "source_version": "graph-etag-or-ctag",
  "source_url": "https://medeor.sharepoint.com/sites/TheLabworks/.../offer.xlsx",
  "name": "offer.xlsx",
  "captured_at": "2026-08-19T10:00:00Z",
  "modified_at": "2026-08-18T15:42:00Z",
  "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "size_bytes": 123456
}
```

```text
PUT /api/v1/offers/{same-graph-drive-item-id}
{
  "source_version": "graph-etag-or-extraction-version",
  "source_url": "https://medeor.sharepoint.com/sites/TheLabworks/.../offer.xlsx",
  "captured_at": "2026-08-19T10:10:00Z",
  "raw_request_text": "Sterile Foley catheter CH18, 50 pieces",
  "offered_description": "Sterile Foley catheter CH18",
  "supplier": "Example supplier",
  "currency": "EUR",
  "unit_price": "0.42",
  "unit_price_unit": "piece",
  "valid_until": "2026-12-31"
}
```

The shared external ID connects the file catalogue with its structured result without either service
having to infer identity from a filename.

To check a supplier offer that is absent from the ERP catalog, submit it through
`PUT /api/v1/offers/{id}` and omit `item_number`. Use the real SharePoint document URL,
`offered_description`, and text that overlaps the requested item. The file metadata endpoint
is optional for this manual check and does not feed matching on its own. Run matching again:
the offer appears as a separate candidate with **Offer from SharePoint** and an **Open document**
link. It can be selected without an ERP SKU. Its product attributes and stock need human review.
Standalone offers currently use text retrieval, not offer embeddings. A matching offer retains one
slot in the returned suggestions even when catalog articles fill the other slots. Optional
`valid_until` is an ISO date (`YYYY-MM-DD`); expired offers are excluded from new matches.
Optional `unit_price` requires `unit_price_unit` and `currency`, and is displayed as a per-unit
quote without assuming a total order value. To revise an existing offer, send a new
`source_version`; replaying the same version leaves the saved fields unchanged. Older saved
match runs need a new run to include updated offer details.

### ERP import behavior

Upload `Artikeldaten.csv` and `Artikeluebersetzungen.csv` together as multipart form fields
`article_data` and `article_translations`. The import is all-or-nothing, checksum-idempotent, and
serialized so two imports cannot overlap.

- Article number is the durable product identity.
- Quantity-only changes create a new inventory snapshot but no product-text version or embedding.
- Description, translation, category, or base-unit changes create a new immutable text version and
  queue an embedding for every active model. The previous version remains available for audit.
- Non-text metadata changes such as replenishment method or T1 also create an auditable product
  version, but reuse the identical stored vectors instead of paying to run the model again.
- A missing article number is flagged `source_missing` on its first absence and excluded from matching;
  it is not deleted. Reappearance clears that flag.
- A report containing less than half of the previously known article numbers is rejected as probably
  truncated, preventing one broken export from flagging most of the catalogue as missing.
- Business Central master rows with a `00` suffix and no parent article are retained but are not
  offerable and are not embedded. Placeholder rows without a medicine/equipment category are handled
  the same way.
- Available quantity is calculated as `Lagerbestand - Menge in Bestellung + Menge in Auftrag`
  (`on_hand - incoming_purchase_order + committed_order`).
  The raw result is preserved even when negative; the fulfillable amount used operationally is
  `max(0, raw result)`. Purchasing inquiries are preserved but not counted as confirmed incoming
  stock.

The current `(2)` exports validate as 3,576 articles and 3,816 translations. Of these, 2,141 are
classified non-master variants before applying ERP restrictions, and 1,430 are master rows.
Seventy-seven rows have a negative calculated raw
availability, which is why the value is clamped only at the point where a promiseable quantity is
needed.

### Why a text hash exists

The SHA-256 content hash is a fingerprint of the normalized text that was embedded, not the product's
identity. If the description changes but the article number stays the same, the importer keeps the
same product, stores a new text version, and creates a new embedding job. The old text and vector stay
attached to the old version for audit and are no longer selected as the current version. An item is
only considered missing when its article number disappears from a complete valid report.

See the matching [overview](apps/backend/app/matching/README.md) and
[detailed architecture](apps/backend/app/matching/README_DETAILED.md). Complete German versions are
available for the [overview](apps/backend/app/matching/README_DE.md) and
[detailed architecture](apps/backend/app/matching/README_DETAILED_DE.md).

## Environment

For a local backend, keep `apps/backend/.env` beside `apps/backend/.env.example`.
If no local backend `.env` exists yet, create it from the example and fill in the private
database URL, Foundry endpoint, and API key. Docker Compose uses its own defaults or a
separate root `.env` for overrides; Azure Container Apps uses runtime settings and secrets.

The first database target is PostgreSQL with pgvector so local Docker and deployment use the same
shape. The backend keeps the database behind `DATABASE_URL`, so it can be swapped later.

### Where the database is implemented

The database is not a CSV file and is not stored inside the frontend. Its schema is created by the
Alembic migrations in [`apps/backend/migrations/versions`](apps/backend/migrations/versions), and all
runtime access goes through the backend services under [`apps/backend/app`](apps/backend/app).

The main groups are:

| Tables | Purpose |
|---|---|
| `source_snapshots`, `catalog_imports` | Checksums, provenance, and repeatable import audit |
| `catalog_items`, `catalog_item_versions`, `catalog_item_translations` | Stable article identity and immutable text versions |
| `inventory_snapshots` | A new quantity snapshot for every changed CSV pair |
| `embedding_models`, `product_embeddings`, `catalog_embedding_jobs` | Model registry, version-bound vectors, and durable incremental work |
| `sharepoint_offer_files`, `historical_offers` | Live source links and separately normalized structured offer evidence |
| `match_runs`, `match_candidates`, `match_decisions` | Reproducible suggestions and human decisions |

When a match request supplies the `catalog_snapshot_id` returned by the import, product text, its
corresponding inventory snapshot, and pgvector retrieval are all pinned to that same snapshot.
Without it, all three use the latest database sequence. This prevents a historical product
description from being ranked with current stock or current embeddings.

Locally, Docker Compose keeps PostgreSQL data in the named `postgres-data` volume (normally shown by
Docker as `allocura_postgres-data`). In Azure,
`DATABASE_URL` must point to a separately managed PostgreSQL service with pgvector enabled; rebuilding
or replacing the application container must not delete the database. Run `alembic upgrade head` as a
deployment step before serving the new application version.

## Combined Production Container

The production image builds the React frontend and copies it into the FastAPI runtime. Uvicorn
serves both applications on port `8000`:

```text
/        React application and client-side routes
/api/*   FastAPI endpoints
```

### Signed-in user in Azure Container Apps

The sidebar and home greeting read `/api/me`. Locally it returns `Local User`; in Azure,
Container Apps built-in authentication supplies the signed-in user's name through its trusted
`X-MS-CLIENT-PRINCIPAL` claims or `X-MS-CLIENT-PRINCIPAL-NAME` header. Do not expose the
container directly around the Container Apps authentication layer: these headers are only
trusted when that layer controls the public ingress.

For the existing `allocura-app-auth` app registration, configure the Container App's
**Security > Authentication** to use Microsoft Entra ID and **Require authentication**,
redirecting unauthenticated browser requests to Microsoft. The app registration needs a
Web redirect URI of `<app-url>/.auth/login/aad/callback` and ID tokens enabled. The
name works without Microsoft Graph access.

The profile avatar is one of six bundled animal illustrations. A stable hash of the Entra
user ID assigns an initial avatar; users can choose another from the profile popup in the
sidebar. The selected avatar is stored in `user_avatar_preferences`, so it follows the user
across browsers and devices.
Run `alembic upgrade head` before deploying this version. Neither Microsoft Graph
permissions nor a Container Apps token store are needed for avatars.

## Embedding model evaluation

The benchmark under [`benchmarks/embeddings`](benchmarks/embeddings/README.md) compares Azure OpenAI
embedding deployments in Foundry. It evaluates French ERP descriptions against the offerable
catalogue and can include manually reviewed normalized inquiry labels. It reports Recall@1/3/10,
mean reciprocal rank, runtime, throughput, vector dimensions, token usage and storage.

The lightweight benchmark image calls Foundry remotely and deliberately excludes Sentence
Transformers, PyTorch and local model weights. Optional open-model comparisons require a separate
model-enabled environment.

After selecting and pinning a model, configure the provider as shown in
[`benchmarks/embeddings/README.md`](benchmarks/embeddings/README.md). The cloud worker can then
initialize all missing product embeddings:

```bash
python -m app.catalog.embedding_worker
```

Later catalog imports automatically queue only new or text-changed offerable versions. Inventory-only
updates do not run the model again.

## API routes and scheduled jobs in plain language

An API route is a named HTTP input/output contract. It is useful here because the React frontend,
scheduled Azure jobs, extraction service, tests, and future integrations can all call the same
validated operation without direct database access. This keeps credentials and database rules inside
the backend.

A cron job is simply a task triggered on a schedule. No always-running cron process is embedded in
the web application. In Azure, a scheduled job should periodically read SharePoint through Microsoft
Graph and register changed file metadata and normalized offers using the shared database services; another scheduled or manual process can
upload the latest ERP CSV pair. Separating scheduled work from the web container makes retries,
credentials, and failures observable and prevents a long sync from blocking user requests.

## Roadmap from merged code to operational Matching V1

The code foundation and production rollout are separate milestones. Complete these phases in order:

| Phase | Owner/work | Verification and exit criterion |
|---|---|---|
| 1. Review and merge | Backend/database, frontend-contract and Azure reviewers inspect the PR; CI runs PostgreSQL/pgvector integration tests and the frontend build | All checks green, review findings resolved and branch merged to `main` |
| 2. Secure staging platform | Azure owner provisions managed PostgreSQL with pgvector, backups, Container App, migration job, secret references and protected/private API access | `alembic upgrade head` succeeds and `/api/health` reports a healthy database without exposing credentials |
| 3. Initial ERP load | Operator uploads the matching `Artikeldaten.csv` and `Artikeluebersetzungen.csv` pair, saves the response and checks representative articles | Counts are plausible, repeat upload is idempotent and missing/negative quantities are reviewed |
| 4. Incremental ERP rehearsal | Operator tests a quantity change, text change, new item, first absence and reappearance in staging | Only text/new eligible versions queue embeddings; inventory and missing/reactivated counts match expectations |
| 5. Embedding evaluation | ML/backend owner runs smoke, full automatic and reviewed-inquiry benchmarks in cloud compute | Failure review completed; model, immutable revision, licence/privacy decision and measured cost are documented |
| 6. Embedding activation | Azure owner runs the worker against staging and chooses a model-capable query-inference boundary | All eligible current versions have compatible vectors; known multilingual matches pass; no failed jobs remain unexplained |
| 7. SharePoint metadata sync | Integration owner deploys a least-privilege read-only Graph job using stable drive-item IDs and live URLs | New/changed/deleted files appear correctly; `needs_extraction=true` returns the intended queue |
| 8. Extraction handoff | Extraction owner reads the queue and publishes normalized offers/inquiry lines without changing matching internals | Same external ID links source file and structured record; malformed payloads fail visibly |
| 9. Real frontend workflow | Frontend owner replaces the fixture adapter with the real extraction/matching APIs | Validated lines create match runs, explanations render correctly and decisions persist, with optional override reasons |
| 10. Production readiness | Team adds authentication/authorization, monitoring, alerts, backup-restore test, operating ownership and rollback procedure | End-to-end acceptance with real examples passes and every scheduled/manual process has an owner and failure response |

Matching V1 must not be called semantically validated at phase 3 merely because products were
imported. It becomes vector-enabled only after phases 5 and 6. It must not be called fully operational
until SharePoint/extraction, the real UI path and production controls have also passed their exit
criteria.

## Publish to Azure Container Registry

`.github/workflows/publish-container.yml` is manual-only and publishes only from `main`. A run
builds `main` and pushes only an immutable commit tag:

```text
<acr-login-server>/allocura:<git-sha>
```

This is the current boundary of the repository's Azure automation: it builds and stores an image in
Azure Container Registry. It does **not** yet create or update the running web application,
PostgreSQL, scheduled Graph/ERP jobs, model worker, network rules, or secrets. A complete environment
will have separate resources with separate lifecycles:

```text
GitHub Actions --OIDC/Entra--> ACR --image--> Azure Container App
                                             |--> managed PostgreSQL + pgvector
                                             |--> scheduled CSV/Graph jobs
                                             `--> on-demand benchmark/embedding jobs
```

Microsoft Entra is the identity system: it proves which user or workload is calling Azure. The tenant
is the organization's identity directory. A subscription is the billing/resource boundary, a
resource group organizes related resources, and ACR stores container images. The web app should use
managed identity or secret references for database/Graph access; credentials must never be committed
to this repository or sent through frontend code.

The names used for this deployment are:

| Resource | Name |
| --- | --- |
| GitHub repository | `TUM-Social-AI/action-medeor` |
| Application and ACR image repository | `allocura` |
| Azure resource group | `rg-allocura` |
| Azure Container Registry resource | `allocura` |

The registry login server may include an additional DNS tenant suffix, so always copy its complete
value from the Azure portal instead of deriving it from the registry resource name.

The workflow definition must exist on the default branch (`main`) before GitHub displays its **Run
workflow** control. Dispatches for any other ref are skipped. This publishes the combined image but
does not deploy or update an Azure Container App.

Configure exactly these non-secret GitHub repository variables under **Settings > Secrets and
variables > Actions > Variables**:

| Variable | Azure portal source |
| --- | --- |
| `AZURE_CLIENT_ID` | App registration **Overview > Application (client) ID** |
| `AZURE_TENANT_ID` | App registration or Microsoft Entra ID **Overview > Directory (tenant) ID** |
| `AZURE_SUBSCRIPTION_ID` | **Subscriptions > target subscription > Overview > Subscription ID** |
| `AZURE_CONTAINER_REGISTRY_NAME` | Existing container registry **Overview > Registry name** |
| `AZURE_CONTAINER_REGISTRY_LOGIN_SERVER` | Existing container registry **Overview > Login server**; copy the complete value, including any DNS tenant suffix |

The workflow uses GitHub OIDC to obtain an AAD access token, exchanges that token directly at the
configured login server's `/oauth2/exchange` endpoint, and passes the resulting short-lived ACR
refresh token to Docker. It does not use a client secret, registry password, long-lived credential,
registry suffix setting, or registry control-plane discovery command.

### OIDC and ABAC prerequisites

The existing registry uses **RBAC Registry + ABAC Repository Permissions**, where the legacy
`AcrPush` role is not honored. Configure the workload identity outside this repository:

1. In **Microsoft Entra ID > App registrations**, create or select a single-tenant application for
   this publisher. Record its application/client and directory/tenant IDs. Do not create a client
   secret.
2. Under **Certificates & secrets > Federated credentials**, add a GitHub Actions credential for
   organization `TUM-Social-AI`, repository `action-medeor`, entity **Branch**, and branch `main`.
   Name it
   `github-allocura-main`. Its exact subject must be
   `repo:TUM-Social-AI/action-medeor:ref:refs/heads/main`.
3. Open the existing ACR resource itself, then **Access control (IAM) > Add role assignment**. At
   this exact ACR resource scope—not the resource group or subscription—assign `Container Registry
   Repository Writer` to the app registration's service principal.
4. In the assignment's **Conditions** editor, select all actions exposed for the Writer role and
   add:
   - Attribute source: `Request`
   - Attribute: `Repository name`
   - Operator: `StringEqualsIgnoreCase`
   - Value: `allocura`
5. Save the generated condition as condition version `2.0`. For CLI-managed assignments, copy the
   Writer-specific expression generated by the portal; do not reuse the Reader-role example from
   the Azure documentation.

`Container Registry Repository Writer` permits publishing and updating the known repository but
does not permit image deletion, catalog listing, or registry management. Do not grant the workload
identity `Container Registry Repository Catalog Lister`, `AcrPush`, Resource Group Contributor,
Owner, or a registry control-plane administrator role. The administrator creating the role
assignment needs separate role-assignment privileges; the publishing identity does not.

After the workflow definition is available on `main`, run **Publish production container** from the
Actions tab with branch `main`. Confirm that the known `allocura` repository contains the
expected `<git-sha>` tag and that the workflow did not add a `latest` tag. Also confirm that this
identity cannot push another repository name, list the registry catalog, delete images, or manage
the ACR resource.
