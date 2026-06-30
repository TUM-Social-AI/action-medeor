from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


REQUEST_ID = "SD-2024-0611"


@pytest.mark.asyncio
async def test_home_returns_stats_and_recent_requests() -> None:
    response = await request("GET", "/api/home")

    assert response.status_code == 200
    body = response.json()
    assert body["organization"] == "action medeor"
    assert body["stats"][0]["label"] == "Requests Processed"
    assert body["recentRequests"][0]["id"] == REQUEST_ID


@pytest.mark.asyncio
async def test_cors_allows_localhost_alias_frontend_origin() -> None:
    response = await request(
        "OPTIONS",
        "/api/home",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


@pytest.mark.asyncio
async def test_cors_allows_localhost_dev_server_ports() -> None:
    response = await request(
        "OPTIONS",
        "/api/home",
        headers={
            "Origin": "http://127.0.0.1:5174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


@pytest.mark.asyncio
async def test_recent_imports_returns_supported_file_types() -> None:
    response = await request("GET", "/api/imports/recent")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["fileName"].endswith(".xlsx")
    assert {item["type"] for item in body} <= {"pdf", "xlsx", "xls"}


@pytest.mark.asyncio
async def test_create_import_returns_review_payload() -> None:
    response = await request(
        "POST",
        "/api/imports",
        json={
            "fileName": "Sudan_EmergencyRequest_MSF_June2024.xlsx",
            "fileType": "xlsx",
            "fileSize": 128000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requestId"] == REQUEST_ID
    assert body["counts"]["total"] == 8
    assert body["items"][2]["status"] == "missing"


@pytest.mark.asyncio
async def test_create_import_rejects_mismatched_extension() -> None:
    response = await request(
        "POST",
        "/api/imports",
        json={"fileName": "request.pdf", "fileType": "xlsx", "fileSize": 128000},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_review_returns_extracted_items_and_source_references() -> None:
    response = await request("GET", f"/api/requests/{REQUEST_ID}/review")

    assert response.status_code == 200
    body = response.json()
    assert body["partner"]["partner"] == "MSF Sudan"
    assert body["sourceReferences"][0]["page"] == 3


@pytest.mark.asyncio
async def test_update_item_returns_verified_item() -> None:
    response = await request(
        "PATCH",
        f"/api/requests/{REQUEST_ID}/items/3",
        json={"quantity": 500, "notes": "Quantity confirmed by phone"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["quantity"] == 500
    assert body["status"] == "verified"


@pytest.mark.asyncio
async def test_verify_item_returns_verified_item() -> None:
    response = await request("POST", f"/api/requests/{REQUEST_ID}/items/5/verify")

    assert response.status_code == 200
    assert response.json()["status"] == "verified"


@pytest.mark.asyncio
async def test_update_partner_confirms_details() -> None:
    response = await request(
        "PATCH",
        f"/api/requests/{REQUEST_ID}/partner",
        json={
            "partner": "MSF Sudan",
            "region": "East Sudan (Kassala)",
            "requestId": REQUEST_ID,
            "contact": "Dr. Amira Hassan",
        },
    )

    assert response.status_code == 200
    assert response.json()["confirmed"] is True


@pytest.mark.asyncio
async def test_start_matching_returns_candidates_and_defaults() -> None:
    response = await request("POST", f"/api/requests/{REQUEST_ID}/matching")

    assert response.status_code == 200
    body = response.json()
    assert body["requestedItems"][0]["name"] == "Amoxicillin 500mg Capsules"
    assert body["matches"]["1"][0]["id"] == "erp-001"
    assert body["selectedMatches"]["1"] == "erp-001"


@pytest.mark.asyncio
async def test_update_matching_returns_selected_match() -> None:
    response = await request(
        "PATCH",
        f"/api/requests/{REQUEST_ID}/matching/1",
        json={"matchId": "erp-002"},
    )

    assert response.status_code == 200
    assert response.json() == {"itemId": 1, "matchId": "erp-002"}


@pytest.mark.asyncio
async def test_summary_returns_items_and_metrics() -> None:
    response = await request("GET", f"/api/requests/{REQUEST_ID}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["sku"] == "AM500-CAP-1000"
    assert body["metrics"]["totalLineItems"] == 8


@pytest.mark.asyncio
async def test_create_offer_returns_mock_document_details() -> None:
    response = await request("POST", f"/api/requests/{REQUEST_ID}/offer")

    assert response.status_code == 200
    body = response.json()
    assert body["fileName"] == f"Offer-{REQUEST_ID}.pdf"
    assert body["lineItems"] == 8


@pytest.mark.asyncio
async def test_trends_returns_chart_data() -> None:
    response = await request("GET", "/api/trends")

    assert response.status_code == 200
    body = response.json()
    assert body["demandTrend"][0]["month"] == "Jan"
    assert body["categoryDemand"][0]["risk"] == "high"
    assert body["topItems"][0]["name"] == "Paracetamol 500mg Tablets"


@pytest.mark.asyncio
async def test_unknown_request_returns_404() -> None:
    response = await request("GET", "/api/requests/UNKNOWN/review")

    assert response.status_code == 404


async def request(method: str, url: str, **kwargs: Any) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.request(method, url, **kwargs)
