# SharePoint supplier-offer pipeline

The backend image's existing `app.jobs.sharepoint_sync sync` command discovers documents,
queues extraction, persists multiple offers per document, and processes supplier-offer embeddings.
It uses the same database services as the API, rather than making HTTP calls to its own backend.
The embedding API is the configured external provider; no new public extraction endpoint is needed.

## Current defaults and folder configuration

`SHAREPOINT_PROCESSING_ENABLED=false` keeps scheduled extraction and embedding work off.
`process-one` is an explicit one-file override. The local equipment folder is configured from
the user's confirmed “Einkaufsanfragen Equipment für Nicht-Lagerware” folder. Medication is
unconfigured until uploaded. Partner-request example folders are excluded from offer processing.

Configure these on the **job**, not just the web container:

| Setting | Purpose/default |
| --- | --- |
| `DATABASE_URL` | Migrated PostgreSQL database with pgvector |
| `SHAREPOINT_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET` | App-only Graph credentials |
| `SHAREPOINT_DRIVE_ID`, `SHAREPOINT_ROOT_FOLDER_ID` | Permitted source root |
| `SHAREPOINT_EQUIPMENT_FOLDER_ID`, `SHAREPOINT_MEDICATION_FOLDER_ID` | Explicit domain folders; at least one required |
| `SHAREPOINT_PROCESSING_ENABLED` | `false` |
| `SHAREPOINT_MAX_DOCUMENTS_PER_RUN` | `1`; embeddings follow the same attempted files, or retry existing pending files when there is no extraction work |
| `SHAREPOINT_MAX_DOCUMENT_BYTES` | `20000000`; streamed download limit |
| `SHAREPOINT_MAX_EXTRACTION_CHUNKS` | `32`; reject excessive input before model calls |
| `SHAREPOINT_DOCUMENT_TIMEOUT_SECONDS` | `600` |
| `SHAREPOINT_MAX_ATTEMPTS` | `3` durable attempts per document/embedding job |
| `LLM_PROVIDER`, `AZURE_OPENAI_DEPLOYMENT` and extraction endpoint/key | Configured Azure Luna deployment |
| Embedding provider/deployment/name/version/dimensions and endpoint/key | Must match the query model; current local configuration is `text-embedding-3-large`, 3072 dimensions |

Configured domain folders must be distinct, immediate child folders of the permitted root.
Nested customer-request folders are provenance only: historical offers are not restricted to that
customer. File formats are `.xlsx`, `.xls` and selectable-text `.pdf`, case-insensitively.
`.eml`, Office `~$` files and unsupported formats are never downloaded by offer processing.
Scanned/empty PDFs and mixed PDFs with unreadable pages are reported as unsupported; OCR is absent.

## One-document check and retries

Run from `apps/backend` after setting configuration:

```bash
uv run alembic upgrade head
uv run python -m app.jobs.sharepoint_sync inspect
uv run python -m app.jobs.sharepoint_sync process-one --item-id DOCUMENT_ID --output ../../data/sharepoint-validation/one.json
```

`inspect` reads immediate root metadata only. `process-one` checks folder ancestry before content
access and again after extraction. It does not crawl other documents, change the discovery cursor,
archive unrelated files or invoke the catalog embedding worker. Repeating a completed unchanged
file skips downloading, extraction and document embedding, but performs a new matching query check.
Empty or entirely review-only batches complete extraction but cannot pass the matching smoke check;
the command exits nonzero and records that reason. Private JSON reports belong under ignored `data/`.

Transient failures are retried with bounded backoff. Unsupported files are not automatically retried.
After fixing a terminal failure, explicitly retry this document:

```bash
uv run python -m app.jobs.sharepoint_sync process-one --item-id DOCUMENT_ID --retry-failed --output ../../data/sharepoint-validation/retry.json
```

This resets only the selected document's failed extraction/embedding jobs. Completed extraction
is retained when only embeddings failed. Content/domain/format changes or a prompt/normalizer
version change queue a fresh extraction. Version changes are checked before accepting results;
leases fence late workers, and failed/partial extraction never replaces previous successful offers.
Timeout cancellation prevents further chunk calls; an already running synchronous SDK call may
finish in its thread, but cannot publish after cancellation or lease expiry.

One complete discovery commits its cursor and pending work before any extraction. Failed discovery
does not reconcile deletions or advance the cursor. Source discovery uses a database advisory lock;
document and embedding work use leased, fenced claims. Metadata snapshot pagination is not an atomic
SharePoint snapshot, so overlapping remote edits can require a subsequent reconciliation run.

## Data interpretation and matching

