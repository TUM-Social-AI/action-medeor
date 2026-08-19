# Multilingual embedding benchmark

This is the required evaluation and activation guide for Matching V1 embeddings. The database,
pgvector queries and worker are implemented, but **no embedding model is approved merely because the
code exists**. A model becomes usable only after the smoke test, full catalogue comparison, reviewed
real-inquiry evaluation, failure analysis and immutable revision approval described below.

The benchmark is implemented in [`run.py`](run.py). Model loading and the query/document formatting
shared with production live in
[`../../apps/backend/app/catalog/embeddings.py`](../../apps/backend/app/catalog/embeddings.py). The
production indexing entry point is
[`../../apps/backend/app/catalog/embedding_worker.py`](../../apps/backend/app/catalog/embedding_worker.py).

## What the benchmark consumes

The benchmark uses the same two Business Central exports as the database import:

| Input | How it is used |
|---|---|
| `Artikeldaten.csv` | Creates the candidate catalogue, product identity, category, base unit and German text |
| `Artikeluebersetzungen.csv` | Adds multilingual descriptions; French descriptions with the same article number become automatically labelled cross-language queries |
| `reviewed-labels.jsonl` | Optional but required before final approval; contains real normalized inquiries and a human-reviewed expected article number |

Both CSVs are required, UTF-8 and semicolon-separated. They are parsed with the production eligibility
rules from
[`../../apps/backend/app/catalog/parser.py`](../../apps/backend/app/catalog/parser.py): master rows and
unknown/non-offerable placeholders are not benchmark candidates. The supplied files currently yield
1,645 offerable candidates and 801 automatic French queries. Newer files can legitimately change
these counts.

Keep all real CSVs, labels and reports outside Git. Mount or download them into access-controlled
Azure job storage. The benchmark does not parse SharePoint, Outlook, PDFs or supplier datasheets;
the extraction workstream must provide normalized labels.

## Reviewed-label format

Use one JSON object per line:

```json
{"query_id":"case-1","text":"sonde urinaire Foley stérile CH18","expected_item_number":"410001001","domain":"equipment","language":"fr"}
```

Required fields are `query_id`, `text`, `expected_item_number` and `domain`. `language` is optional but
strongly recommended for subgroup analysis. The expected article must exist and be offerable in the
uploaded `Artikeldaten.csv`; otherwise the runner stops instead of silently evaluating a false label.
Start from [`labels.example.jsonl`](labels.example.jsonl), but never replace real review with the
example row.

Good reviewed labels cover both medicine and equipment, German/French/English wording, abbreviations,
misspellings and difficult distinctions such as strength, dosage form, size, sterility and packaging.
Use only inquiries whose correct catalogue article has been confirmed by a responsible person.

## Models compared first

The default free-first comparison is:

1. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
2. `BAAI/bge-m3`
3. `intfloat/multilingual-e5-large-instruct`

“Free” means there is no per-vector provider fee because the weights run in our own job. Azure
CPU/GPU, temporary storage, model downloads and engineering time still cost money. MiniLM is the
low-cost baseline; BGE-M3 and E5-large are larger quality candidates. The runner applies required E5
query/passages prefixes and the medical procurement instruction consistently.

## Where to run it

Run this in an Azure Container Apps Job or another adequately sized cloud runner, not on Martin's
project laptop. The normal web image intentionally excludes PyTorch and model weights. Build the
separate image from the repository root:

```bash
docker build \
  -f benchmarks/embeddings/Dockerfile \
  -t allocura-embedding-benchmark .
```

In Azure, use the same Dockerfile, attach secure read-only input storage and writable output storage,
and give the job outbound access to download model weights. Record the job's CPU/GPU type and hourly
price so model quality can be compared with measured operating cost.

## Required test sequence

### Gate 1: cloud smoke test

First test the smallest model on 25 queries. This proves that both ERP files are readable, the model
can be downloaded and an output report can be persisted without paying for a full run:

```bash
python benchmarks/embeddings/run.py \
  --articles /secure-input/Artikeldaten.csv \
  --translations /secure-input/Artikeluebersetzungen.csv \
  --models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
  --limit-queries 25 \
  --batch-size 8 \
  --compute-cost-per-hour <runner-hourly-price> \
  --output /secure-output/embedding-smoke-report.json
```

The gate passes only if the command exits successfully, the report names 25 queries, the model has a
non-zero dimension and timing, and failures can be inspected. A successful smoke test says nothing
about medical quality.

### Gate 2: full automatic comparison

Run all default models on all automatically derived French queries:

```bash
python benchmarks/embeddings/run.py \
  --articles /secure-input/Artikeldaten.csv \
  --translations /secure-input/Artikeluebersetzungen.csv \
  --batch-size 32 \
  --compute-cost-per-hour <runner-hourly-price> \
  --output /secure-output/embedding-automatic-report.json
```

Reduce `--batch-size` if a model runs out of memory. Use the same input pair and comparable runner
configuration for all candidates. This automatic set measures cross-language retrieval at scale, but
it is easier than real partner inquiries and cannot decide the winner alone.

### Gate 3: reviewed real-inquiry comparison

Add the normalized, human-reviewed label file:

```bash
python benchmarks/embeddings/run.py \
  --articles /secure-input/Artikeldaten.csv \
  --translations /secure-input/Artikeluebersetzungen.csv \
  --labels /secure-input/reviewed-labels.jsonl \
  --batch-size 32 \
  --compute-cost-per-hour <runner-hourly-price> \
  --output /secure-output/embedding-reviewed-report.json
```

