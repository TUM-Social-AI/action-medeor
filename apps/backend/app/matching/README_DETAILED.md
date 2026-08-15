# Allocura Matching: Detailed Walkthrough, Architecture and Rationale

[German version](README_DETAILED_DE.md) · [Short plain-language overview](README.md)

## 1. What exists today

The current implementation is a working and tested matching core. It can accept one already
normalized inquiry line, search prepared catalogue and history data, evaluate candidates, return an
explained ranking and store the later human decision.

It is not yet a complete production workflow. It does not read the real Lagerliste, parse Outlook
mail, synchronize ERP/SharePoint, generate production embeddings or connect to the Figma UI. The
database migration creates the required structures, but it does not fill them with action medeor
products.

The most useful mental model is:

> The engine and its connection points exist; the real data pipelines and selected production model
> still need to be connected.

```mermaid
flowchart LR
    S["Excel, Outlook, ERP<br/>(outside this package)"] --> A["Normalized inquiry line"]
    A --> B["Validate"]
    B --> C["Build searchable text"]
    C --> D["Retrieve candidates<br/>in four ways"]
    D --> E["Fuse ranked lists"]
    E --> F["Apply rules"]
    F --> G["Packaging and stock"]
    G --> H["Deterministic ranking"]
    H --> I["Explained Top K"]
    I --> J["Human decision"]
    J --> K["Audit and future learning data"]
```

### The safety promise

The system proposes; a person decides. It must not silently claim clinical equivalence, hide missing
data or let price, stock, embeddings or customer history overrule a confirmed exclusion.

Seven principles enforce this:

1. Raw source values remain immutable evidence.
2. Unknown does not mean false, zero, free or sufficient.
3. Search relevance is not product approval.
4. Hard exclusions cannot be outweighed by operational advantages.
5. Algorithm, policy, source and model versions are recorded.
6. A valid result may contain fewer than ten—or no—candidates.
7. A recommendation and a human confirmation are separate stored events.

## 2. How the code is divided

The package uses small modules so that data access, matching behavior and HTTP handling can change
independently.

| Responsibility | Files | Plain-language role |
|---|---|---|
| Public data shapes | [`contracts.py`](contracts.py) | Defines exactly what may enter and leave matching |
| Internal working state | [`domain.py`](domain.py) | Holds candidates while the algorithm is evaluating them |
| Replaceable interfaces | [`ports.py`](ports.py) | Describes what catalogue, history, vectors, models and storage must provide |
| Orchestration | [`service.py`](service.py) | Runs the complete sequence in the correct order |
| Input checks | [`validation.py`](validation.py) | Adds warnings and matching-specific validation |
| Searchable text | [`representation.py`](representation.py) | Normalizes descriptions and structured attributes |
| Candidate search | [`retrieval/`](retrieval/) | Exact, lexical, vector and historical retrieval plus fusion |
| Safety and attribute rules | [`constraints/`](constraints/) | Evaluates current versioned matching policy |
| Packaging and stock | [`packaging.py`](packaging.py) | Calculates package alternatives and conservative availability |
| Ranking | [`ranking/`](ranking/) | Creates inspectable features and deterministic ordering |
| Database implementations | [`adapters/persistence.py`](adapters/persistence.py) | Reads PostgreSQL/pgvector and stores runs and decisions |
| Test implementations | [`adapters/in_memory.py`](adapters/in_memory.py) | Provides deterministic data stores for tests without PostgreSQL |
| HTTP endpoints | [`api.py`](api.py) | Makes matching available to a future UI or another service |
| Human feedback checks | [`feedback.py`](feedback.py) | Ensures a decision refers to the correct run and candidate |

### Why interfaces and adapters exist

[`ports.py`](ports.py) contains interfaces rather than ERP-, SharePoint- or PostgreSQL-specific logic.
[`service.py`](service.py) therefore asks for “catalogue items” or “historical offers” without knowing
where they came from. Today an in-memory adapter supports tests and a PostgreSQL adapter supports the
real backend. Later, the data source can change without rewriting the matching rules.

This is also why the matching package does not parse Excel or Outlook itself. Parsing source formats
and deciding whether products match are different failure domains and should be tested separately.

## 3. What must enter matching

### The system boundary

```text
Excel / Outlook / PDF / SharePoint / ERP
                    │
          source-specific extraction
                    │
     versioned normalized JSON contracts
                    │
            matching framework
```

The extraction workstream must convert source material into the contracts in
[`contracts.py`](contracts.py). Matching never reads workbook layout, cell colors, MIME bodies, PDF
positions or SharePoint folders.

### `InquiryLineV1`

One requested line enters as `InquiryLineV1`. Important fields include:

- stable inquiry and line IDs;
- `medicine` or `equipment` domain;
- original description and optional translation;
- optional requested article number;
- normalized quantity and unit, while preserving the raw expression;
- structured attributes such as ingredient, strength, CH size or sterility;
- partner, destination, urgency and shelf-life request when known;
- parsing warnings;
- exact source reference.