Document-stated dates take precedence. Otherwise, file `createdDateTime` is the estimated offer
date; missing creation stays unknown. No row-edit history, document-modification fallback or current
time fallback is used. Imports/copies of old quotes can have recent creation timestamps, so the UI
labels this estimate. Relative validity uses the resolved offer date in Europe/Berlin, with calendar
days/weeks/months/years and month-end clamping. Explicit expiry wins. Business days, ambiguous
durations/anchors and unsupported wording remain unresolved; delivery and product expiry are separate.

Quoted prices and explicit bases remain unchanged, including `/100` and pack prices. No per-unit
division is performed. Conflicting prices are retained with a null selected amount. Supplier blocks
and alternatives have separate identities and source evidence. Blank offered-title cells may use
the same row's requested product only when a concrete supplier price/reference supports it; this
fallback is labelled. Missing or unverified supplier/product evidence excludes automatic matching,
while uncertain price/date information remains visible with warnings.

Each successful batch atomically updates its file's current offer set, retains historical versions,
archives removed offers and records successful empty results. Source-file deletion or a move outside
the permitted domain folders archives the linked set. Customer grouping is not a retrieval restriction.

Offer vectors have their own durable jobs and tables. Their text contains product description and
domain, without price/date. Unchanged text/model hashes reuse vectors across offer versions. Model
registration validates provider/name/version/dimensions without activating models or touching ERP
queues. Retrieval fuses relevance-ranked lexical and offer-vector results using the existing query
embedding, filters by domain/current/active/eligible status, and preserves expired offers as supplier
leads. Initial offer-vector search is exact cosine, with a 0.5 minimum similarity; tuning and indexing
need a larger representative sample. Historic offers do not establish current stock or orderability.

## Before a production test or scheduled rollout

- Build and deploy the updated backend/job image and frontend; apply migration `20261002_0001`
  before the new code runs. This repository has no deployment definition for the existing Azure job;
  local validation does not update that deployed job or its schedule.
- Verify the actual job's database target, network access, folder grants, domain IDs and provider
  secrets/quotas. Keep Graph reads restricted to the permitted subtree; no broader grant is required
  by this implementation. Upload/configure medication before testing that domain.
- Verify API authentication/access control, protected database access, secret management, backups
  and restore procedures in the deployed environment. These operational settings cannot be certified
  by local extraction tests.
- Keep processing disabled initially. Run one explicitly selected production document with the
  one-file limit, review source association, original prices/bases, estimated dates and matching output.
  The prompt is now `supplier-offers-v4`; the prior v3 corpus scores do not establish v4 quality.
  Do not run a bulk live validation or automatic benchmark during deployment.
- Configure schedule timeout/concurrency, provider timeout/rate limits and cost limits. Durable job
  attempts and provider transport retries are separate; one worker attempt can make several API
  attempts. Monitor processed/failed/unsupported counts, pending age, expired leases, retry exhaustion,
  embedding coverage and provider latency/cost. Route failures to an owner and test alerts.
- Assess relevance thresholds and exact-vector/lexical query latency on production-sized data before
  increasing throughput; the configured 3072-dimensional vectors need an appropriate indexing design.
- Roll back processing by setting `SHAREPOINT_PROCESSING_ENABLED=false`; retain the additive schema
  and extracted history. Stop active executions when immediate cessation is required. Do not downgrade
  a populated schema as an operational rollback. Take backups before any later data repair/removal.

Useful queue inspection:

```sql
SELECT status, count(*), min(updated_at) AS oldest_update
FROM sharepoint_offer_jobs GROUP BY status;
SELECT status, count(*) FROM offer_embedding_jobs GROUP BY status;
SELECT item_id, status, attempts, error
FROM sharepoint_offer_jobs WHERE status IN ('failed','unsupported');
```

## Local live validation

On 2026-10-02, one 31 KB equipment workbook was downloaded once. The initial v3 extraction exposed
a blank offered-title case. The same cached workbook was checked against its unchanged SharePoint
version and reprocessed with v4: one offer persisted, one 3072-dimensional vector stored, and a real
Smart Matching query returned the supplier. The quoted amount/basis and source cells were reviewed;
missing offer date used labelled file creation, and delivery time did not become offer validity.
Replay made no additional download, extraction or document-embedding call. Processing remains off.
Private evidence/report: `data/sharepoint-validation/equipment-one.json` and `equipment-source.xlsx`.
No full SharePoint sync, corpus benchmark or medication live test was performed.

The complete backend suite passed (241 tests) against a separate migrated local database with
live model credentials disabled. Frontend tests/build and Ruff also passed. For repeat offline
tests, set both `DATABASE_URL` and `MATCHING_TEST_DATABASE_URL` to a dedicated test database,
set `LLM_PROVIDER=anthropic` and `EMBEDDING_PROVIDER=`, and explicitly clear
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY` and `AZURE_FOUNDRY_API_KEY`
in the test process environment so credentials in `.env` cannot activate live fallbacks.
