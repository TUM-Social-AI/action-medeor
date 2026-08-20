import asyncio

from sqlalchemy import text

from app.db.session import engine


CREATE_TABLE = text(
    """
    CREATE TABLE IF NOT EXISTS cron_heartbeat (
        id BIGSERIAL PRIMARY KEY,
        job_name TEXT NOT NULL,
        message TEXT NOT NULL,
        ran_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
)

INSERT_HEARTBEAT = text(
    """
    INSERT INTO cron_heartbeat (job_name, message)
    VALUES (:job_name, :message)
    RETURNING id, ran_at
    """
)


async def run_heartbeat() -> None:
    try:
        async with engine.begin() as connection:
            await connection.execute(CREATE_TABLE)

            result = await connection.execute(
                INSERT_HEARTBEAT,
                {
                    "job_name": "allocura-heartbeat",
                    "message": "Scheduled Azure job executed successfully",
                },
            )
            row = result.one()

        print(f"Heartbeat inserted successfully: id={row.id}, ran_at={row.ran_at.isoformat()}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_heartbeat())
