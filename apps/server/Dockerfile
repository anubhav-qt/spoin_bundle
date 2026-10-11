# One image, several commands (build context: the repository root):
#   node dist/api.js       the API (default)
#   node dist/migrate.js   both databases' migrations
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY packages/shared/package.json packages/shared/
COPY packages/frog/package.json packages/frog/
COPY packages/pi-ai/package.json packages/pi-ai/
COPY packages/pi-agent/package.json packages/pi-agent/
COPY apps/server/package.json apps/server/
COPY apps/web/package.json apps/web/
RUN npm ci --workspace @spoin/server --include-workspace-root=false --ignore-scripts --no-audit --no-fund
COPY tsconfig.base.json ./
COPY packages/shared packages/shared
COPY packages/frog packages/frog
COPY packages/pi-ai packages/pi-ai
COPY apps/server apps/server
RUN npm run build -w @spoin/server

# The embedder's runtime loads native code and model files of its own, so it is
# installed beside the bundle rather than inside it (build.mjs).
FROM node:24-slim AS runtime-deps
WORKDIR /deps
COPY package-lock.json /tmp/
RUN v=$(node -p "require('/tmp/package-lock.json').packages['node_modules/@huggingface/transformers'].version") \
  && npm install --no-package-lock --no-audit --no-fund "@huggingface/transformers@$v"

FROM node:24-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/* \
  && mkdir -p /models && chown node:node /models
WORKDIR /app
ENV NODE_ENV=production
# The commit, shown by /health, so you can see which version each server runs.
ARG RELEASE=dev
ENV RELEASE=$RELEASE
COPY --from=runtime-deps /deps/node_modules ./node_modules
COPY --from=build /app/apps/server/dist ./dist
COPY --from=build /app/apps/server/drizzle ./drizzle
COPY --from=build /app/packages/frog/drizzle ./universe-drizzle
ENV UNIVERSE_MIGRATIONS_DIR=/app/universe-drizzle
USER node
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "--enable-source-maps", "dist/api.js"]
