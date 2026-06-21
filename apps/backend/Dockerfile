FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app app
COPY alembic.ini alembic.ini
COPY migrations migrations

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