### `InventoryItemV1`

Each catalogue item supplies:

- article number as a string, so leading zeros are never lost;
- domain and one or more descriptions;
- normalized product attributes;
- manufacturer, brand, family and package information;
- authoritative active and quality-blocked flags;
- a separate current stock snapshot;
- source version and provenance.

### `HistoricalOfferV1`

Historical evidence supplies the old request wording, mapped article when known, customer and
destination context, supplier, quantity, package, price basis, date and source. History is evidence
for candidate generation—not proof that the old choice remains suitable.

### `SourceReferenceV1`

Every input can identify its source type, document, checksum, timestamp, sheet/row or another locator.
This answers “where did this fact come from?” without requiring matching to understand the source
format.

All public models reject unexpected fields and require timezone-aware timestamps. This catches
contract drift early instead of silently accepting a renamed unit, a floating-point article number or
an ambiguous timestamp.

### Outlook inquiries

An Outlook connector is deliberately outside this package. It should eventually use an approved
mailbox/folder, immutable Microsoft Graph message IDs, notifications plus delta reconciliation and
immutable storage of MIME content and attachments. Its extractor should emit the same `InquiryLineV1`
records as Excel. Matching then processes both sources identically; only their `SourceReferenceV1`
differs.

## 4. The worked example used below

**Responsible files:** [`tests/matching/factories.py`](../../tests/matching/factories.py) creates the
data and [`tests/matching/test_service.py`](../../tests/matching/test_service.py) executes the full
pipeline. [`service.py`](service.py) orchestrates the behavior being demonstrated.

The inquiry is:

| Field | Value |
|---|---|
| Original description | `SONDE VESICALE FOLEY sterile CH18` |
| Domain | Equipment |
| Quantity | 50 pieces |
| Structured attributes | `charriere=18 CH`, `sterile=true` |
| Partner | `partner-1` |
| Destination | `CD` |
| Source | `request.xlsx`, sheet `Tabelle1`, row 7 |

A shortened version of the normalized request looks like this:

```json
{
  "inquiry_id": "request-1",
  "line_id": "line-1",
  "domain": "equipment",
  "raw_description": "SONDE VESICALE FOLEY sterile CH18",
  "quantity": {"value": "50", "unit": "piece", "raw_expression": "50"},
  "attributes": {
    "charriere": {"value": 18, "unit": "CH"},
    "sterile": {"value": true}
  },
  "partner_id": "partner-1",
  "destination_country": "CD",
  "source": {
    "source_type": "excel",
    "document_id": "request.xlsx",
    "sheet": "Tabelle1",
    "row": 7
  }
}
```

The test catalogue contains:

| Article | Description | Important facts |
|---|---|---|
| `410001001` | Foley urinary catheter sterile CH18 | Active, CH18, 80 pieces in stock |
| `410001002` | Foley urinary catheter sterile CH12 | Active, CH12, 500 pieces in stock |
| `410001003` | Foley urinary catheter sterile CH18 | Inactive, CH18, 500 pieces in stock, appears in history |

Every item contains 12 pieces per package. The test also supplies a simple two-dimensional query
embedding and stored vectors. These vectors prove the mechanics; they do not represent a production
multilingual embedding model.

## 5. Step 1 — Validate the request

**Responsible files:** [`contracts.py`](contracts.py), [`validation.py`](validation.py) and the first
part of [`service.py`](service.py).

### What happens

Pydantic first enforces the structural contract. The matching validator then reports whether quantity,
unit, attributes or upstream parsing information are missing. A request embedding is accepted only
together with its model ID, and every vector component must be finite.

The result is one of:

- `valid`;
- `valid_with_warnings`;
- `review_required`;
- `invalid`.

The example is `valid`. A missing normalized quantity would create a warning and disable packaging
calculation, but it would not necessarily prevent text search.

### Why this step exists

Without a strict boundary, malformed source data could look like a legitimate zero, false value or
unit. Validation makes uncertainty visible before ranking starts and keeps downstream modules simpler.

### Current limitation

The matching-specific validator is intentionally small. Domain-specific extraction confidence and
field-level acceptance thresholds still belong to the future extraction agreement.

## 6. Step 2 — Build deterministic searchable text

**Responsible file:** [`representation.py`](representation.py).

### What happens

The code applies Unicode NFKC normalization, case folding and a deterministic token pattern. It builds:

```text
semantic core:
  sonde vesicale foley sterile ch18

canonical text:
  sonde vesicale foley sterile ch18; charriere=18 ch; sterile=true
```

Attribute names are sorted, values and units are rendered consistently, and SHA-256 creates a stable
content hash. Catalogue items are represented by their descriptions, manufacturer, brand and
attributes using the same process.

### Why two forms exist

The semantic core keeps the natural product wording. The canonical text also includes facts that may
otherwise be hidden or inconsistently phrased. The content hash tells the embedding store exactly
which text version produced a vector, so unchanged products do not need to be embedded again.

