# Allocura Matching: Current Status and End-to-End Example

[German version](README_DE.md) · [Detailed technical documentation](README_DETAILED.md)

The simplest description is:

> We have built and tested the matching engine, but it is not yet connected to the real
> Excel/Outlook/ERP data flow and does not yet use a production embedding model.

It currently works when it receives already-clean, structured data.

```mermaid
flowchart LR
    S["Excel, Outlook, ERP<br/>(extraction not built here)"] --> A["Normalized inquiry line"]
    A --> B["Validate input"]
    B --> C["Search for candidates<br/>in four ways"]
    C --> D["Merge candidate lists"]
    D --> E["Check safety and attributes"]
    E --> F["Calculate packaging<br/>and inspect stock"]
    F --> G["Create deterministic ranking"]
    G --> H["Return up to 10<br/>explained candidates"]
    H --> I["Human confirms or changes"]
    I --> J["Decision is stored<br/>for later evaluation"]
```

## A concrete example

**Example source:** [`tests/matching/factories.py`](../../tests/matching/factories.py) defines the
inquiry and catalogue records; [`tests/matching/test_service.py`](../../tests/matching/test_service.py)
runs the complete example. [`service.py`](service.py) coordinates the end-to-end matching sequence.

The automated tests contain this example inquiry:

| Input field | Value |
|---|---|
| Description | `SONDE VESICALE FOLEY sterile CH18` |
| Product type | Medical equipment |
| Quantity | 50 pieces |
| Size | CH18 |
| Sterile | Yes |
| Customer | `partner-1` |
| Destination | Democratic Republic of the Congo |
| Source | Row 7 of `request.xlsx` |

The important point is that the matching code does not read row 7 itself. Another component must
first turn the Excel row—or an Outlook email—into this structured information.

From the matching system's perspective, Excel and Outlook become the same kind of input after
extraction.

## Step 1: Validate the input

**Responsible code:** [`contracts.py`](contracts.py) defines the permitted input structure and
[`validation.py`](validation.py) performs the additional matching-specific checks.

The framework checks whether the input has the expected structure:

- Is there an inquiry and line ID?
- Is this a medicine or equipment request?
- Is there a description?
- Is the quantity valid?
- Are source file, row and timestamp recorded?
- If an embedding is supplied, does it also include a model ID?

For the example, validation returns:

```text
Status: valid
Warnings: none
Errors: none
```

Missing information does not always stop matching. For example, a missing quantity can produce a
warning while textual product search still continues.

## Step 2: Create a searchable representation

**Responsible code:** [`representation.py`](representation.py) normalizes the text, renders the
structured attributes and creates the stable content hash.

The description and attributes are converted into a stable internal text:

```text
sonde vesicale foley sterile ch18;
charriere=18 ch;
sterile=true
```

This makes searches reproducible and ensures that important structured values such as CH18 are not
hidden inside the description.

What it does not currently do is translate this text automatically. Multilingual understanding will
ultimately come from a selected multilingual embedding model or an upstream translation. The
production model has not been selected yet.

## Step 3: Search for possible products

**Responsible code:** [`retrieval/exact.py`](retrieval/exact.py),
[`retrieval/lexical.py`](retrieval/lexical.py), [`retrieval/vector.py`](retrieval/vector.py) and
[`retrieval/history.py`](retrieval/history.py) implement the four search channels. The real
PostgreSQL/pgvector queries live in [`adapters/persistence.py`](adapters/persistence.py).

The test catalogue contains three products:

| Product | Description | Status | Stock |
|---|---|---|---:|
| `410001001` | Foley catheter, sterile, CH18 | Active | 80 pieces |
| `410001002` | Foley catheter, sterile, CH12 | Active | 500 pieces |
| `410001003` | Foley catheter, sterile, CH18 | Inactive | 500 pieces |

The framework searches through four independent channels.

### 1. Exact search

This checks for an explicitly supplied article number or an identical normalized description.

No article number was supplied in this example.

### 2. Lexical search

This compares the actual words and characters. It recognizes that “Sonde Vesicale Foley” resembles
“Foley urinary catheter,” although this method alone is not genuinely language-independent.

### 3. Vector search

This compares the inquiry embedding with stored product embeddings.

In the test, the vectors are artificial and deterministic. They prove that the integration works,
but they are not a selected production multilingual model.

### 4. Historical search

This looks at previous requests and offers. In the example, the customer previously received an offer
involving product `410001003`.

History may therefore bring that product into consideration—but history can never override current
safety or catalogue status.

## Step 4: Merge the search results

**Responsible code:** [`retrieval/fusion.py`](retrieval/fusion.py) implements Reciprocal Rank Fusion
and deduplicates products found by several search channels.

Each search method produces its own ranked list.

The framework does not directly add the raw scores because a lexical score and a vector score mean
different things. Instead, Reciprocal Rank Fusion rewards products that appear near the top of several
lists.

In this example, inactive product `410001003` may initially look especially promising:

- its text is a good match;
- its vector is a good match;
- it appears in customer history.

But search only finds possibilities. It does not approve them.

## Step 5: Apply safety and attribute checks

**Responsible code:** [`constraints/engine.py`](constraints/engine.py) evaluates the rules, while
[`config/default_policy_v1.json`](config/default_policy_v1.json) defines the current behavior for
missing or mismatching attributes.

Every retrieved product is checked independently.

### Product `410001001`

