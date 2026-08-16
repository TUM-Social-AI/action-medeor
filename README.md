# Allocura

Full-stack monorepo for the Allocura project.

## Stack

- Frontend: Vite, React, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, SQLAlchemy asyncio
- Package managers: pnpm for frontend workspaces, uv for Python
- Local runtime: Docker Compose with separate frontend, backend, and Postgres services
- Production runtime: one FastAPI/Uvicorn container serving the compiled React application

## Project Layout

```text
apps/
  frontend/   Vite React app
  backend/    FastAPI app managed with uv
docker-compose.yml
Dockerfile
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
```
This starts only Postgres on `localhost:5432`. When running the backend directly on your machine, use:

```bash
DATABASE_URL=postgresql+asyncpg://allocura:allocura@localhost:5432/allocura
```

Docker:

```bash
docker compose up --build
```

The frontend runs at `http://localhost:3000`, and the backend runs at `http://localhost:8000`.
FastAPI docs are available at `http://localhost:8000/docs`.

## Environment

Copy `.env.example` to `.env` for Docker Compose overrides.

```bash
cp .env.example .env
```

The first database target is Postgres so local Docker and deployment use the same shape. The backend keeps the database behind `DATABASE_URL`, so it can be swapped later.

## Combined Production Container

The production image builds the React frontend and copies it into the FastAPI runtime. Uvicorn
serves both applications on port `8000`:

```text
/        React application and client-side routes
/api/*   FastAPI endpoints
```

Build the image from the repository root:

```bash
docker build -t action-medeor .
```

For a local smoke test, start the Compose database and run the image on the Compose network:

```bash
docker compose up -d db
docker run --rm -p 8000:8000 \
  --network allocura_default \
  -e APP_ENV=production \
  -e DATABASE_URL=postgresql+asyncpg://allocura:allocura@db:5432/allocura \
  action-medeor
```

Open `http://localhost:8000`. The production runtime accepts these environment variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Async SQLAlchemy PostgreSQL URL. Use the externally managed production database. |
| `APP_ENV` | Recommended | Set to `production` to disable automatic local-development CORS behavior. |
| `CORS_ORIGINS` | No | Comma-separated cross-origin frontend URLs. Same-origin production needs none. |

`VITE_API_BASE_URL` is a frontend build-time setting for separately hosted local development. The
combined production build deliberately leaves it unset so browser requests use same-origin
`/api/...` URLs.

## Publish to Azure Container Registry

`.github/workflows/publish-container.yml` is manual-only and publishes only from `main`. A run
builds `main` and pushes only an immutable commit tag:

```text
<acr-login-server>/action-medeor:<git-sha>
```

The workflow definition must exist on the default branch (`main`) before GitHub displays its **Run
workflow** control. Dispatches for any other ref are skipped. This publishes the combined image but
does not deploy or update an Azure Container App.

Configure exactly these non-secret GitHub repository variables under **Settings > Secrets and
variables > Actions > Variables**:

| Variable | Azure portal source |
| --- | --- |
| `AZURE_CLIENT_ID` | App registration **Overview > Application (client) ID** |
| `AZURE_TENANT_ID` | App registration or Microsoft Entra ID **Overview > Directory (tenant) ID** |
| `AZURE_SUBSCRIPTION_ID` | **Subscriptions > target subscription > Overview > Subscription ID** |
| `AZURE_CONTAINER_REGISTRY_NAME` | Existing container registry **Overview > Registry name** |
| `AZURE_CONTAINER_REGISTRY_LOGIN_SERVER` | Existing container registry **Overview > Login server**; copy the complete value, including any DNS tenant suffix |

The workflow uses GitHub OIDC to obtain an AAD access token, exchanges that token directly at the
configured login server's `/oauth2/exchange` endpoint, and passes the resulting short-lived ACR
refresh token to Docker. It does not use a client secret, registry password, long-lived credential,
registry suffix setting, or registry control-plane discovery command.

### OIDC and ABAC prerequisites

The existing registry uses **RBAC Registry + ABAC Repository Permissions**, where the legacy
`AcrPush` role is not honored. Configure the workload identity outside this repository:

1. In **Microsoft Entra ID > App registrations**, create or select a single-tenant application for
   this publisher. Record its application/client and directory/tenant IDs. Do not create a client
   secret.
2. Under **Certificates & secrets > Federated credentials**, add a GitHub Actions credential for
   organization `TUM-Social-AI`, repository `action-medeor`, entity **Branch**, and branch `main`.
   Name it
   `github-action-medeor-main`. Its exact subject must be
   `repo:TUM-Social-AI/action-medeor:ref:refs/heads/main`.
3. Open the existing ACR resource itself, then **Access control (IAM) > Add role assignment**. At
   this exact ACR resource scope—not the resource group or subscription—assign `Container Registry
   Repository Writer` to the app registration's service principal.
4. In the assignment's **Conditions** editor, select all actions exposed for the Writer role and
   add:
   - Attribute source: `Request`
   - Attribute: `Repository name`
   - Operator: `StringEqualsIgnoreCase`
   - Value: `action-medeor`
5. Save the generated condition as condition version `2.0`. For CLI-managed assignments, copy the
   Writer-specific expression generated by the portal; do not reuse the Reader-role example from
   the Azure documentation.

`Container Registry Repository Writer` permits publishing and updating the known repository but
does not permit image deletion, catalog listing, or registry management. Do not grant the workload
identity `Container Registry Repository Catalog Lister`, `AcrPush`, Resource Group Contributor,
Owner, or a registry control-plane administrator role. The administrator creating the role
assignment needs separate role-assignment privileges; the publishing identity does not.

After the workflow definition is available on `main`, run **Publish production container** from the
Actions tab with branch `main`. Confirm that the known `action-medeor` repository contains the
expected `<git-sha>` tag and that the workflow did not add a `latest` tag. Also confirm that this
identity cannot push another repository name, list the registry catalog, delete images, or manage
the ACR resource.