### Current multilingual reality

This function does not translate. It combines the original description with an optional translation
provided upstream. Lexical matching is therefore only partly multilingual. True cross-language recall
depends on a future approved multilingual embedding model or upstream translation. The production API
currently has no embedding provider configured automatically.

## 7. Step 3 — Retrieve a broad candidate set

**Responsible files:** [`retrieval/exact.py`](retrieval/exact.py),
[`retrieval/lexical.py`](retrieval/lexical.py), [`retrieval/vector.py`](retrieval/vector.py),
[`retrieval/history.py`](retrieval/history.py), [`ports.py`](ports.py) and
[`adapters/persistence.py`](adapters/persistence.py).

[`service.py`](service.py) first asks the catalogue repository for items in the requested domain. The
default retrieval limit is 50 per channel. Four independent channels then create ranked lists.

### 3A. Exact retrieval

[`retrieval/exact.py`](retrieval/exact.py) finds:

- an explicitly requested article number; or
- an identical normalized semantic description.

An article-number match is a strong navigation signal, but the item still passes through active,
quality and attribute checks. Users and source files can contain outdated article numbers.

The example contains no requested article number and no identical bilingual description, so exact
retrieval adds no hit.

### 3B. Lexical retrieval

[`retrieval/lexical.py`](retrieval/lexical.py) combines:

- character similarity using `SequenceMatcher`;
- token-set overlap;
- coverage of inquiry tokens by the product text.

This channel is transparent, deterministic and useful for spelling variants, codes, numbers and
technical names. It also provides a fallback when vectors are unavailable.

It is not genuinely language-invariant. German/French wording and English catalogue wording only
match when they share enough terms, codes or structure. There is currently no calibrated minimum
lexical score; positive results can enter the bounded candidate pool and are controlled later by
rules, ranking and human review.

### 3C. Vector retrieval

[`retrieval/vector.py`](retrieval/vector.py) delegates vector search through `VectorRepository`.
[`PgVectorRepository`](adapters/persistence.py) then:

1. loads the registered model dimensions;
2. rejects unknown models or mismatched query dimensions;
3. selects the latest catalogue version for each article;
4. calculates exact cosine similarity using pgvector's `<=>` operator;
5. returns the nearest items for the requested domain.

Only vectors produced by the same model ID and dimension may be compared. The schema deliberately
supports multiple model registrations and variable vector dimensions.

In the test, article `410001001` and inactive article `410001003` have the strongest artificial vector
match. This demonstrates that vector relevance is only candidate generation; it cannot approve an
inactive item.

### What is still missing for production vectors

- no multilingual model has been selected or benchmarked;
- the API dependency setup in [`api.py`](api.py) configures vector search but no automatic
  `EmbeddingProvider`;
- therefore a caller must currently supply both `query_embedding` and `embedding_model_id` to use the
  vector channel through the API;
- no production indexing job currently generates and inserts vectors for all Lagerliste products;
- no approximate HNSW/IVFFlat index is needed at the current catalogue size.

### 3D. Historical retrieval

[`PostgresHistoryRepository`](adapters/persistence.py) loads recent offers scoped by partner and
destination when available. [`retrieval/history.py`](retrieval/history.py) compares the current query
tokens with previous request wording and returns the article linked to a similar historical offer.

In the example, history points to `410001003`. That may represent a real customer preference, an old
exception or an outdated choice. History therefore improves recall but receives no authority over
current rules.

Historical records without an article number cannot retrieve a catalogue item. A historical article
that is absent from the current catalogue is also discarded by [`service.py`](service.py).

### Why the pipeline does not simply filter all attributes first

Only the trusted product domain is used as an early filter. Detailed attributes are evaluated after
retrieval because extraction may be incomplete and units or vocabularies may not yet be normalized.
Using every attribute as a database filter would create false negatives: the correct item could
disappear before the system has a chance to explain uncertainty.

The chosen sequence is therefore:

```text
safe broad retrieval → authoritative exclusions → review annotations → deterministic ranking
```

Additional prefilters should only be added when they are proven safe and measured scale or latency
requires them.

## 8. Step 4 — Fuse the four ranked lists

**Responsible file:** [`retrieval/fusion.py`](retrieval/fusion.py).

### What happens

Lexical, vector, exact and history scores use unrelated scales. Adding `0.7 lexical + 0.8 vector`
would pretend those numbers mean the same thing. They do not.

The framework therefore uses Reciprocal Rank Fusion (RRF):

```text
RRF(article) = sum(1 / (60 + rank_in_channel))
```

The method cares about a product's position in each list rather than the raw score. It deduplicates an
article within each channel, rewards products found by several independent methods and keeps every
underlying retrieval hit as evidence.

### What happens in the example

Inactive `410001003` can receive strong fused evidence because lexical, vector and historical channels
all find it. `410001001` is also found strongly by lexical and vector search. `410001002` is found with
weaker text/vector positions.

