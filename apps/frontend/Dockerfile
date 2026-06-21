FROM node:22-alpine AS builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@9.15.4 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/frontend/package.json apps/frontend/package.json

RUN pnpm install --filter @allocura/frontend... --frozen-lockfile

COPY apps/frontend apps/frontend

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN pnpm --filter @allocura/frontend build

FROM nginx:1.27-alpine

COPY apps/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/apps/frontend/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1/ || exit 1
