# Allocura Matching: Architecture and Rationale

[German version](README_DETAILED_DE.md)

## 1. Purpose

Allocura supports action medeor staff who match multilingual requests for medicines and medical
equipment to approved catalogue variants and, when needed, historical procurement evidence. The
software is a decision-support system: it proposes candidates, explains them, and records the human
decision. It must not silently assert clinical equivalence or turn uncertain data into a confirmed
fact.

The framework is designed to be reliable, testable, auditable, modular, and incrementally scalable.
It intentionally starts with conservative deterministic behavior and makes probabilistic components
replaceable.

## 2. Non-negotiable principles

1. **Raw values are immutable evidence.** Normalized or inferred values never overwrite source data.
2. **Unknown is not false or zero.** Missing price is not free; missing shelf life is not sufficient.
3. **Retrieval is not approval.** Embeddings and history generate candidates, never clinical rules.
4. **Hard rules do not compete with price.** A confirmed exclusion cannot be outweighed by a cheap,
   available product.
5. **Every result is reproducible.** Algorithm, policy, model, and data versions are recorded.
6. **A valid result may contain no candidate.** The service never pads Top 10 with unsafe options.
7. **Human decisions are separate events.** A recommendation is not a confirmation.

## 3. System boundary

Matching starts after extraction.

```text
Excel / Outlook / PDF / SharePoint / ERP
                    │
             source-specific extraction
                    │
       versioned normalized contracts
                    │
             matching framework
```

The matching package never parses workbooks, email bodies, PDF layout, cell colors, or SharePoint
folders. Those concerns belong to intake/extraction adapters. This boundary prevents source-format
changes from contaminating safety-critical matching behavior.

### Outlook boundary

An Outlook connector should eventually use a dedicated mailbox/folder, Microsoft Graph immutable
message IDs, change notifications plus delta reconciliation, and immutable MIME/attachment storage.
Its extractor must emit the same normalized contracts as Excel. Matching only stores a generic
`SourceReferenceV1`, so an Outlook-derived line follows the identical pipeline.

## 4. Versioned contracts

### `InquiryLineV1`

Carries the original description, optional translation, normalized quantity/package request,
structured attributes, partner/destination context, parsing warnings, and precise source reference.

### `InventoryItemV1`

Carries a string item number, product domain, descriptions, normalized attributes, manufacturer,
brand, package, replenishment/T1 values, authoritative activity/quality flags, raw stock fields, and
source version.

### `HistoricalOfferV1`

Carries the historical request wording, mapped item when known, supplier evidence, price basis,
package, date, context, and SharePoint/source provenance.

### Why contracts are strict

All public models reject unexpected fields. This catches drift early: an extraction team cannot
silently rename `quantity.unit`, convert an item number to a float, or collapse unknown sterility to
`false`. Contract version `1` allows a future V2 without breaking historical reproduction.

## 5. Validation

Pydantic checks structure and types. `validation.py` adds matching-specific diagnostics, such as:

- normalized quantity missing;
- quantity unit missing;
- no structured attributes supplied;
- upstream parsing warnings.

Validation reports `valid`, `valid_with_warnings`, `review_required`, or `invalid`. Missing packaging
data does not prevent textual retrieval, but the result explicitly says that packaging cannot be
calculated.

## 6. Search representation

The framework builds two deterministic strings.

```text
semantic core:
  urinary Foley catheter sterile balloon

canonical text:
  urinary Foley catheter sterile balloon; charriere=18 ch; single_use=true
```

The semantic core supports multilingual meaning. The canonical form also renders normalized
attributes, making embedding content versionable and inspectable. Numbers are not removed wholesale:
they help recall, while structured constraints remain authoritative.

Unicode is normalized with NFKC and tokens are created deterministically. A SHA-256 content hash
identifies exactly which representation was embedded.

## 7. Retrieval channels

### Exact retrieval

Finds an explicitly requested item number or identical normalized description. It provides a strong
signal but still passes through activity, quality, and other constraints.

### Lexical retrieval

Uses dependency-free character similarity and token overlap. It handles spelling variants, partial
overlap, codes, and technical names. It is the transparent baseline and remains available when ML is
disabled.

### Vector retrieval

Uses cosine distance in PostgreSQL/pgvector. Vectors are compared only when the registered model ID
and dimensions match. The database stores variable-dimension vectors so future model experiments do
not require redesigning the schema. A model-specific approximate index can be added later.

