# Article Catalogue

The sidebar screen reads current ERP articles and active, normalized SharePoint offers from
`GET /api/v1/catalogue/articles`. It shows whether each current article or offer has a stored
embedding. The screen does not initiate imports or extraction.

## Deferred: Fetch new data

The **Fetch new data** button is intentionally disabled. When this control is implemented,
have a backend endpoint trigger the existing Azure scheduled job asynchronously and return a
job/run identifier promptly. The frontend should poll or subscribe to that run's status.
It should not run ERP sync, SharePoint scanning, extraction, or embedding work in the HTTP
request, and it should not display simulated progress or success.
