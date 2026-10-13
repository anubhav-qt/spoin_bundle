# Two images (build context: the repository root). `server`, several commands:
#   node dist/api.js       the API (default)
#   node dist/migrate.js   both databases' migrations
# and `worker`, the same with headless Chromium, which runs the authoring harness.
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
COPY packages/pi-agent packages/pi-agent
COPY apps/server apps/server
RUN npm run build -w @spoin/server

# The embedder's runtime loads native code and model files of its own, and Playwright
# finds its browser from its own package, so both are installed beside the bundle
# rather than inside it (build.mjs), at the lockfile's versions.
FROM node:24-slim AS runtime-deps
WORKDIR /deps
COPY package-lock.json /tmp/
RUN t=$(node -p "require('/tmp/package-lock.json').packages['node_modules/@huggingface/transformers'].version") \
  && p=$(node -p "require('/tmp/package-lock.json').packages['node_modules/playwright-core'].version") \
  && npm install --no-package-lock --no-audit --no-fund "@huggingface/transformers@$t" "playwright-core@$p"

FROM node:24-slim AS server
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
COPY prompts ./prompts
ENV PROMPTS_DIR=/app/prompts
USER node
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "--enable-source-maps", "dist/api.js"]

# The worker: headless Chromium for pages with no text in their HTML, and for designer_toad's
# renders of the real card (task 0045).
FROM server AS worker
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN node node_modules/playwright-core/cli.js install --with-deps chromium \
  && rm -rf /var/lib/apt/lists/* \
  && mkdir -p /data/universe && chown node:node /data/universe
USER node
CMD ["node", "--enable-source-maps", "dist/worker.js"]
