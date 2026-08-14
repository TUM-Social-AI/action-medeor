# Allocura Matching

[German version](README_DE.md)

Allocura Matching is an explainable decision-support backend for mapping normalized medicine and
medical-equipment inquiry lines to catalogue item variants. It returns a short, auditable list of
candidates for a human to confirm. It does not make autonomous clinical or procurement decisions.

## What this package does

For each normalized inquiry line, the service:

1. validates the versioned input contract;
2. builds deterministic semantic and canonical text representations;
3. retrieves candidates through exact, lexical, vector, and historical channels;
4. combines those lists with Reciprocal Rank Fusion;
5. evaluates versioned medical/equipment constraints;
6. calculates reversible packaging options and conservative stock evidence;
7. ranks eligible candidates deterministically;
8. returns up to ten candidates with reasons, warnings, and provenance;
9. persists the complete run and the later human decision.

The same input, source versions, algorithm version, policy version, and embedding model produce the
same ordering.

## What this package does not do

- It does not read Excel, PDF, email, Outlook, or SharePoint files.
- It does not infer missing strengths, sizes, shelf life, or substitutions.
- It does not calculate available-to-offer stock until action medeor confirms the formula.
- It does not treat an embedding score as a correctness probability.
- It does not learn online from every click.
- It does not change or depend on the Figma UI branch.

Extraction systems must produce `InquiryLineV1`, `InventoryItemV1`, and `HistoricalOfferV1` data.
Raw source values and provenance remain attached to every normalized record.

## Package map

```text
matching/
├── contracts.py       Versioned API and source contracts
├── domain.py          Internal candidate state
├── ports.py           Catalogue, vector, history, model, and run interfaces
├── representation.py Deterministic searchable text
├── validation.py      Defensive input validation
├── retrieval/         Exact, lexical, vector, history, and fusion
├── constraints/       Policy-driven medicine/equipment rules
├── packaging.py       Pack rounding options and stock evidence
├── ranking/           Inspectable features and deterministic ordering
├── adapters/          In-memory and PostgreSQL/pgvector implementations
├── service.py         Matching orchestration
├── api.py             UI-independent HTTP boundary
└── README_DETAILED.md Architecture, rationale, safety, and roadmap
```

## HTTP API

```text
POST /api/v1/match-runs
GET  /api/v1/match-runs/{match_run_id}
POST /api/v1/match-decisions
```

The API accepts normalized JSON, not uploaded source files. The Figma UI can later use a thin mapper
around this API without coupling the matching domain to React types.

## Local development

From `apps/backend`:

```bash
uv sync
uv run pytest -q
uv run ruff check .
```

Start the pgvector-enabled database and apply migrations:

```bash
docker compose up -d db
uv run alembic upgrade head
```

The default migration creates versioned catalogue, inventory, embedding, history, match-run,
candidate, decision, and explicit partner-preference tables.

## Current algorithm status

Implemented now:

- exact and deterministic lexical retrieval;
- vector retrieval through a model-agnostic pgvector port;
- historical retrieval as a non-authoritative recall signal;
- Reciprocal Rank Fusion;
- conservative policy-based constraints;
- reversible pack calculations;
- deterministic Top-K ranking;
- immutable match runs and decisions;
- fallbacks when vector/history data is unavailable.

Not selected yet:

- production multilingual embedding model;
- confirmed action-medeor availability and substitution policies;
- learned ranking or calibrated confidence;
- live ERP, SharePoint, Outlook, or supplier adapters.

See [README_DETAILED.md](README_DETAILED.md) before changing matching behavior.