The framework deliberately does not ship a production embedding model yet. `EmbeddingProvider` is a
port, and tests use a deterministic fake provider. A real model must win a multilingual, domain-
specific benchmark and pass licensing, cost, retention, and data-residency review.

### Historical retrieval

Finds earlier request text associated with catalogue items. Partner and destination context scope the
search. History can add an item to the candidate pool and contribute an inspectable score; it cannot
bypass current constraints or receive a false “historically verified” guarantee.

### Why this is not simply “filter first, then score”

The pipeline uses selective filtering. The trusted product domain is applied before retrieval because
a medicine and a piece of equipment cannot be interchangeable. Detailed attributes are not applied as
database filters: extracted values may be incomplete or differently normalized, and an early filter
would silently destroy recall. Instead, exact, lexical, vector, and historical retrieval create a
broad but bounded union; authoritative safety/status rules then remove prohibited candidates; review
rules annotate uncertainty; and deterministic ranking orders the eligible remainder. At the current
catalogue size, this is both fast and easier to audit than a premature graph or approximate-search
layer. Additional proven-safe prefilters can be introduced through a new policy version when scale or
measured latency requires them.

## 8. Candidate fusion

Retriever scores have different meanings and ranges. Cosine similarity, edit similarity, an exact
flag, and historical frequency must not be added directly.

The initial implementation uses Reciprocal Rank Fusion (RRF):

```text
RRF(item) = sum(1 / (k + rank_in_retriever))
```

RRF rewards candidates found highly by several independent channels, deduplicates item numbers, and
does not pretend that heterogeneous scores are calibrated. Individual evidence remains attached to
the candidate.

## 9. Constraint engine

The engine is policy-driven. A rule returns:

- `pass`;
- `exclude`;
- `review`;
- `warning`;
- `unknown`.

Every result includes a stable reason code, human explanation, compared values, attribute name, and
policy version.

### Safe V1 behavior

Only authoritative catalogue state is automatically hard-excluded now:

- wrong product domain;
- item explicitly inactive;
- item explicitly quality-blocked.

Potentially critical attributes such as ingredient, strength, concentration, dosage form, route,
size, gauge, Charrière, sterility, material, and compatibility are evaluated, but mismatches default
to `review` until action medeor approves exact substitution/exclusion rules. The JSON policy makes a
future change explicit, reviewable, and versionable.

Medicine and equipment attribute vocabularies remain separate even though the generic comparison
engine is shared.

## 10. Packaging and fulfilment evidence

When quantity, units-per-package, and units are comparable, the framework calculates both lower and
upper pack options.

Example: 50 requested pieces, 12 pieces per package.

```text
4 packages = 48 pieces (difference -2)
5 packages = 60 pieces (difference +10)
```

No option is recommended until action medeor confirms a rounding policy. Exact divisions can be
selected automatically because they introduce no rounding decision.

Stock is compared only when its unit/basis is explicitly compatible with the requested quantity or
selected package count. The current inventory workbook does not confirm that basis, so the honest
default is `unknown`, with raw on-hand/incoming/inquiry/committed fields preserved. The framework does
not implement an invented available-to-offer formula.

## 11. Ranking

Initial ranking is lexicographic and deterministic rather than an opaque weighted sum:

1. excluded candidates are removed;
2. fully passing candidates precede review/warning candidates;
3. exact item references receive priority;
4. stronger structured-attribute agreement receives priority;
5. fused retrieval rank resolves remaining product-fit differences;
6. comparable operational evidence may resolve otherwise equivalent candidates;
7. item number provides a stable final tie-breaker.

The framework records separate components (`exact_reference`, lexical, vector, history,
`attribute_match_ratio`, RRF). They are ranking evidence, not correctness probabilities. Price,
availability, reliability, recency, shelf life, documentation, and partner preference have explicit
extension points, but absent/non-comparable evidence is never converted to zero.

Top K defaults to ten and is bounded by the request contract. Fewer candidates are valid.

## 12. Explainability

Each returned candidate includes:

- retrieval channel, rank, score, and details;
- structured constraint results;
- matching and mismatching values;
- packaging options;
- conservative availability state;
- missing-data warnings;
- catalogue provenance;
- algorithm, policy, source, and embedding-model versions through the parent Match Run.