Nothing is excluded at this stage. RRF answers only: “Which articles are worth checking?”

### Why RRF is the conservative first choice

It is deterministic, easy to inspect and does not require labelled training data or score
calibration. A learned fusion or cross-encoder can be evaluated later, but only against a benchmark
that proves an improvement without increasing hard-rule violations.

## 9. Step 5 — Apply safety and attribute rules

**Responsible files:** [`constraints/engine.py`](constraints/engine.py),
[`config/default_policy_v1.json`](config/default_policy_v1.json),
[`constraints/medicines.py`](constraints/medicines.py) and
[`constraints/equipment.py`](constraints/equipment.py).

### Possible rule outcomes

Each rule creates an inspectable result:

| Outcome | Meaning |
|---|---|
| `pass` | Confirmed compatible fact |
| `exclude` | Candidate must not be offered automatically |
| `review` | Important difference or missing fact requires a person |
| `warning` | Relevant concern that does not currently block |
| `unknown` | The available data cannot answer the question |

Every result includes a stable code, explanation, attribute name and the requested/candidate values.

### Current hard exclusions

V1 automatically excludes only facts that are authoritative now:

- wrong product domain;
- catalogue item explicitly inactive;
- catalogue item explicitly quality-blocked.

These checks cannot be outweighed by search relevance, history, price or stock.

### Attribute comparison

The policy currently knows medicine attributes such as ingredient, strength, concentration, dosage
form and route, and equipment attributes such as size, gauge, Charrière, sterility, material and
compatibility.

For each requested configured attribute, the engine compares normalized value and normalized unit.
Missing or mismatching critical values normally produce `review`, not `exclude`, because action medeor
has not yet approved exact substitution rules.

This comparison currently expects extraction to normalize synonymous units and concepts. For example,
`mg` and `milligram` are not yet resolved through an ontology inside matching.

### Example decisions

| Article | Checks | Result |
|---|---|---|
| `410001001` | Equipment, active, CH18 matches, sterile matches | `pass` |
| `410001002` | Equipment, active, CH12 differs from requested CH18 | `review` |
| `410001003` | Equipment and attributes match, but item is inactive | `exclude` |

The CH12 product remains visible for explicit review. The inactive CH18 product is removed even though
its search evidence is stronger.

### Why the policy is data, not hidden logic

Missing/mismatch severity lives in a versioned JSON policy. A future approved rule change can be
reviewed, tested and published under a new version. Old match runs retain the policy version that
produced them.

## 10. Step 6 — Calculate packaging alternatives

**Responsible file:** [`packaging.py`](packaging.py), function `calculate_packaging`.

### What happens

Packaging is calculated only when requested quantity, package size and units are known and comparable.
For 50 requested pieces and 12 pieces per package:

```text
floor: 4 packages = 48 pieces = difference -2
ceil:  5 packages = 60 pieces = difference +10
```

Both options are returned. An option is selected automatically only when the division is exact. For a
non-exact division, the current code emits a warning and leaves `recommended_option` empty.

### Why the code refuses to round automatically

Different humanitarian workflows may prefer avoiding shortages, avoiding excess, respecting carton
constraints or asking the customer. Until action medeor defines the rule, choosing four or five would
be a hidden business decision. Returning both options preserves the decision and makes it reversible.

### Fallbacks

- missing requested quantity → packaging `unknown`;
- missing package size → packaging `unknown`;
- non-comparable units → `unit_mismatch`;
- exact division → exact package count may be recommended.

## 11. Step 7 — Inspect current availability

**Responsible file:** [`packaging.py`](packaging.py), function `observed_availability`.

### What happens

The code uses `on_hand` only when its unit is confirmed comparable with the requested quantity. It can
also compare package counts when stock is explicitly measured in packages and packaging has an exact
recommended option.

Possible results are:

- `on_hand_sufficient`;
- `on_hand_partial`;
- `procurement_indicated` when comparable on-hand stock is zero;
- `unknown` when data or unit basis is missing;
- `not_allowed` is reserved for future operational rules.

In the example, both remaining articles have stock measured in pieces:

```text
410001001: 80 available versus 50 requested → sufficient
410001002: 500 available versus 50 requested → sufficient
```

### Why incoming and committed quantities are not combined yet

The database preserves on-hand, incoming purchase order, purchasing inquiry and committed order as
separate raw facts. It does not invent an “available to offer” formula because the meaning, timing and
unit basis of those columns have not been confirmed. Missing data remains `unknown` rather than being
treated as zero.

Supplier availability follows the same principle: the architecture can add a source, but there is no
approved supplier connector or shared stock semantics yet.

## 12. Step 8 — Rank eligible candidates

**Responsible files:** [`ranking/features.py`](ranking/features.py) and
[`ranking/ranker.py`](ranking/ranker.py).

### Inspectable components

The feature calculation records available evidence separately:

- fused RRF value;
- strongest score from each retrieval channel;
- `exact_reference=1` when exact retrieval found the item;
- structured-attribute match ratio when attributes are comparable.

