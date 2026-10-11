# The web's development image (build context: the repository root, infra/compose.yml).
# Only the manifests, the shared contract and the web's own files are copied, never
# apps/web whole: a host checkout carries node_modules and .next, and the root has no
# .dockerignore. The lockfile carries the musl builds of swc and sharp.
FROM node:24-alpine
WORKDIR /app
COPY package.json package-lock.json ./
COPY packages/shared/package.json packages/shared/
COPY packages/frog/package.json packages/frog/
COPY apps/server/package.json apps/server/
COPY apps/web/package.json apps/web/
RUN npm ci --workspace @spoin/web --include-workspace-root=false --no-audit --no-fund
COPY tsconfig.base.json ./
COPY packages/shared packages/shared
COPY apps/web/app apps/web/app
COPY apps/web/components apps/web/components
COPY apps/web/lib apps/web/lib
COPY apps/web/public apps/web/public
COPY apps/web/next.config.ts apps/web/tsconfig.json apps/web/next-env.d.ts apps/web/
WORKDIR /app/apps/web
EXPOSE 3000
CMD ["npm", "run", "dev"]
