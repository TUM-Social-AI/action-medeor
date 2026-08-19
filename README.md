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

## Product Matching

The backend now contains an explainable matching foundation for normalized medicine and medical-
equipment inquiries. It combines exact, lexical, vector, and historical retrieval, applies
conservative versioned constraints, calculates packaging and availability evidence, and stores both
matching runs and subsequent human decisions. Source extraction from Excel, Outlook, SharePoint, or
ERP systems remains outside the matching package, and no frontend integration is included yet.

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
| `EMBEDDING_MODEL_NAME` | No | Approved Sentence Transformers model. Leave empty until benchmarking is complete. |
| `EMBEDDING_MODEL_REVISION` | No | Pinned upstream revision for reproducible query embeddings. Do not use `main` in production. |

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