These values explain ordering. They are not correctness probabilities.

### Actual ordering policy

Excluded products are removed. The rest are sorted lexicographically:

1. `pass` before any review/warning candidate;
2. exact article reference first;
3. higher structured-attribute agreement;
4. higher fused retrieval value;
5. better comparable availability;
6. article number as the stable final tie-breaker.

Lexicographic means a later factor cannot compensate for an earlier one. Therefore 500 pieces of CH12
do not outrank a fully matching CH18 product with 80 pieces merely because stock is higher.

### Example result

| Rank | Article | Review state | Availability | Reason |
|---:|---|---|---|---|
| 1 | `410001001` | `pass` | Sufficient | All requested attributes match |
| 2 | `410001002` | `review` | Sufficient | CH12 differs from requested CH18 |
| — | `410001003` | `exclude` | Not returned | Catalogue marks item inactive |

Top K defaults to ten and may be set from 1 to 50. The result is not padded: two safe/reviewable
articles remain two results.

### Metrics deliberately absent from current ranking

Price, shelf life, supplier reliability, purchase recency, documentation completeness and approved
partner preferences are not active ranking factors yet. Their raw or future extension points exist,
but comparable definitions and authoritative data are missing. Treating missing price as zero or an
unknown shelf life as acceptable would create incorrect rankings.

User-adjustable weights are also deferred. Unbounded weights could let a user make price compensate
for a critical product mismatch and would make old runs difficult to reproduce.

## 13. Step 9 — Build and return an explained result

**Responsible files:** [`service.py`](service.py), [`contracts.py`](contracts.py) and
[`api.py`](api.py).

[`service.py`](service.py) creates a `MatchCandidateV1` for every ranked item. Each candidate contains:

- stable candidate ID within the run;
- article number, descriptions and manufacturer;
- rank and review status;
- availability status;
- every retrieval hit with channel, rank, score and details;
- separate score components;
- every constraint result and compared value;
- packaging alternatives and warnings;
- catalogue provenance.

The parent `MatchRunResponseV1` adds inquiry/line IDs, run status, algorithm version, policy version,
embedding model ID, validation report and timestamps.

A shortened response for the example is:

```json
{
  "status": "completed",
  "algorithm_version": "allocura-matching-v1",
  "policy_version": "matching-policy-v1",
  "candidates": [
    {
      "rank": 1,
      "item_number": "410001001",
      "review_status": "pass",
      "availability_status": "on_hand_sufficient",
      "packaging": {
        "options": [
          {"packages": 4, "total_units": "48", "difference": "-2"},
          {"packages": 5, "total_units": "60", "difference": "10"}
        ],
        "recommended_option": null
      }
    },
    {
      "rank": 2,
      "item_number": "410001002",
      "review_status": "review",
      "availability_status": "on_hand_sufficient"
    }
  ]
}
```

### Why no confidence percentage exists

Cosine similarity, lexical similarity, RRF and attribute agreement are not calibrated probabilities.
Displaying “93% correct” would be misleading until a representative labelled dataset supports
calibration and measures error by product type, language and missing-data pattern.

## 14. Step 10 — Store the human decision safely

**Responsible files:** [`feedback.py`](feedback.py), [`contracts.py`](contracts.py),
[`adapters/persistence.py`](adapters/persistence.py) and [`api.py`](api.py).

The result is a recommendation, not an order. A later `MatchDecisionRequestV1` can record:

- `accept_suggestion`;
- `select_alternative`;
- `manual_match`;
- `no_match`;
- `procurement_required`.

A selected product is required for suggestion, alternative and manual decisions. Selecting an
alternative requires an override reason. For accepted suggestions and alternatives,
[`feedback.py`](feedback.py) verifies that the item—and optional candidate ID—was actually exposed in
the referenced completed run. It also verifies the inquiry line ID.

### Why recommendation and decision are separate

Separating them records both what the algorithm showed and what the person chose. That makes override
analysis possible and prevents an accepted item from being presented later as an algorithmic fact.

### What “learning” means today

The decision is stored as immutable evidence. No weight or rule changes immediately after a click.
Automatic online learning would absorb position bias, accidental clicks and potentially unsafe
choices. Later, reviewed decisions can form a temporal offline dataset for evaluation and controlled
learning-to-rank experiments.

`partner_preferences` is prepared for explicit proposed/approved/retired preferences. It is never
populated automatically from clicks.

## 15. HTTP API and application wiring

**Responsible files:** [`api.py`](api.py), [`service.py`](service.py),
[`../db/session.py`](../db/session.py) and [`../main.py`](../main.py).

### Create a run

```text
POST /api/v1/match-runs
```

Accepts `MatchRequestV1`, creates a `running` audit record, executes the pipeline and returns
`MatchRunResponseV1` with HTTP 201. Contract or configuration errors become HTTP 422.

### Read a run

```text
GET /api/v1/match-runs/{match_run_id}
```

