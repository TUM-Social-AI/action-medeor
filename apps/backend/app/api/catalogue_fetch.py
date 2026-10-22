"""Start SharePoint sync locally in development or through Azure in production."""

import logging
import os
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import SharePointSyncRunRow
from app.db.session import get_session
from app.jobs.sharepoint_sync import required_config
from app.sharepoint.local_sync import SyncAlreadyRunning, start_local_sync
from app.sharepoint.run_status import STALE_SECONDS

router = APIRouter(prefix="/api/v1/catalogue/fetch", tags=["catalogue"])
logger = logging.getLogger(__name__)
ARM_ORIGIN = "https://management.azure.com"
JOB_RESOURCE_ID = re.compile(
    r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/?#\s]+"
    r"/providers/Microsoft\.App/jobs/[-\w.()]+"
)
AZURE_ERROR_CODES = frozenset({
    "AuthorizationFailed", "DenyAssignmentAuthorizationFailed", "LinkedAuthorizationFailed",
    "InvalidAuthenticationToken", "InvalidAuthenticationTokenTenant", "AuthenticationFailed",
    "ResourceNotFound", "ResourceGroupNotFound", "SubscriptionNotFound",
    "InvalidSubscriptionId", "InvalidApiVersionParameter", "NoRegisteredProviderFound",
    "MissingSubscriptionRegistration", "InvalidRequestContent", "BadRequest", "Conflict",
    "TooManyRequests", "InternalServerError", "ServiceUnavailable",
    "invalid_request", "invalid_client", "invalid_resource", "unauthorized_client",
})


class AzureJobRequestError(Exception):
    """Safe Azure diagnostics; never retain a response body, token, or request headers."""

    def __init__(self, stage: Literal["identity", "start"], response: httpx.Response):
        self.stage = stage
        self.status_code = response.status_code
        self.azure_code = None
        self.request_id = None
        try:
            error = response.json().get("error")
            code = error.get("code") if isinstance(error, dict) else error
            if isinstance(code, str) and code in AZURE_ERROR_CODES:
                self.azure_code = code
        except (ValueError, AttributeError):
            pass
        for header in ("x-ms-correlation-request-id", "x-ms-request-id"):
            try:
                self.request_id = str(UUID(response.headers[header]))
                break
            except (KeyError, ValueError):
                pass
        super().__init__("Azure job request failed")

    def public_detail(self) -> str:
        diagnostic = f"Azure HTTP {self.status_code}"
        if self.azure_code:
            diagnostic += f", {self.azure_code}"
        if self.stage == "identity":
            return (
                f"The web app could not authenticate with its managed identity ({diagnostic}). "
                "Check the web app's identity configuration. For a system-assigned identity, "
                "leave AZURE_JOB_MANAGED_IDENTITY_CLIENT_ID empty."
            )
        if self.status_code == 403:
            return (
                f"Azure denied the job start ({diagnostic}). The web app's managed identity "
                "needs Microsoft.App/jobs/start/action on the configured SharePoint job."
            )
        if self.status_code == 404:
            return (
                f"Azure could not find the configured SharePoint job ({diagnostic}). "
                "Check AZURE_SHAREPOINT_JOB_RESOURCE_ID on the web app."
            )
        if self.status_code == 401:
            return f"Azure rejected the web app's managed identity token ({diagnostic}). Check its identity and tenant."
        return (
            f"Azure could not start the SharePoint job ({diagnostic}). "
            "Check the job's Activity log and execution history before trying again."
        )


class FetchAvailability(BaseModel):
    enabled: bool
    reason: str | None = None


class FetchAccepted(BaseModel):
    status: str = "accepted"
    execution_name: str | None = None
    requested_at: datetime
    execution_mode: Literal["azure", "local"] = "azure"


class SyncRunStatus(BaseModel):
    id: UUID
    execution_name: str | None
    status: Literal["running", "completed", "failed", "skipped", "stale"]
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    summary: dict[str, int | bool]
    message: str | None


class SyncStatus(BaseModel):
    runs: list[SyncRunStatus]


def local_backend(settings: Settings) -> bool:
    return settings.app_env.lower() == "development" and not os.environ.get("CONTAINER_APP_NAME")


@router.get("/status", response_model=SyncStatus)
async def sync_status(
    request: Request, response: Response,
    settings: Settings = Depends(get_settings), session: AsyncSession = Depends(get_session),
) -> SyncStatus:
    if settings.app_env.lower() == "production" and not request.headers.get("x-ms-client-principal-id"):
        raise HTTPException(status_code=401, detail="Sign in to view sync status.")
    job_name = settings.azure_sharepoint_job_resource_id.rsplit("/", 1)[-1] or "sharepoint-sync"
    rows = (await session.scalars(
        select(SharePointSyncRunRow).where(SharePointSyncRunRow.job_name == job_name)
        .order_by(SharePointSyncRunRow.updated_at.desc(), SharePointSyncRunRow.id.desc()).limit(20)
    )).all()
    now = datetime.now(UTC)
    runs = []
    for row in rows:
        stale = row.status == "running" and (now - row.updated_at).total_seconds() > STALE_SECONDS
        runs.append(SyncRunStatus(
            id=row.id, execution_name=row.execution_name,
            status="stale" if stale else row.status,
            started_at=row.started_at, updated_at=row.updated_at, finished_at=row.finished_at,
            summary=row.summary,
            message=(
                "No recent update from the job. Check the backend logs." if local_backend(settings)
                else "No recent update from the job. Check its Azure execution logs."
            ) if stale else row.message,
        ))
    response.headers["Cache-Control"] = "no-store"
    return SyncStatus(runs=runs)


