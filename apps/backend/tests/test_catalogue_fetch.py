import httpx
import pytest
from fastapi import FastAPI

from app.api import catalogue_fetch
from app.core.config import Settings, get_settings

JOB_ID = (
    "/subscriptions/11111111-2222-3333-4444-555555555555"
    "/resourceGroups/rg-allocura/providers/Microsoft.App/jobs/sharepoint-sync"
)
ORIGIN = "https://allocura.example.test"
HEADERS = {
    "x-ms-client-principal-id": "user-1",
    "origin": ORIGIN,
    "x-catalogue-fetch": "true",
    "sec-fetch-site": "same-origin",
}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("CONTAINER_APP_NAME", "allocura")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://identity.test/token")
    monkeypatch.setenv("IDENTITY_HEADER", "private-identity-header")
    settings = Settings(
        _env_file=None,
        app_env="production",
        azure_sharepoint_job_resource_id=JOB_ID,
        azure_job_app_origin=ORIGIN,
    )
    app = FastAPI()
    app.include_router(catalogue_fetch.router)
    app.dependency_overrides[get_settings] = lambda: settings
    return app, settings


async def request(app, method="POST", headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=ORIGIN
    ) as client:
        return await client.request(method, "/api/v1/catalogue/fetch", headers=headers)


@pytest.mark.parametrize("missing", ["CONTAINER_APP_NAME", "IDENTITY_ENDPOINT", "IDENTITY_HEADER"])
async def test_local_calls_cannot_trigger_even_with_forged_user_headers(configured, monkeypatch, missing):
    app, _ = configured
    monkeypatch.delenv(missing)
    assert (await request(app, headers=HEADERS)).status_code == 403
    status = await request(app, "GET", HEADERS)
    assert status.json()["enabled"] is False
    assert status.headers["cache-control"] == "no-store"


async def test_development_remains_disabled_with_azure_configuration(configured):
    app, settings = configured
    settings.app_env = "development"
    assert (await request(app, headers=HEADERS)).status_code == 403
    assert "not set to production" in (await request(app, "GET", HEADERS)).json()["reason"]


@pytest.mark.parametrize("field,value", [
    ("azure_sharepoint_job_resource_id", ""),
    ("azure_sharepoint_job_resource_id", JOB_ID + "/start?override=bad"),
    ("azure_job_app_origin", ""),
    ("azure_job_app_origin", "http://localhost:5173"),
    ("azure_job_app_origin", ORIGIN + "/"),
])
async def test_invalid_or_missing_configuration_is_disabled(configured, field, value):
    app, settings = configured
    setattr(settings, field, value)
    assert (await request(app, headers=HEADERS)).status_code == 403


@pytest.mark.parametrize("field,value", [
    ("x-ms-client-principal-id", None),
    ("origin", None),
    ("origin", "http://localhost:5173"),
    ("origin", "https://untrusted.example"),
    ("x-catalogue-fetch", None),
    ("sec-fetch-site", "cross-site"),
    ("sec-fetch-site", "same-site"),
])
async def test_identity_and_same_origin_are_required(configured, field, value):
    app, _ = configured
    headers = dict(HEADERS)
    if value is None:
        del headers[field]
    else:
        headers[field] = value
    assert (await request(app, headers=headers)).status_code == 403


async def test_availability_does_not_start_a_job(configured, monkeypatch):
    app, _ = configured

    async def unexpected(_settings):
        pytest.fail("GET must not start a job")

    monkeypatch.setattr(catalogue_fetch, "start_azure_job", unexpected)
    assert (await request(app, "GET", HEADERS)).json() == {"enabled": True, "reason": None}
    assert (await request(app, "GET")).json()["enabled"] is False


@pytest.mark.parametrize("status,body,expected", [
    (200, {"name": "sharepoint-sync-abc123"}, "sharepoint-sync-abc123"),
    (202, None, None),
])
async def test_managed_identity_starts_only_configured_job(configured, monkeypatch, status, body, expected):
    app, settings = configured
    calls = []
    original_client = httpx.AsyncClient

    def azure(req):
        calls.append(req)
        if req.url.host == "identity.test":
            assert req.headers["x-identity-header"] == "private-identity-header"
            assert req.url.params["resource"] == "https://management.azure.com/"
            assert req.url.params["api-version"] == "2019-08-01"
            return httpx.Response(200, json={"access_token": "private-arm-token"})
        assert req.method == "POST"
        assert str(req.url) == "https://management.azure.com" + JOB_ID + "/start?api-version=2025-07-01"
        assert req.headers["authorization"] == "Bearer private-arm-token"
        assert req.headers["content-type"] == "application/json"
        assert "x-identity-header" not in req.headers
        assert req.content == b""
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    # Replace only the Azure client; keep ASGI requests using the real client.
    async with original_client(
        transport=httpx.ASGITransport(app=app), base_url=ORIGIN
    ) as client:
        monkeypatch.setattr(
            catalogue_fetch.httpx, "AsyncClient",
            lambda **kwargs: original_client(transport=httpx.MockTransport(azure), **kwargs),
        )
        response = await client.post("/api/v1/catalogue/fetch", headers=HEADERS,
                                     json={"job": "other-job", "containers": [{"image": "bad"}]})
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert response.json()["execution_name"] == expected
    assert response.json()["requested_at"].endswith("Z")
    assert len(calls) == 2
    assert "private" not in response.text