Returns the stored result. It does not rerun matching against today's catalogue, which would change
the historical meaning of the result. Unknown runs return HTTP 404.

### Record a decision

```text
POST /api/v1/match-decisions
```

Stores a validated human decision and returns HTTP 201. Missing runs return 404; inconsistent
decisions return 422.

### How dependencies are assembled

`get_matching_service` in [`api.py`](api.py) receives an asynchronous SQLAlchemy session and builds:

- `PostgresCatalogRepository`;
- `PostgresHistoryRepository`;
- `PostgresMatchRunRepository`;
- `PgVectorRepository`;
- the default versioned matching policy.

No production `EmbeddingProvider` is wired here yet. Consequently, ordinary API requests use exact,
lexical and historical retrieval unless the caller includes a precomputed query vector and model ID.

The API is intentionally UI-independent. It accepts matching contracts, not React/Figma view models or
uploaded source files.

## 16. PostgreSQL and pgvector persistence

**Responsible files:** [`adapters/persistence.py`](adapters/persistence.py),
[`20260814_0001_matching_foundation.py`](../../migrations/versions/20260814_0001_matching_foundation.py)
and [`docker-compose.yml`](../../../../docker-compose.yml).

The Compose service still uses database name `allocura`, port 5432 and the existing named volume. Only
the image changed from plain PostgreSQL 16 to PostgreSQL 16 with pgvector included. This enables
`CREATE EXTENSION vector`; it does not rename or intentionally delete the database.

### Source and catalogue tables

| Table | What it stores | Why it is separate |
|---|---|---|
| `source_snapshots` | Source identity, checksum, capture time and locator | Immutable provenance for every imported version |
| `catalog_items` | Stable article number, domain, active/quality status | Identity and authoritative status outlive descriptions |
| `catalog_item_versions` | Descriptions, attributes, package, content hash and valid time | Product content can change while identity stays stable |
| `inventory_snapshots` | On-hand, incoming, inquiry, committed, unit and capture time | Frequent stock updates must not force re-embedding product text |

`PostgresCatalogRepository` selects the latest product version and latest stock snapshot per article.
An optional `catalog_snapshot_id` can restrict the catalogue source version.

### Embedding tables

| Table | What it stores |
|---|---|
| `embedding_models` | Provider, model name/version, dimensions and cosine metric |
| `product_embeddings` | Catalogue-version/model pair, content hash and vector |

Vectors are attached to a catalogue item version rather than mutable stock. Exact cosine search is
used now. A model-specific approximate index can be introduced later without replacing the matching
service interface.

### History, runs and feedback tables

| Table | Purpose |
|---|---|
| `historical_offers` | Normalized, timestamped historical request and procurement evidence |
| `match_runs` | Original request, versions, status, complete result or error |
| `match_candidates` | Candidate-level evidence for analytics and auditing |
| `match_decisions` | The later human decision and override explanation |
| `partner_preferences` | Explicit versioned proposed/approved/retired preferences |

### Transaction behavior

The run is first committed as `running`. Completion writes the result and candidate rows. If that
transaction fails, the repository rolls it back before recording `failed`. This preserves a terminal
audit state instead of leaving a partially stored candidate list.

### What the migration does not do

It does not import the Lagerliste, generate product embeddings or configure live ERP/history data.
After migration, the structures exist but may be empty until an ingestion/indexing process fills them.

## 17. Reproducibility, provenance and limitations

The framework records:

- contract version;
- algorithm version (`allocura-matching-v1`);
- constraint-policy version (`matching-policy-v1`);
- embedding model ID when used;
- complete request and result payloads;
- source document, checksum, timestamp and locator;
- retrieval evidence and compared values;
- human decision as a separate event.

This makes a result explainable after the fact. Exact replay is strongest when callers pin the
catalogue snapshot and embedding model. If `catalog_snapshot_id` is omitted, the repository uses the
latest catalogue versions at execution time. The stored payload and candidate provenance preserve the
audit record, but a later full rerun against changed data is not guaranteed to recreate the original
candidate pool. Production ingestion should therefore establish explicit snapshot/as-of semantics.

Raw values and normalized values remain separate. Unknown information is not silently filled. Errors
are stored with the run where possible, truncated to a safe database length.

## 18. Fallback and failure behavior

| Situation | Current behavior | Reason |
|---|---|---|
| No query vector/provider | Exact, lexical and history continue | Matching remains usable without ML |
| No history | Catalogue retrieval continues | New customers remain matchable |
| Missing package size | Candidate remains with packaging warning | Product relevance may still be useful |
| Unconfirmed stock unit | Availability is `unknown` | Avoid invalid quantity comparison |
| All candidates excluded | Completed run with empty list | Never pad Top 10 with unsafe items |
| Unknown model/dimension mismatch | Run fails visibly | Never compare incompatible vectors |
| Database error during completion | Partial transaction rolls back; failure is recorded where possible | Avoid partial audit data |
| Historical item not in current catalogue | Candidate is ignored | History cannot resurrect a removed catalogue record |

