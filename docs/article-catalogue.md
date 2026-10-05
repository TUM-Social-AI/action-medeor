# Article Catalogue

The sidebar screen reads current ERP articles and active, normalized SharePoint offers from
`GET /api/v1/catalogue/articles`. It shows whether each current article or offer has a stored
embedding. ERP imports are available through **Update ERP catalogue**; supplier extraction remains
separate.

Restricted ERP articles use a muted striped row with restriction badges. Suspended and sales-blocked
articles show **Excluded from matching** and calculated available stock. Purchase-blocked articles show
**Stock-only matching** and the same calculated quantity, displayed once. The
purchasing badge explains that the available quantity must cover the complete request. Raw warehouse
stock is not displayed in the catalogue. ERP references are crossed out for articles excluded
from matching.

To add the requested database-backed example explicitly, run from `apps/backend`:
`uv run python -m app.jobs.seed_suspended_example`. It adds **ERP-51108**, **Infusion Set 20 drops/ml,
Luer Lock**, from **FlowMed GmbH**, with **340 pcs** available. Its source metadata identifies it as
sample data.
The command is transactional, safe to repeat, and refuses to overwrite an existing ERP identity.
The example participates in normal catalogue counts, search, and filters, remains excluded from
matching and embeddings, and survives CSV uploads. It never runs automatically at startup and does
not create an import or change the current matching snapshot.
No suspension date, reason, replacement article, or responsible person is collected or displayed:
the ERP exports do not provide those details.

The table uses fixed proportional column widths. Long offer availability text and price bases wrap;
offer filenames truncate within their column and remain available in the link tooltip. Desktop
layouts fit the available width; narrow layouts keep horizontal scrolling inside the table.

## Update ERP catalogue

The separate **Update ERP catalogue** button uploads the complete current Artikeldaten and
Artikelübersetzungen exports to `POST /api/v1/catalog-imports` as `article_data` and
`article_translations`. Both must be UTF-8, semicolon-separated CSV files, up to 25 MB each.
The dialog labels these **Article data** and **Article translations**, with styled **Choose file**
buttons and **No file selected** placeholders independent of the browser's language.
New uploads require `Gesperrt`, `Verkauf gesperrt`, and `Einkauf gesperrt`. Only a trimmed,
case-insensitive `ja` activates a restriction. Blank and unexpected values default to unblocked;
unexpected nonempty values produce import warnings. Existing database versions lacking these flags
continue to work as unblocked articles. Old-format uploads are rejected.

Inventory refreshes for every article. Stock is `Lagerbestand - Menge in Bestellung + Menge in
Auftrag`, clamped to zero for sellable availability while retaining the raw negative result in
article detail. Article numbers ending in `00` without `Nummer 2` are **Stammartikel**. Their
availability cell shows that label instead of misleading zero stock. They remain visible and never
match, including articles imported under the previous `000` rule.

Read-only local database audit on 5 October 2026: the imported checksum matched the original
`Artikeldaten.csv`. All 2,773 articles' latest on-hand, purchase-order, and sales-order quantities
matched that CSV exactly. With the corrected availability formula, 2,193 have zero sellable stock;
1,136 of those are Stammartikel, and 72 articles have negative raw availability. The stored source
quantities showed no import discrepancies. This audit did not import the newer exports.

Restricted articles remain visible with **Suspended**, **Sales blocked**, and **Purchasing blocked**
badges. The **Suspended** filter includes all three restrictions. Fully blocked and sales-blocked
articles never match. Purchase-blocked articles match only when known, comparable stock covers the
entire requested quantity. Piece and package aliases are normalized; unknown packaging is never
inferred. Restrictions and stock use the matching snapshot. Existing results and queued requests
remain unchanged; newly started requests use the latest import.

