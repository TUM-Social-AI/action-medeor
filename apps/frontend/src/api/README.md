# Frontend API boundaries

The frontend keeps transport contracts separate from React view models. This lets the current UI run
against fixture-backed workflow routes while the real APIs are developed on separate branches.

## Current fixture workflow

`client.ts` contains the existing screen-oriented `/api/...` client. Those routes currently return
backend fixtures and remain unchanged so the UI branch keeps working.

## Matching API

`matching/contracts.ts` mirrors the implemented matching V1 boundary:

```text
POST /api/v1/match-runs
GET  /api/v1/match-runs/{match_run_id}
POST /api/v1/match-decisions
```

Components should consume the view models in `features/matching/models.ts`, not matching DTOs
directly. `features/matching/mapper.ts` owns the conversion. Retrieval scores are evidence, not
calibrated percentages, and must not be displayed as confidence percentages.

## Extraction API

`extraction/` is a proposed boundary for the extraction workstream:

```text
POST  /api/v1/inquiries
POST  /api/v1/inquiries/{inquiry_id}/files
GET   /api/v1/inquiries/{inquiry_id}
GET   /api/v1/inquiries/{inquiry_id}/lines
PATCH /api/v1/inquiry-lines/{line_id}
POST  /api/v1/inquiry-lines/{line_id}/validate
```

These paths are intentionally hidden behind `ExtractionApi`; the team can revise them without
changing React components. A validated extraction line includes a normalized `InquiryLineV1`, which
is the handoff contract to matching.

## Identifier flow

```text
inquiry_id
  -> extraction_id
    -> line_id
      -> match_run_id
        -> candidate_id
          -> decision_id
```

`features/workflow/model.ts` preserves these relationships. Avoid introducing new hard-coded request
IDs when connecting real screens.

## Current matching-screen adapter

`features/matching/fixture-api.ts` adapts the existing fixture response to the same UI view model that
real matching will use. `SmartMatchingScreen` depends on `MatchingWorkflowApi`, not fixture DTOs or
HTTP functions. When a real multi-line orchestrator is available, it can replace this adapter without
rewriting the screen.

`features/matching/real-api.ts` implements the real handoff. It loads extraction lines, matches only
validated rows, calls `POST /api/v1/match-runs` once per row, aggregates partial successes, and sends
candidate choices to `POST /api/v1/match-decisions`. Selecting a non-first candidate requires an
explicit override reason, matching the backend contract.