## 19. Testing: what is proven

**Responsible files:** [`tests/matching/`](../../tests/matching/),
[`tests/test_matching_api.py`](../../tests/test_matching_api.py) and
[`tests/integration/test_matching_postgres.py`](../../tests/integration/test_matching_postgres.py).

Automated tests cover:

- strict contracts, embedding pairs, finite vectors and timezone-aware sources;
- exact and stable lexical retrieval;
- RRF deduplication and multi-channel reward;
- conservative mismatches and authoritative inactive exclusion;
- packaging floor/ceil options and unknown stock basis;
- vector/history fallback;
- deterministic ordering in the worked example;
- empty results instead of unsafe Top-10 padding;
- decisions referring only to exposed candidates;
- HTTP create/read behavior;
- real catalogue JSON mapping and exact pgvector cosine search in the opt-in integration test.

The standard test suite uses deterministic in-memory adapters. The pgvector integration test requires
a migrated PostgreSQL/pgvector database and `MATCHING_TEST_DATABASE_URL`; it skips when this is not
configured. Real partner files are not committed as fixtures.

### What future evaluation must measure

A labelled, temporally separated multilingual benchmark should measure Recall@1/3/10, MRR, coverage,
p50/p95 latency, override/no-match rate and—most importantly—hard-constraint violations, whose target
must be zero. Model selection should compare by product domain, language and missing-data pattern, not
only one aggregate score.

## 20. Figma UI integration boundary

No frontend file or UI branch was changed. The matching API is ready for a later UI adapter, but the
current Figma/React models must not flatten important matching states.

The future UI must:

- distinguish an algorithmic suggestion from a human confirmation;
- show `pass`, `review`, warning and availability states without calling them confidence;
- display attribute differences, provenance and packaging alternatives;
- support manual match, no match, procurement required and override reason;
- use only confirmed decisions in an order summary;
- represent availability more accurately than a single `lowStock: bool`.

A thin UI mapper should translate `MatchRunResponseV1` to display models. The matching domain must not
import React types or Figma-specific assumptions.

## 21. Scaling, filtering, ontologies and knowledge graphs

### Current latency strategy

At the current catalogue size, exact PostgreSQL/pgvector search and bounded lexical comparison are
simple, fast and auditable. Premature microservices, Kafka or approximate indexes would add deployment
and consistency cost before a measured bottleneck exists.

The pipeline already avoids an unbounded full search by filtering trusted domain, limiting each
retriever and retaining a clear index path. When p95 latency or catalogue volume crosses an agreed
threshold, model-specific HNSW/IVFFlat, database text indexes, caching or safe prefilters can be added
behind the existing ports.

### Ontology before graph database

A controlled vocabulary or ontology can provide value earlier than a graph database. Versioned
concept IDs can normalize:

- synonyms and translations;
- ingredient and dosage-form concepts;
- routes and units;
- product families and compatibility codes;
- approved ATC/SNOMED/GMDN mappings where licensing and purpose are confirmed.

These identifiers can live in the existing relational attributes while raw source wording remains
available. They would improve both retrieval and rule comparison—for example resolving `mg` and
`milligram` to the same unit concept.

A graph database does not inherently make vector search faster. It becomes justified only when
measured workloads repeatedly need authoritative multi-hop traversal such as:

```text
product → compatible device → approved substitute → supplier → destination restriction
```

Until those relationships have owners, versioning rules and real query demand, PostgreSQL plus
pgvector is the cleaner system.

## 22. What is implemented and what is not operational

| Area | Current status | Practical meaning |
|---|---|---|
| Contracts and validation | Implemented | Prepared normalized data can enter safely |
| Exact/lexical retrieval | Implemented | Transparent baseline works without ML |
| pgvector storage/search | Implemented | Schema and query adapter exist |
| Historical retrieval | Implemented | Prepared old offers can contribute candidates |
| RRF, rules, packaging, availability, ranking | Implemented | The tested matching core runs end to end |
| API, runs and decisions | Implemented | A caller can match/read/record feedback when DB data exists |
| Excel/Outlook extraction | Not implemented here | Extraction workstream must emit the contracts |
| Lagerliste/ERP catalogue ingestion | Not operational | Database is not automatically populated |
| Product embedding indexing | Not operational | No production model or batch indexing job |
| Live SharePoint/ERP/supplier connectors | Not operational | Ports exist; credentials/schema/semantics unresolved |
| Price/shelf-life/reliability ranking | Not active | Comparable data and approved rules are missing |
| Active or learned ranking | Not active | Feedback is stored only for controlled future use |
| Figma UI connection | Not implemented | UI branch remains untouched |

## 23. Deliberately deferred work

