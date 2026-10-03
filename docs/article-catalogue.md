# Article Catalogue

The sidebar screen reads current ERP articles and active, normalized SharePoint offers from
`GET /api/v1/catalogue/articles`. It shows whether each current article or offer has a stored
embedding. The screen does not initiate imports or extraction.

Supplier prices prefer an explicit unit price and its unit; otherwise they show the quoted
offer price with its original basis (for example, `EUR 18.50 / 50 St.`). Missing currencies
and units are not inferred. The price cell identifies whether it is a unit or offer price.
Offers with no known expiry show their age from the offer date alongside **Validity unknown**.
An issue date does not establish current availability or expiry. Estimated dates and calculated
expiry dates keep the same provenance labels as Smart Matching.

## Deferred: Fetch new data

The **Fetch new data** button is intentionally disabled. When this control is implemented,
have a backend endpoint trigger the existing Azure scheduled job asynchronously and return a
job/run identifier promptly. The frontend should poll or subscribe to that run's status.
It should not run ERP sync, SharePoint scanning, extraction, or embedding work in the HTTP
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
