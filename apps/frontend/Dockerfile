FROM node:22-alpine AS builder
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/frontend/package.json apps/frontend/package.json
COPY packages/config-ts/package.json packages/config-ts/tsconfig.base.json packages/config-ts/
COPY packages/shared-types/package.json packages/shared-types/tsconfig.json packages/shared-types/
RUN corepack enable && pnpm install --frozen-lockfile
COPY packages/shared-types/src packages/shared-types/src
RUN pnpm --filter @doc-pipeline/shared-types build
COPY apps/frontend apps/frontend
RUN pnpm --filter @doc-pipeline/frontend build

FROM nginx:alpine AS runner
COPY --from=builder /workspace/apps/frontend/dist /usr/share/nginx/html
COPY apps/frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
