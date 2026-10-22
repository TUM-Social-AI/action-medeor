"""Start the configured Azure job through the authenticated web app."""

import logging
import os
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/api/v1/catalogue/fetch", tags=["catalogue"])
logger = logging.getLogger(__name__)
ARM_ORIGIN = "https://management.azure.com"
JOB_RESOURCE_ID = re.compile(
    r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/?#\s]+"
    r"/providers/Microsoft\.App/jobs/[-\w.()]+"
)


class FetchAvailability(BaseModel):
    enabled: bool
    reason: str | None = None


class FetchAccepted(BaseModel):
    status: str = "accepted"
    execution_name: str | None = None


def availability(request: Request, settings: Settings) -> FetchAvailability:
    # Deliberately no Azure CLI, developer login, or service-principal fallback.
    if settings.app_env.lower() != "production" or not all(
        os.environ.get(key) for key in ("CONTAINER_APP_NAME", "IDENTITY_ENDPOINT", "IDENTITY_HEADER")
    ):
        return FetchAvailability(enabled=False, reason="Fetching is available in the Azure app only.")
    if not JOB_RESOURCE_ID.fullmatch(settings.azure_sharepoint_job_resource_id) or not re.fullmatch(
        r"https://[^/?#\s]+", settings.azure_job_app_origin
    ):
        return FetchAvailability(enabled=False, reason="Fetching has not been configured in Azure.")
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
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        if not isinstance(token, str) or not token:
            raise ValueError("Missing managed identity access token")
        # No execution overrides, credentials, or caller-supplied job identifiers.
        result = await client.post(
            ARM_ORIGIN + settings.azure_sharepoint_job_resource_id + "/start",
            params={"api-version": "2025-07-01"},
            headers={"Authorization": f"Bearer {token}"},
        )
        result.raise_for_status()
        if result.status_code not in (200, 202):
            raise ValueError("Unexpected Azure job start response")
        # Azure may accept asynchronously and return an empty body.
        if not result.content:
            return None
        name = result.json().get("name")
        return name if isinstance(name, str) else None


@router.post("", status_code=202, response_model=FetchAccepted)
async def fetch_new_data(
    request: Request, response: Response, settings: Settings = Depends(get_settings)
) -> FetchAccepted:
    allowed = availability(request, settings)
    if not allowed.enabled:
        raise HTTPException(status_code=403, detail=allowed.reason)
    if (
        request.headers.get("origin") != settings.azure_job_app_origin
        or request.headers.get("x-catalogue-fetch") != "true"
        or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
    ):
        raise HTTPException(status_code=403, detail="Start fetching from the Azure app.")
    try:
        execution_name = await start_azure_job(settings)
    except httpx.TimeoutException:
        # Never retry a start automatically: Azure might already have accepted it.
        raise HTTPException(
            status_code=504,
            detail="Azure did not respond in time. Check job executions before trying again.",
        ) from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Exception messages and Azure bodies can contain internal URLs or credentials.
        logger.warning("Azure catalogue job start failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="Could not start the Azure job. Check its configuration and managed identity permissions.",
        ) from None
    logger.info("Catalogue fetch accepted for user %s", request.headers["x-ms-client-principal-id"])
    response.headers["Cache-Control"] = "no-store"
    return FetchAccepted(execution_name=execution_name)