No field called “confidence percent” is produced. Confidence requires a labelled calibration set.

## 13. Persistence model

### Source and catalogue

- `source_snapshots`: immutable source identity, checksum, capture time, locator;
- `catalog_items`: stable item identity and authoritative status;
- `catalog_item_versions`: descriptions/attributes/package/content hash per source version;
- `inventory_snapshots`: time-dependent raw stock fields separated from product content.

This separation prevents frequent stock updates from triggering unnecessary re-embedding.

### Embeddings

- `embedding_models`: provider, name, version, dimensions, distance metric;
- `product_embeddings`: catalogue version, model, content hash, vector.

Exact cosine search is the default at the current catalogue size. pgvector is used to avoid a second
database service while retaining a clean scaling path.

### History and feedback

- `historical_offers`: normalized, timestamped procurement evidence;
- `match_runs`: immutable request and result payload plus versions and status;
- `match_candidates`: normalized audit rows for candidate-level analysis;
- `match_decisions`: accepted, alternative, manual, no-match, or procurement-required decision;
- `partner_preferences`: explicit proposed/approved/retired preferences with source evidence.

`partner_preferences` is never populated automatically from clicks.

## 14. API

The matching API is intentionally independent of the Figma UI branch.

### Create a run

```text
POST /api/v1/match-runs
```

Accepts `MatchRequestV1`. It persists `running`, performs matching, then commits the complete result or
marks the run `failed` with an error. A request can optionally provide a precomputed query embedding
and registered model ID.

### Read a run

```text
GET /api/v1/match-runs/{match_run_id}
```

Returns the original stored result, not a re-evaluation against current data.

### Record a decision

```text
POST /api/v1/match-decisions
```

Supports accepted suggestion, selected alternative, manual match, no match, and procurement required.
Alternatives require an override reason. Suggested/alternative candidates are verified against the
stored Match Run.

## 15. Fallback behavior

- No vector provider/data: exact + lexical + history continue.
- No history: catalogue matching continues.
- Missing packaging: candidate remains with packaging warning.
- Unconfirmed stock basis: availability remains unknown.
- No eligible candidates: completed run with an empty candidate list.
- Model dimension mismatch: visible configuration error and failed run.
- Database error: run failure is persisted where possible; no invented partial result.

## 16. Testing strategy

Unit and API tests cover:

- strict contract validation;
- exact, lexical, vector, and historical retrieval behavior;
- RRF deduplication;
- conservative constraint outcomes;
- inactive-item exclusion even when history/vector retrieves it;
- reversible pack calculation;
- unknown stock basis;
- deterministic ranking and fallback;
- stored run retrieval and decision validation.

An opt-in integration test uses a migrated PostgreSQL/pgvector database to verify real catalogue JSON
mapping and exact cosine search. Run it with `MATCHING_TEST_DATABASE_URL` set.

Future authorized benchmark data should measure Recall@1/3/10, MRR, coverage, latency, override rate,
and most importantly hard-constraint violations (target: zero). Real partner files are not committed as
test fixtures.

## 17. Figma UI integration boundary

No frontend file or UI branch is changed in this implementation. The prior UI inspection identified
future adapter requirements:

- distinguish algorithmic suggestion from human confirmation;
- avoid displaying a ranking score as calibrated confidence;
- represent availability beyond `lowStock: bool`;
- show warnings, constraints, provenance, and packaging;
- support manual match, no match, procurement required, and override reason;
- use only confirmed decisions in the order summary.

A future UI-specific response mapper can translate `MatchRunResponseV1` without changing matching
domain logic.

## 18. Ontologies and knowledge graphs

A controlled vocabulary or ontology can become valuable before a graph database does. Versioned
concept identifiers can normalize synonyms, translations, dosage forms, routes, units, product
families, and externally approved classifications while retaining every original value. Those concept
IDs can live in the existing relational attributes and improve both retrieval and constraint checks.

A graph database does not inherently reduce matching latency and would not replace vector, lexical,
or structured indexes. At the present scale it would add operational complexity without a proven
multi-hop query. The relational schema already represents the required direct relationships and
pgvector bounds semantic search. A separate knowledge graph becomes justified only when measured use
cases repeatedly need traversals such as product → compatible device → approved substitute → supplier
→ destination restriction, and those relations have authoritative owners and versioning rules.

## 19. Deliberately deferred work

