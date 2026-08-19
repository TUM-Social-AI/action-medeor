# Allocura

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

## Start here: complete Matching V1 operating example

This section is the shortest complete path from an empty database to a testable matching system.
It includes the two real ERP exports; neither file is optional. Keep all real exports outside Git and
use a secure input directory or Azure storage.

### 1. Understand the two ERP files

| File | Role | Important fields used by V1 |
|---|---|---|
| `Artikeldaten.csv` | Product identity, German descriptions, classification and inventory | `Nr.`, `Nummer 2`, descriptions, base unit, category, T1, on-hand stock, confirmed purchase orders, committed orders and replenishment method |
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
change is committed.

With the supplied initial files and no active embedding model, the first response should be similar
to:

```json
{
  "contract_version": "1",
  "status": "completed",
  "idempotent_replay": false,
  "inserted_items": 2773,
  "text_updated_items": 0,
  "metadata_updated_items": 0,
  "unchanged_items": 0,
  "inventory_refreshed_items": 2773,
  "missing_items": 0,
  "reactivated_items": 0,
  "embedding_jobs_created": 0,
  "warnings": []
}
```

The response also contains `import_id` and `completed_at`. Save the complete response as an
operational record. Counts can change when action medeor supplies a newer export.

### 4. Verify the import before continuing

Read one known article:

```bash
curl --fail-with-body http://localhost:8000/api/v1/catalog-items/410001001
```

Check its descriptions, domain, base unit, `matching_eligible`, `source_missing`, `available_raw` and
`fulfillable_quantity`. Then upload the exact same pair again. The second response must contain
`"idempotent_replay": true` and must not duplicate catalogue versions or inventory snapshots.

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
3. Run all three free-first models against the full automatically labelled French set generated from
   the same `Artikeldaten.csv` and `Artikeluebersetzungen.csv` pair.
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

After approval, initialize the catalogue vectors in a cloud worker with database access:

```bash
python -m app.catalog.embedding_worker \
  --model <approved-hugging-face-model> \
  --revision <immutable-model-revision> \
  --batch-size 32
```

The worker registers the model, queues all missing current eligible product versions and writes
normalized vectors to pgvector. It is safe to rerun: completed `(product version, model)` pairs are
not recomputed. A separate decision is still required for where query embeddings run. The standard
web image deliberately excludes PyTorch; until a model-capable runtime or internal embedding service
is connected, matching falls back to exact, lexical and historical retrieval unless the caller sends
`query_embedding` with the matching `embedding_model_id`.

### 7. Register a SharePoint file, hand it to extraction and store the result

The repository does not parse SharePoint documents. A separate read-only Microsoft Graph job must
discover each file and send its stable drive-item ID, version and live URL to:

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

The backend now contains an explainable matching foundation for normalized medicine and medical-
equipment inquiries. It combines exact, lexical, vector, and historical retrieval, applies
conservative versioned constraints, calculates packaging and availability evidence, and stores both
matching runs and subsequent human decisions. Source extraction from Excel, Outlook, SharePoint, or
ERP systems remains outside the matching package. Frontend contracts and a real adapter are prepared,
but the visible application still selects the fixture workflow until extraction integration is ready.

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
  "item_number": "401234567",
  "supplier": "Example supplier",
  "price": "12.50",
  "currency": "EUR"
}
```

The shared external ID connects the file catalogue with its structured result without either service
having to infer identity from a filename.

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
- Business Central master rows with a `000` suffix and no parent article are retained but are not
  offerable and are not embedded. Placeholder rows without a medicine/equipment category are handled
  the same way.
- Available quantity is calculated as `on hand + incoming purchase orders - committed orders`.
  The raw result is preserved even when negative; the fulfillable amount used operationally is
  `max(0, raw result)`. Purchasing inquiries are preserved but not counted as confirmed incoming
  stock.

The supplied files validate as 2,773 articles and 2,879 translations. Of these, 1,645 are currently
offerable variants and 1,124 are master rows. Thirty-one rows have a negative calculated raw
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

Copy `.env.example` to `.env` for Docker Compose overrides.

```bash
cp .env.example .env
```

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

Build the image from the repository root:

```bash
docker build -t allocura .
```

For a local smoke test, start the Compose database and run the image on the Compose network:

```bash
docker compose up -d db
docker run --rm -p 8000:8000 \
  --network allocura_default \
  -e APP_ENV=production \
  -e DATABASE_URL=postgresql+asyncpg://allocura:allocura@db:5432/allocura \
  allocura
```

Open `http://localhost:8000`. The production runtime accepts these environment variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Async SQLAlchemy PostgreSQL URL. Use the externally managed production database. |
| `APP_ENV` | Recommended | Set to `production` to disable automatic local-development CORS behavior. |
| `CORS_ORIGINS` | No | Comma-separated cross-origin frontend URLs. Same-origin production needs none. |
| `EMBEDDING_MODEL_NAME` | No | Approved Sentence Transformers model. Leave empty in the standard web image until benchmarking and the query-inference runtime are complete. |
| `EMBEDDING_MODEL_REVISION` | No | Pinned immutable upstream revision for reproducible query embeddings. Do not use `main` in production. |

`VITE_API_BASE_URL` is a frontend build-time setting for separately hosted local development. The
combined production build deliberately leaves it unset so browser requests use same-origin
`/api/...` URLs.

## Embedding model evaluation

The benchmark under [`benchmarks/embeddings`](benchmarks/embeddings/README.md) compares open,
multilingual models first. It evaluates French ERP descriptions against the offerable catalogue and
can include manually reviewed normalized inquiry labels. It reports Recall@1/3/10, mean reciprocal
rank, runtime, throughput, vector dimensions, and storage. Model downloads and inference require
cloud CPU/GPU time, but there is no per-request model-provider fee for the default open models.

Run the benchmark and the later embedding worker in Azure or another adequately sized cloud runner.
The development laptop has only about 4 GB RAM and is not suitable for loading BGE-M3 or E5-large.
The web container deliberately excludes PyTorch and model weights.

After selecting and pinning a model, the cloud worker can initialize all missing product embeddings:

```bash
python -m app.catalog.embedding_worker \
  --model <approved-hugging-face-model> \
  --revision <immutable-revision>
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
Graph and register changed file metadata through the API; another scheduled or manual process can
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
| 9. Real frontend workflow | Frontend owner replaces the fixture adapter with the real extraction/matching APIs | Validated lines create match runs, explanations render correctly and decisions persist with required override reasons |
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
