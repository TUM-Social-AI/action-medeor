# Local supplier-offer extraction

This prototype extracts supplier quotations from `.xlsx`, `.xls`, and selectable-text PDF files
using the backend's configured LLM client. It has no Graph or database calls and does not change
the scheduled SharePoint job or request extraction.

See [EVALUATION.md](EVALUATION.md) for the measured results and remaining differences.

From the repository root, after installing backend development dependencies:

```bash
cd apps/backend
uv sync --group dev
cd ../..
apps/backend/.venv/bin/python benchmarks/offer-extraction/fixtures.py
apps/backend/.venv/bin/python benchmarks/offer-extraction/run.py --output-dir benchmarks/offer-extraction/reports/luna-v3
```

The fixture command requires the five supplied workbooks under `data/anonymized data`. It writes
eight deterministic, fictional invoice-style quotation PDFs directly into that directory and
`offer-extraction-labels.json`. It never changes the workbooks. Workbook labels use explicit,
source-reviewed row selections and date/reference annotations; PDF labels come from fixture
definitions. Neither uses a model. Labels are never passed to the extractor. Source hashes
prevent evaluating changed documents against stale labels. The entire `data/` directory and
benchmark reports remain ignored by Git, consistent with existing private-data handling.

The runner defaults to two passes and three concurrent documents, requires the configured
deployment to be `gpt-6-luna`, and loads `apps/backend/.env` independently of the launch directory.
Azure uses the existing endpoint/key settings. No credentials are recorded in reports.
[Official model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
lists structured outputs as supported; actual quality is measured locally.

Select particular labelled documents:

```bash
apps/backend/.venv/bin/python benchmarks/offer-extraction/run.py --documents 'synthetic_offer_*' --passes 2 --workers 2 --output-dir /tmp/offer-pdf-evaluation
```

Extract a new local file without labels:

```bash
apps/backend/.venv/bin/python benchmarks/offer-extraction/extract.py 'data/anonymized data/synthetic_offer_01_equipment.pdf' --output /tmp/extracted-offer.json
```

The reusable Python entrypoint is `app.offers.extraction.extract_offers(content, filename)`.
It returns `OfferExtraction`: per-item/supplier/alternative records, source evidence, warnings,
failed chunks, prompt version and chunk counts. It accepts an injected LLM callable for offline
tests. It does not return the single-record `NormalizedOfferUpsertV1` contract; a future integration
must handle multiple offers per file explicitly rather than discard all but one item.

## Interpretation

- Source rows, supplier blocks and alternatives remain separate. Unknown suppliers are null;
  brands in descriptions are not treated as suppliers. Enquiry-only, declined and internal
  stock instructions are excluded. Concrete offered products count even without prices/dates.
- Prices retain their original quoted amount, currency and explicit denominator. `/100` or
  `/4` prices are never divided. Conflicting textual/numeric prices keep both raw evidence
  values and have no selected amount. Packaging is not a pricing denominator unless stated.
- Full document-stated dates are ISO dates, without invented times/timezones. Two-digit years
  in dated offers expand to `20YY`; month/year-only statements remain incomplete. Product
  shelf life, requested shelf life, delivery times and template revision dates are separate.
  Relative validity is preserved as text without computing an expiry date.
- Local missing dates stay null. The planned SharePoint creation-timestamp fallback is not
  implemented here. Before adding persistence, retain the fallback's provenance and distinguish
  it from a document-stated date.
- Readers retain every sheet/page, coordinates, merged ranges, number formats, cached values
  and formulas. Formulas without cached values are not evaluated. Excel chunks repeat headers
  and stop at full rows. PDF chunks retain full pages where possible, otherwise full text lines
  and table rows; first-page context accompanies continuation pages. An oversized indivisible
  row/context fails explicitly rather than silently truncating.
- Scanned/empty PDF pages produce warnings; corrupt files, unsupported extensions and API/schema
  failures are explicit failures. Partial model failures preserve successful chunks. Source
  excerpts are checked against actual source text; unverified/missing evidence is flagged.

`report.md` contains offer precision/recall, per-field populated accuracy, missing-value accuracy,
synthetic critical checks, timings and representative discrepancies. `results.json` contains
full structured output, evidence and every discrepancy; `pass-N.json` checkpoints retain
completed documents if a run is interrupted. Scores use case/whitespace-normalized exact
matches with a small documented set of unit aliases; price amounts use exact decimal equality.
Missing offers count as incorrect fields. Consistency compares scored values and identities,
excluding wording changes in source excerpts/warnings.

The initial quality target is 95% populated-field accuracy plus all synthetic critical checks.
Report failures honestly; a small, partially sparse and synthetic corpus does not establish
production readiness. Preserve earlier reports when changing the prompt. The first baseline
is `reports/luna-v1`; subsequent runs are `reports/luna-v2` and `reports/luna-v3`.
The final fixtures remove a contradictory "no real commercial offer" footer that caused one
model run to treat a synthetic quotation as declined, and use consistent invoice totals.
Earlier reports retain their original source hashes, so those PDFs differ from the current
fixtures. Original workbooks are identical across all versions.

## Offline checks

```bash
cd apps/backend
uv run pytest tests/test_offer_extraction.py tests/test_parsing.py tests/test_llm_client.py tests/test_llm_table_classifier.py tests/test_custom_columns.py -q
```

ReportLab is a development dependency used by fixture generation/tests, not by the extractor.