- correct domain: pass
- requested CH18, product CH18: pass
- requested sterile, product sterile: pass
- active: yes
- quality-blocked: no

Result: `pass`

### Product `410001002`

- correct domain: pass
- requested CH18, product CH12: mismatch
- requested sterile, product sterile: pass
- active: yes

Result: `review`

It is not automatically excluded because action medeor has not yet formally approved which size or
substitution mismatches must be hard exclusions. The system therefore exposes the problem instead of
inventing a medical rule.

### Product `410001003`

- correct domain: pass
- CH18: pass
- sterile: pass
- active: no

Result: `exclude`

This product is removed even though search and customer history liked it. That is an important safety
property: retrieval strength cannot outweigh an authoritative exclusion.

## Step 6: Calculate packaging

**Responsible code:** [`packaging.py`](packaging.py), specifically `calculate_packaging`, calculates
the lower and upper package alternatives without inventing a rounding decision.

All three products contain 12 pieces per package. The inquiry requests 50 pieces.

The framework calculates both possibilities:

```text
4 packages = 48 pieces → 2 pieces too few
5 packages = 60 pieces → 10 pieces too many
```

It does not automatically choose one because action medeor has not confirmed whether the system
should round up, round down or ask the user.

Therefore, the output contains both options and a warning:

```text
Rounding policy is not confirmed; no option was auto-selected.
```

## Step 7: Inspect availability

**Responsible code:** [`packaging.py`](packaging.py), specifically `observed_availability`, compares
the requested amount with confirmed and unit-compatible on-hand stock.

For product `410001001`:

```text
Required: 50 pieces
On hand: 80 pieces
Result: sufficient
```

For product `410001002`:

```text
Required: 50 pieces
On hand: 500 pieces
Result: sufficient
```

The CH12 product does not win merely because it has more stock. Product suitability and review status
come before availability.

The current code only uses confirmed, comparable on-hand stock. It does not yet calculate a
sophisticated “available to offer” value from incoming orders, commitments and inquiries because the
exact business meaning of those fields has not been confirmed.

## Step 8: Rank the remaining products

**Responsible code:** [`ranking/features.py`](ranking/features.py) creates the inspectable ranking
components and [`ranking/ranker.py`](ranking/ranker.py) applies the deterministic ordering.

The current ordering is:

1. fully passing products before products requiring review;
2. exact article-number matches;
3. stronger structured-attribute agreement;
4. combined search rank;
5. comparable availability;
6. article number as a stable final tie-breaker.

Therefore, the result is:

| Rank | Product | Outcome | Why |
|---:|---|---|---|
| 1 | `410001001` | Pass | CH18, sterile, active and enough stock |
| 2 | `410001002` | Review | CH12 differs from requested CH18 |
| — | `410001003` | Excluded | Article is inactive |

The output contains two products, not ten. “Top 10” means up to ten; the framework never fills missing
positions with unsuitable products.

## Step 9: Return an explained result

**Responsible code:** [`service.py`](service.py) assembles the final candidates,
[`contracts.py`](contracts.py) defines the response format and [`api.py`](api.py) exposes it through
HTTP.

For every returned product, the API includes:

- article number and rank;
- why each search method found it;
- rule results and mismatching values;
- packaging alternatives;
- availability status;
- warnings;
- source information;
- algorithm, rule and embedding-model versions.

It deliberately does not return a statement such as “93% correct.” The current search scores have not
been calibrated as correctness probabilities.

## Step 10: Store the human decision

**Responsible code:** [`feedback.py`](feedback.py) validates the decision against the displayed
candidates, [`adapters/persistence.py`](adapters/persistence.py) stores it and [`api.py`](api.py)
provides the decision endpoint.

The employee can subsequently record:

- accept the suggested product;
- choose another displayed candidate;
- create a manual match;
- state that there is no match;
- state that procurement is required.

The system verifies that an accepted suggestion was actually shown in that matching run.

The decision is stored, but it does not immediately modify the algorithm. That avoids unsafe learning
from accidental clicks. The decisions form a clean dataset for later offline evaluation and
controlled learning.

## What is genuinely implemented now?

| Area | Current status |
|---|---|
| Input contracts and validation | Implemented |
| Exact and lexical search | Implemented |
| Vector storage and search with pgvector | Implemented |
| Historical search | Implemented |
| Candidate-list fusion | Implemented |
| Conservative rules | Implemented |
| Packaging calculation | Implemented |
| Basic stock comparison | Implemented |
| Deterministic ranking | Implemented |
| API and decision storage | Implemented |
| Database schema and migrations | Implemented |
| Automated tests | Implemented |

## What is not yet operational?

| Area | Current reality |
|---|---|
| Excel/Outlook extraction | Must be built by the extraction workstream |
| Lagerliste import | No production import process yet |
| Filled product database | Schema exists, but the migration does not import the products |
| Production embeddings | Storage/search exists; real multilingual model is not selected |
| Automatic query embeddings | API currently needs a precomputed embedding unless a provider is configured |
| ERP and SharePoint synchronization | Interfaces exist, but no live connector |
| Supplier availability | Not connected |
| Price, shelf-life and reliability ranking | Not active because comparable data and rules are missing |
| Active learning | Decisions are stored, but the ranking does not learn from them yet |
| Figma UI integration | Not implemented and the UI branch remains untouched |

So the current code is a working, tested matching core—not yet a complete production workflow. The
next major milestone is to feed it real normalized catalogue and inquiry data and select/evaluate a
production multilingual embedding model.
