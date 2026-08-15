# apps/web

Next.js + TypeScript. Deployed to **Cloudflare Pages** (not Vercel — the Hobby tier
prohibits commercial use, and we intend to monetize).

## Owns

- Rendering and client state. **That's all.**
- The swipe feed, card expansion, notes, quiz UI, progress and completion surfaces.

## Does not own

**Any business logic.** Zero. It calls `apps/api` over HTTP exactly as the future React
Native app will. If logic creeps in here, the mobile app either can't reach it or we end
up maintaining two divergent implementations. This is the most common way
"we'll add mobile later" projects rot.

## API types

Generated from the API's OpenAPI schema, never hand-written:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o packages/api-types/schema.d.ts
```

This runs in CI. A Pydantic model change that breaks the frontend fails the build.
See [ADR-0001](../../docs/adr/0001-python-fastapi-over-node.md).

## Status

Not yet implemented.
