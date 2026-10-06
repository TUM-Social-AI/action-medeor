"""Display identity and avatar preferences supplied by Azure built-in authentication."""

import base64
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserAvatarPreferenceRow, UserExtractionPreferenceRow
from app.db.session import get_session

router = APIRouter(prefix="/api/me")
AVATAR_IDS = ("cat", "fox", "panda", "rabbit", "bear", "owl")
AvatarId = Literal["cat", "fox", "panda", "rabbit", "bear", "owl"]


class AvatarPreference(BaseModel):
    avatarId: AvatarId


def _display_name(request: Request) -> str:
    principal = request.headers.get("x-ms-client-principal")
    if principal:
        try:
            payload = json.loads(base64.b64decode(principal, validate=True))
            claims = payload.get("claims", [])
            for claim_type in ("name", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"):
                for claim in claims:
                    if claim.get("typ") == claim_type and isinstance(claim.get("val"), str):
                        name = claim["val"].strip()
                        if name and "@" not in name:
                            return name
        except (ValueError, TypeError, AttributeError, KeyError):
            pass

    name = request.headers.get("x-ms-client-principal-name", "").strip()
    return name or "Local User"


def _user_id(request: Request) -> str:
    return request.headers.get("x-ms-client-principal-id") or "local"


def _default_avatar(user_id: str) -> AvatarId:
    index = int.from_bytes(hashlib.sha256(user_id.encode()).digest()[:4], "big") % len(AVATAR_IDS)
    return AVATAR_IDS[index]


@router.get("")
async def current_user(request: Request) -> dict[str, str]:
    return {"displayName": _display_name(request)}


@router.get("/avatar")
async def get_avatar(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AvatarPreference:
    user_id = _user_id(request)
    preference = await session.get(UserAvatarPreferenceRow, user_id)
    return AvatarPreference(avatarId=preference.avatar_id if preference else _default_avatar(user_id))


@router.put("/avatar")
async def put_avatar(
    request: Request,
    choice: AvatarPreference,
    session: AsyncSession = Depends(get_session),
) -> AvatarPreference:
    statement = insert(UserAvatarPreferenceRow).values(
        user_id=_user_id(request), avatar_id=choice.avatarId
    ).on_conflict_do_update(
        index_elements=[UserAvatarPreferenceRow.user_id], set_={"avatar_id": choice.avatarId}
    )
    await session.execute(statement)
    await session.commit()
    return choice


class ExtractionPreference(BaseModel):
    mode: Literal["basic", "balanced"] = "balanced"


async def extraction_mode(request: Request, session: AsyncSession) -> str:
    preference = await session.get(UserExtractionPreferenceRow, _user_id(request))
    return preference.mode if preference else "balanced"


@router.get("/extraction-preferences")
async def get_extraction_preferences(
    request: Request, session: AsyncSession = Depends(get_session)
) -> ExtractionPreference:
    return ExtractionPreference(mode=await extraction_mode(request, session))


@router.put("/extraction-preferences")
async def put_extraction_preferences(
    request: Request, choice: ExtractionPreference, session: AsyncSession = Depends(get_session)
) -> ExtractionPreference:
    statement = (
        insert(UserExtractionPreferenceRow)
        .values(user_id=_user_id(request), mode=choice.mode)
        .on_conflict_do_update(
            index_elements=[UserExtractionPreferenceRow.user_id], set_={"mode": choice.mode}
        )
    )
    await session.execute(statement)
    await session.commit()
    return choice