@pytest.mark.parametrize("stage,status,code,detail", [
    ("identity", 400, "invalid_request", "could not authenticate"),
    ("identity", 403, "AuthenticationFailed", "identity configuration"),
    ("start", 403, "AuthorizationFailed", "Microsoft.App/jobs/start/action"),
    ("start", 404, "ResourceNotFound", "AZURE_SHAREPOINT_JOB_RESOURCE_ID"),
    ("start", 401, "InvalidAuthenticationTokenTenant", "identity and tenant"),
    ("start", 429, "TooManyRequests", "execution history"),
    ("start", 400, "InvalidRequestContent", "Activity log"),
    ("start", 500, "private-token", "Azure HTTP 500"),
])
async def test_azure_http_failures_report_safe_stage_status_and_code(
    configured, monkeypatch, caplog, stage, status, code, detail
):
    app, _ = configured
    original_client = httpx.AsyncClient
    calls = []
    request_id = "11111111-2222-3333-4444-555555555555"

    def azure(req):
        calls.append(req)
        if req.url.host == "identity.test" and stage == "start":
            return httpx.Response(200, json={"access_token": "private-arm-token"})
        return httpx.Response(
            status, json={"error": {"code": code, "message": "private-token and internal URLs"}},
            headers={"x-ms-correlation-request-id": request_id, "x-ms-request-id": "private-token"},
        )

    async with original_client(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        monkeypatch.setattr(
            catalogue_fetch.httpx, "AsyncClient",
            lambda **kwargs: original_client(transport=httpx.MockTransport(azure), **kwargs),
        )
        response = await client.post("/api/v1/catalogue/fetch", headers=HEADERS)
    assert response.status_code == 502
    assert detail in response.json()["detail"]
    assert f"Azure HTTP {status}" in response.text
    if code != "private-token":
        assert code in response.text
    assert f"stage={stage} status={status}" in caplog.text
    assert request_id in caplog.text
    assert "private" not in response.text
    assert "private" not in caplog.text
    assert len(calls) == (1 if stage == "identity" else 2)


@pytest.mark.parametrize("body", [b"", b"<html>Accepted</html>", b"[]"])
async def test_accepted_start_with_unreadable_metadata_stays_successful(configured, monkeypatch, body):
    app, _ = configured
    original_client = httpx.AsyncClient

    def azure(req):
        if req.url.host == "identity.test":
            return httpx.Response(200, json={"access_token": "private-arm-token"})
        return httpx.Response(202, content=body)

    async with original_client(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        monkeypatch.setattr(
            catalogue_fetch.httpx, "AsyncClient",
            lambda **kwargs: original_client(transport=httpx.MockTransport(azure), **kwargs),
        )
        response = await client.post("/api/v1/catalogue/fetch", headers=HEADERS)
    assert response.status_code == 202
    assert response.json()["execution_name"] is None


async def test_user_assigned_identity_is_selected_explicitly(configured, monkeypatch):
    _, settings = configured
    settings.azure_job_managed_identity_client_id = "user-assigned-client"
    original_client = httpx.AsyncClient

    def azure(req):
        if req.url.host == "identity.test":
            assert req.url.params["client_id"] == "user-assigned-client"
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(202)

    monkeypatch.setattr(
        catalogue_fetch.httpx, "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(azure), **kwargs),
    )
    assert await catalogue_fetch.start_azure_job(settings) is None


@pytest.mark.parametrize("failure,expected", [("timeout", 504), ("forbidden", 502), ("token", 502)])
async def test_failures_do_not_leak_secrets_or_retry(configured, monkeypatch, failure, expected):
    app, _ = configured
    calls = 0

    async def fail(_settings):
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("private-token")
        if failure == "token":
            raise KeyError("private-token")
        raise httpx.HTTPStatusError(
            "private-token", request=httpx.Request("POST", ORIGIN), response=httpx.Response(403)
        )

    monkeypatch.setattr(catalogue_fetch, "start_azure_job", fail)
    response = await request(app, headers=HEADERS)
    assert response.status_code == expected
    assert "private-token" not in response.text
    assert calls == 1