| Deferred | Why now | Prepared now | Activation condition |
|---|---|---|---|
| Excel/PDF/mail extraction | Different team and failure domain | Strict contracts and provenance | Extractor payload agreed |
| Outlook connector | Needs mailbox, Entra, permissions, operations | Outlook source types/locators | Approved mailbox and access |
| Business Central live sync | No confirmed API/schema access | Catalogue/inventory ports and snapshots | Read-only API + data dictionary |
| SharePoint live sync | Folder/status authority unresolved | History port and provenance | Approved scope and permissions |
| Supplier stock APIs | Suppliers and semantics unknown | Supplier-ready candidate boundary | One approved pilot source |
| Production embedding model | No labelled comparison or governance decision | Provider port, registry, pgvector | Benchmark winner + privacy approval |
| HNSW/IVFFlat | 646 rows do not need approximate search | pgvector storage | p95 latency/scale threshold exceeded |
| Cross-encoder | Extra latency/MLOps without measured gain | Reranking boundary | Recall@10 good, ordering measurably weak |
| LLM as judge | Hallucination, cost, privacy, reproducibility | Not in critical path | Narrow non-safety use case only |
| Online learning | Position bias and unsafe feedback loops | Immutable exposure/decision data | Not planned without strong controls |
| Learning-to-rank | Too few clean labels | Feature and benchmark-ready records | Sufficient reviewed temporal dataset |
| Confidence percentage | Retrieval scores are not probabilities | Evidence and review states | Successful calibration study |
| Knowledge graph database | No proven multi-hop workload | Relational concepts/relations can be added | Repeated complex graph queries |
| Full ATC/SNOMED/GMDN mapping | Purpose/licence/mapping not confirmed | Optional external-code fields later | action medeor standard decision |
| Substitution hard rules | Clinical/technical equivalence unconfirmed | Versioned constraint policy | Explicit domain-owner approval |
| Available-to-offer formula | Stock field semantics unresolved | Separate raw snapshots | Authoritative formula confirmed |
| Automatic shelf-life exclusion | Arrival/receipt/route policy unresolved | Fields and constraint hook | Confirmed policy and lot data |
| Price ranking | Currency/basis/freight/validity incomplete | Comparable-evidence extension point | Normalized price contract |
| Supplier reliability score | No outcome history/minimum sample | Outcome-ready history model | Enough completed procurements |
| Automatic pack rounding | Direction varies by workflow | Both reversible options | Confirmed policy/profile |
| User-adjustable weights | Risks safety and reproducibility | Versioned server-side policy | Approved bounded scenario profiles |
| Automatic confirmation | Prototype is decision support | Explicit decision endpoint | Narrow proven case + approval |
| Figma UI changes | Today's scope is matching only | Stable API and integration notes | Separate UI integration task |
| Dashboards/forecasting/offers | Outside core matching acceptance | Auditable historical data | Stable matching MVP |
| Microservices/Kafka | Operational overkill for current team/volume | Ports and clean module boundaries | Demonstrated deployment/team need |

## 20. Adding a production embedding provider

1. Implement `EmbeddingProvider` with a stable `model_id`.
2. Register provider/name/version/dimensions in `embedding_models`.
3. Build canonical catalogue text and content hash.
4. Batch-generate vectors only for missing `(catalogue version, model)` pairs.
5. Store vectors in `product_embeddings`.
6. Evaluate on a held-out multilingual benchmark.
7. Activate only the approved model ID in the calling application.

Never compare vectors from different model IDs or dimensions.

## 21. Adding or changing a constraint

1. Obtain an authoritative domain decision and examples.
2. Add/normalize the attribute in the extraction contract.
3. Add a versioned policy entry (`on_missing`, `on_mismatch`).
4. Add passing, mismatch, missing, and boundary tests.
5. Build a regression set against existing labelled cases.
6. Publish a new policy version; never alter the meaning of an old recorded version.

## 22. Definition of done for this foundation

- no frontend changes;
- strict V1 contracts and provenance;
- four retrieval channels and deterministic fusion;
- conservative constraints and packaging;
- deterministic Top 10 with explainable evidence;
- pgvector migration and exact-search adapter;
- immutable runs, candidates, and decisions;
- fallback behavior;
- unit/API tests and real pgvector integration test;
- Ruff and pytest clean;
- short and detailed matching documentation.