def availability(request: Request, settings: Settings) -> FetchAvailability:
    if local_backend(settings):
        try:
            required_config(settings)
        except ValueError as exc:
            return FetchAvailability(enabled=False, reason=str(exc))
        return FetchAvailability(enabled=True)
    # Deliberately no Azure CLI, developer login, or service-principal fallback.
    if not os.environ.get("CONTAINER_APP_NAME"):
        return FetchAvailability(enabled=False, reason="Fetching is available in the Azure app only.")
    if settings.app_env.lower() != "production":
        return FetchAvailability(
            enabled=False, reason="Fetching is disabled because this deployment is not set to production."
        )
    if not all(os.environ.get(key) for key in ("IDENTITY_ENDPOINT", "IDENTITY_HEADER")):
        return FetchAvailability(enabled=False, reason="The web app's managed identity is not available.")
    if not JOB_RESOURCE_ID.fullmatch(settings.azure_sharepoint_job_resource_id):
        return FetchAvailability(enabled=False, reason="The SharePoint job has not been configured.")
    if not re.fullmatch(
        r"https://[^/?#\s]+", settings.azure_job_app_origin
    ):
        return FetchAvailability(enabled=False, reason="The Azure app address has not been configured.")
    # These headers are trusted only behind Container Apps' required-authentication ingress.
    if not request.headers.get("x-ms-client-principal-id"):
        return FetchAvailability(enabled=False, reason="Sign in to fetch new data.")
    return FetchAvailability(enabled=True)


@router.get("", response_model=FetchAvailability)
async def fetch_availability(
    request: Request, response: Response, settings: Settings = Depends(get_settings)
) -> FetchAvailability:
    response.headers["Cache-Control"] = "no-store"
    return availability(request, settings)


async def start_azure_job(settings: Settings) -> str | None:
    """Use only the managed identity endpoint injected by Azure Container Apps."""
    token_params = {"resource": ARM_ORIGIN + "/", "api-version": "2019-08-01"}
    if settings.azure_job_managed_identity_client_id:
        token_params["client_id"] = settings.azure_job_managed_identity_client_id
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        token_response = await client.get(
            os.environ["IDENTITY_ENDPOINT"],
            params=token_params,
            headers={"X-IDENTITY-HEADER": os.environ["IDENTITY_HEADER"]},
        )
        if token_response.status_code != 200:
            raise AzureJobRequestError("identity", token_response)
        token = token_response.json()["access_token"]
        if not isinstance(token, str) or not token:
            raise ValueError("Missing managed identity access token")
        # No execution overrides, credentials, or caller-supplied job identifiers.
        result = await client.post(
            ARM_ORIGIN + settings.azure_sharepoint_job_resource_id + "/start",
            params={"api-version": "2025-07-01"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if result.status_code not in (200, 202):
            raise AzureJobRequestError("start", result)
        # Azure may accept asynchronously and return an empty body.
        if not result.content:
            return None
        try:
            name = result.json().get("name")
        except (ValueError, AttributeError):
            # A confirmed start stays successful even if Azure omits readable execution metadata.
            return None
        return name if isinstance(name, str) else None


@router.post("", status_code=202, response_model=FetchAccepted)
async def fetch_new_data(
    request: Request, response: Response, settings: Settings = Depends(get_settings)
) -> FetchAccepted:
    allowed = availability(request, settings)
    if not allowed.enabled:
        raise HTTPException(status_code=403, detail=allowed.reason)
    if local_backend(settings):
        origin = request.headers.get("origin", "")
        trusted_origin = (
            origin == str(request.base_url).rstrip("/")
            or origin in settings.cors_origin_list
            or bool(settings.cors_origin_regex and re.fullmatch(settings.cors_origin_regex, origin))
        )
        if not trusted_origin or request.headers.get("x-catalogue-fetch") != "true":
            raise HTTPException(status_code=403, detail="Start fetching from the local app.")
        requested_at = datetime.now(UTC)
        job_name = settings.azure_sharepoint_job_resource_id.rsplit("/", 1)[-1] or "sharepoint-sync"
        try:
            execution_name = await start_local_sync(job_name)
        except SyncAlreadyRunning:
            raise HTTPException(status_code=409, detail="A SharePoint fetch is already running.") from None
        response.headers["Cache-Control"] = "no-store"
        return FetchAccepted(
            execution_name=execution_name, requested_at=requested_at, execution_mode="local",
        )
    if (
        request.headers.get("origin") != settings.azure_job_app_origin
        or request.headers.get("x-catalogue-fetch") != "true"
        or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
    ):
        raise HTTPException(status_code=403, detail="Start fetching from the Azure app.")
    try:
        requested_at = datetime.now(UTC)
        execution_name = await start_azure_job(settings)
    except httpx.TimeoutException:
        # Never retry a start automatically: Azure might already have accepted it.
        raise HTTPException(
            status_code=504,
            detail="Azure did not respond in time. Check job executions before trying again.",
        ) from None
    except AzureJobRequestError as exc:
        logger.warning(
            "Azure catalogue job start failed stage=%s status=%s code=%s request_id=%s",
            exc.stage, exc.status_code, exc.azure_code or "unknown", exc.request_id or "unavailable",
        )
        raise HTTPException(status_code=502, detail=exc.public_detail()) from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Exception messages and Azure bodies can contain internal URLs or credentials.
        logger.warning("Azure catalogue job start failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="Could not start the Azure job. Check its configuration and managed identity permissions.",
        ) from None
    logger.info("Catalogue fetch accepted for user %s", request.headers["x-ms-client-principal-id"])
    response.headers["Cache-Control"] = "no-store"
    return FetchAccepted(execution_name=execution_name, requested_at=requested_at)