Keep a final group of reviewed inquiries out of tuning decisions where the dataset is large enough.
That holdout gives a less biased final comparison.

### Gate 4: inspect the report and failures

For each model, record:

- exact model name and tested revision;
- vector dimensions and estimated database storage;
- Recall@1, Recall@3 and Recall@10;
- mean reciprocal rank (MRR);
- catalogue/query encoding time and throughput;
- measured Azure compute-cost estimate;
- runtime/model-download failures;
- failures grouped by medicine/equipment, language, strength, dosage form, size, sterility and package.

The first 100 failures are included for manual review. A model that retrieves the wrong strength or
device size can be unsafe even if its average score is highest. The team must write down acceptance
thresholds before choosing the winner; do not change thresholds after seeing which model benefits.

### Gate 5: approve and pin the winner

The decision record must contain:

1. links or secure locations for the automatic and reviewed reports;
2. dataset/export dates and reviewed-label version;
3. selected model and an immutable upstream revision/commit, never `main`;
4. quality and failure-analysis rationale;
5. measured runner cost and expected update frequency;
6. licence, privacy, retention and EU data-processing review;
7. rejected candidates and why they lost;
8. owner and approval date.

A paid API model may be added only after the open-model results are understood and its EU hosting,
retention, no-training terms, request volume and projected cost are documented with the same test set.

## Activate product embeddings only after approval

Run the same separately built image with its entry point overridden and a secure `DATABASE_URL` for
the migrated staging database:

```bash
python -m app.catalog.embedding_worker \
  --model <approved-model> \
  --revision <immutable-revision> \
  --batch-size 32
```

The worker:

1. loads the approved model and confirms its dimensions;
2. registers that exact model/revision as active;
3. queues every current, offerable product version without a compatible vector;
4. recovers jobs left running by an interrupted worker;
5. creates normalized document vectors and stores them in pgvector;
6. reports queued, completed and failed counts.

The initial supplied catalogue should target the current 1,645 offerable versions; use the current
database count rather than hard-coding that number into monitoring. Investigate every failed job and
rerun the worker only after correcting the cause. The operation is idempotent: completed compatible
pairs are not recomputed.

## Test matching after indexing

Product vectors alone are insufficient. Matching also needs a query vector generated by the exact
same model/revision and query formatting. The standard web image does not install Sentence
Transformers. Before calling semantic matching operational, choose and test one of these deployments:

- a dedicated internal query-embedding service using the pinned model;
- a model-enabled matching runtime containing the optional model dependencies;
- an orchestrator that sends both `query_embedding` and the exact `embedding_model_id` to
  `POST /api/v1/match-runs`.

Never compare vectors from different models or dimensions. After wiring query inference, rerun known
reviewed inquiries through the real matching API and confirm that vector evidence appears alongside
exact, lexical and historical evidence. Store the human decision separately; similarity is not a
confidence percentage.

## What happens after a new ERP file pair

1. Upload the matching new `Artikeldaten.csv` and `Artikeluebersetzungen.csv` pair through
   `POST /api/v1/catalog-imports`.
2. Review `inserted_items`, `text_updated_items`, `missing_items`, warnings and
   `embedding_jobs_created`.
3. Quantity-only changes create inventory snapshots but no model work.
4. New or text-changed eligible versions create jobs for the active model.
5. Run or schedule the embedding worker.
6. Confirm all new jobs complete before relying on semantic retrieval for those products.

The import orchestration is implemented in
[`../../apps/backend/app/catalog/service.py`](../../apps/backend/app/catalog/service.py). Text hashes
identify the exact normalized text already embedded; they do not replace the durable article number.

## Troubleshooting

| Symptom | Check |
|---|---|
| Missing CSV headers | Use the original UTF-8, semicolon-separated Business Central exports and both required files |
| `expected_item_number` rejected | Confirm the article exists and is offerable in the exact uploaded article file |
| Model download fails | Check outbound network, model name/revision, storage and provider availability |
| Out of memory | Lower `--batch-size`; use a larger CPU-memory/GPU job for BGE-M3 or E5-large |
| Report exists but has weak real-inquiry results | Improve reviewed labels and inspect domain/language failure groups; do not activate based on the automatic set |
| Worker completes but no vector evidence appears | Confirm query inference uses the same model ID/revision and that the request includes or can generate a query vector |
| Dimension mismatch | Stop; model/revision or stored vector identity is incompatible and must not be coerced |

## Embedding roadmap

| Status | Milestone | Exit criterion |
|---|---|---|
| Ready | Benchmark code and free-first candidates | Reproducible image builds from [`Dockerfile`](Dockerfile) |
| Next | Cloud smoke test | One small report generated from both ERP files |
| Next | Full automatic benchmark | All candidate reports complete on the full French set with comparable cost data |
| Next | Reviewed real-inquiry dataset | Responsible reviewers confirm expected article numbers and dataset version |
| Next | Failure review and model decision | Safety-relevant error groups reviewed and immutable winner approved |
| Next | Initial staging indexing | All current eligible versions have a vector or a documented failure |
| Next | Query-inference integration | Real match runs use the same pinned model and return vector evidence |
| Later | Scheduled incremental worker | New/text-changed versions are processed after each accepted ERP import with alerts |
| Later | Periodic re-evaluation | New reviewed decisions and drift are tested offline before any model replacement |

Do not mark the embedding work complete at “benchmark code exists.” Completion requires an approved
report, pinned model, indexed catalogue, query-inference path and end-to-end matching verification.