| Deferred | Why now | Prepared now | Activation condition |
|---|---|---|---|
| Excel/PDF/mail extraction | Different team and failure domain | Strict contracts and provenance | Extractor payload agreed |
| Outlook connector | Needs mailbox, Entra, permissions and operations | Outlook source types/locators | Approved mailbox and access |
| Business Central live sync | No confirmed API/schema access | Catalogue/inventory ports and snapshots | Read-only API and data dictionary |
| SharePoint live sync | Folder/status authority unresolved | History port and provenance | Approved scope and permissions |
| Supplier stock APIs | Suppliers and semantics unknown | Supplier-ready boundary | One approved pilot source |
| Production embedding model | No labelled comparison or governance decision | Provider port, registry and pgvector | Benchmark winner and privacy approval |
| HNSW/IVFFlat | Current catalogue does not need approximate search | pgvector storage | p95 latency/scale threshold exceeded |
| Cross-encoder | Extra latency/MLOps without measured gain | Reranking boundary | Recall@10 good, ordering measurably weak |
| LLM as judge | Hallucination, cost, privacy and reproducibility | Not in critical path | Narrow non-safety use case only |
| Online learning | Position bias and unsafe feedback loops | Immutable exposure/decision data | Not planned without strong controls |
| Learning-to-rank | Too few reviewed labels | Feature and benchmark-ready records | Sufficient temporal reviewed dataset |
| Confidence percentage | Retrieval scores are not probabilities | Evidence and review states | Successful calibration study |
| Knowledge graph database | No proven multi-hop workload | Relational concepts can be added | Repeated authoritative graph queries |
| Full ATC/SNOMED/GMDN mapping | Purpose/licence/mapping unconfirmed | Ontology-ready attributes | action medeor standard decision |
| Substitution hard rules | Clinical/technical equivalence unconfirmed | Versioned policy | Explicit domain-owner approval |
| Available-to-offer formula | Stock semantics unresolved | Separate raw snapshots | Authoritative formula confirmed |
| Automatic shelf-life exclusion | Arrival/receipt/route policy unresolved | Contract field and rule hook | Confirmed policy and lot data |
| Price ranking | Currency/basis/freight/validity incomplete | Comparable-evidence extension point | Normalized price contract |
| Supplier reliability score | No outcome history/minimum sample | Outcome-ready history model | Enough completed procurements |
| Automatic pack rounding | Direction varies by workflow | Both reversible options | Confirmed policy/profile |
| User-adjustable weights | Safety and reproducibility risk | Versioned server policy | Approved bounded scenario profiles |
| Automatic confirmation | System is decision support | Explicit decision endpoint | Narrow proven case and approval |
| Figma UI changes | Current scope is matching only | Stable API and UI notes | Separate UI integration task |
| Dashboards/forecasting/offers | Outside core matching acceptance | Auditable historical data | Stable matching MVP |
| Microservices/Kafka | Operational overkill at current scale | Ports and module boundaries | Demonstrated deployment/team need |

## 24. How to extend the framework safely

### Add a production embedding provider

1. Implement `EmbeddingProvider` from [`ports.py`](ports.py) with a stable model ID.
2. Register provider, name, version, dimensions and cosine metric in `embedding_models`.
3. Build canonical catalogue text with [`representation.py`](representation.py).
4. Generate vectors only for missing `(catalogue version, model)` pairs.
5. Validate dimensions and persist the content hash with every vector.
6. Evaluate on a held-out multilingual, domain-specific benchmark.
7. Complete licensing, privacy, retention, residency, cost and latency review.
8. Wire only the approved model ID into the API/indexing workflow.

Never compare vectors from different models or dimensions.

### Add or change a constraint

1. Obtain a documented decision from the appropriate domain owner.
2. Add/normalize the attribute in the extraction contract.
3. Add a versioned policy entry for missing and mismatch behavior.
4. Add pass, mismatch, missing, unit and boundary tests.
5. Run regression evaluation on existing labelled cases.
6. Publish a new policy version; never change the historical meaning of an old version.

### Connect a new data source

1. Keep source parsing outside matching.
2. Preserve raw data and create immutable source/checksum/version metadata.
3. Map into the V1 contracts without source-specific fields leaking into matching logic.
4. Implement or feed the relevant port: catalogue, history, vectors or decisions.
5. Add contract, mapping, idempotency, update and failure-recovery tests.
6. Define snapshot/as-of semantics before calling the integration production-ready.

## 25. Definition of done for this foundation

- no frontend changes;
- strict versioned contracts and provenance;
- exact, lexical, vector and historical retrieval;
- deterministic RRF fusion;
- conservative policy-driven constraints;
- reversible packaging and honest stock evidence;
- deterministic, explained Top K without unsafe padding;
- PostgreSQL/pgvector schema and adapters;
- immutable match runs, candidates and human decisions;
- API endpoints and fallback behavior;
- automated unit/API tests and an opt-in real pgvector integration test;
- English and German plain-language and detailed documentation.

The foundation is complete as a matching core. Production readiness still depends on real ingestion,
catalogue population, embedding-model selection, domain-policy approval, operational monitoring and a
separate UI integration.
