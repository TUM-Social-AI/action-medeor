# Allocura

Full-stack monorepo for the Allocura project.

## Stack

- Frontend: Vite, React, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, SQLAlchemy asyncio
- Package managers: pnpm for frontend workspaces, uv for Python
- Runtime/deployment: Docker Compose with PostgreSQL 16 and pgvector

## Project Layout

```text
apps/
  frontend/   Vite React app
  backend/    FastAPI app managed with uv
docker-compose.yml
pnpm-workspace.yaml
```

## Local Development

Backend:

```bash
cd apps/backend
uv sync
uv run uvicorn app.main:app --reload
```

Frontend:

```bash
corepack enable
pnpm install
pnpm --filter @allocura/frontend dev
```

Database only for local development:

```bash
docker compose up -d db
cd apps/backend
uv run alembic upgrade head
```

Docker:

```bash
docker compose up --build
```

The database service uses PostgreSQL 16 with the pgvector extension and remains available as
`allocura` on `localhost:5432`. When running the backend directly on your machine, use:

```bash
DATABASE_URL=postgresql+asyncpg://allocura:allocura@localhost:5432/allocura
```

The frontend runs at `http://localhost:3000`, and the backend runs at `http://localhost:8000`.
FastAPI docs are available at `http://localhost:8000/docs`.

## Product Matching

The backend now contains an explainable matching foundation for normalized medicine and medical-
equipment inquiries. It combines exact, lexical, vector, and historical retrieval, applies
conservative versioned constraints, calculates packaging and availability evidence, and stores both
matching runs and subsequent human decisions. Source extraction from Excel, Outlook, SharePoint, or
ERP systems remains outside the matching package, and no frontend integration is included yet.

```text
POST /api/v1/match-runs
GET  /api/v1/match-runs/{match_run_id}
POST /api/v1/match-decisions
```

See the matching [overview](apps/backend/app/matching/README.md) and
[detailed architecture](apps/backend/app/matching/README_DETAILED.md). Complete German versions are
available for the [overview](apps/backend/app/matching/README_DE.md) and
[detailed architecture](apps/backend/app/matching/README_DETAILED_DE.md).

## Environment

Copy `.env.example` to `.env` for Docker Compose overrides.

```bash
cp .env.example .env
```

The first database target is PostgreSQL with pgvector so local Docker and deployment use the same
shape. The backend keeps the database behind `DATABASE_URL`, so it can be swapped later.