Matching shows the snapshot's calculated available quantity in the ERP unit even when the requested
quantity cannot be compared. For example, **50 PAKET available** can appear alongside **Request
quantity not comparable** for a request in rolls. The inventory is known; the conversion is missing.
Stored historical runs without quantity fields load their display quantity and unit from their
saved import snapshot. Early runs without an explicit snapshot use the completed import available
when they started. This is read-only response enrichment: saved results, ranking, and decisions are
not recomputed or rewritten, and newer inventory never replaces historical stock. If no historical
stock can be recovered, the UI still reports that the quantity is unavailable.
Matching cards and the order summary show the calculated available quantity instead of a stock
status label. The number is green for sufficient stock, orange when sufficient stock is at most
110% of the requested quantity, and red for insufficient stock. This margin uses the request
expressed in the ERP stock unit, including confirmed package conversions. Unknown comparisons
stay grey, with an explanation on hover and for screen readers.

Unambiguous unit aliases such as `PAKET`/packs, `STÜCK`/pcs, `FLASCHE`/bottles, `PAAR`/pairs,
`ROLLE`/rolls and `TUBE`/tubes compare directly. Matching does not require a package size when the
request already uses the ERP stock unit. A pack-to-content conversion needs confirmed article-specific
`units_per_package`, its contained `unit`, and the ERP `stock_unit`. The confirmed ERP naming convention
provides these through the final comma-separated segment in `Beschreibung`: `24 Rollen` means
24 rolls per ERP unit, `tablets, 1000` means 1,000 tablets, `10 x 10` multiplies the counts, and
`2 Dtzd.` means 24 pieces. A bare number needs an unambiguous contained-unit word in the name.
Dimensions, strength, volume, unclear suffixes, and translations are not used as count fallbacks.
Imports store the structured package in immutable version metadata and the record hash. This
metadata does not add anything to the embedding text hash; unchanged product text reuses vectors.
Existing versions without package metadata derive it from their pinned description and ERP unit,
so no re-upload, database rewrite, or embedding run is needed. Explicit package metadata takes
precedence. Match details show the conversion and identify the ERP description as its source.
Conversions work in both directions, including non-exact package quantities;
the available stock comparison does not automatically choose a rounded supply option.

The dialog shows real import counts, warnings, and checksum replays. Product embeddings are reused
for stock/status-only changes and regenerated for new or changed searchable text. A lifespan worker
drains durable embedding jobs outside upload requests, backfills missing vectors on initialization,
and recovers running jobs older than one hour. It uses the configured active model without switching
an existing active model. If no model is active, it initializes the configured model. Configuration
errors and failed jobs are reported separately from successful inventory updates.

While open, the dialog polls `GET /api/v1/catalog-imports/{import_id}/embedding-status` every five
seconds. Counts cover eligible article versions in that import, including reused vectors. Progress
continues after closing the dialog. Failed jobs remain failed until an operator retries them through
the existing embedding-worker command; automatic startup does not reset them. No schema migration
is needed: flags use versioned metadata and legacy records default to unblocked.

Supplier prices prefer an explicit unit price and its unit; otherwise they show the quoted
offer price with its original basis (for example, `EUR 18.50 / 50 St.`). Missing currencies
and units are not inferred. The price cell identifies whether it is a unit or offer price.
Offers with no known expiry show their age from the offer date alongside **Validity unknown**.
An issue date does not establish current availability or expiry. Estimated dates and calculated
expiry dates keep the same provenance labels as Smart Matching.

## Deferred: Fetch new data

The separate **Fetch new data** button is intentionally disabled and reserved for SharePoint.
When this control is implemented,
have a backend endpoint trigger the existing Azure scheduled job asynchronously and return a
job/run identifier promptly. The frontend should poll or subscribe to that run's status.
It should not run SharePoint scanning, extraction, or embedding work in the HTTP
request, and it should not display simulated progress or success.

## Filter counts

Status is a single selection. Changing the source resets status to **All statuses**.
Search applies to every count. Source counts also apply the category filter; category counts
apply source and status; status counts apply source and category. Each filter therefore shows
how many articles choosing an option would return, while keeping alternatives available.
The header badges and the matching article count include all active filters.
Zero-count categories and statuses stay visible but cannot be selected; a selected option
remains enabled so it can always be cleared. Offer validity follows the Berlin calendar day
and refreshes when the day changes or the browser tab resumes.
