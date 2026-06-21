from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine

settings = get_settings()

app = FastAPI(title=settings.service_name)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


async def check_database_health() -> dict[str, str]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    return {"status": "ok"}


@app.get("/api/health")
async def health() -> dict[str, Any]:
    database = await check_database_health()
    status = "ok" if database["status"] == "ok" else "degraded"

    return {
        "status": status,
        "service": settings.service_name,
        "environment": settings.app_env,
        "database": database,
    }
