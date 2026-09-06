---
title: Database Schema Evolution and Zero-Downtime Deployments
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: Martin Fowler (Evolutionary Database Design), Continuous Delivery & Modern SRE Deployment Practices
source_date: 2024
topic_tags: [fullstack-engineering, zero-downtime, expand-and-contract, database-migrations, chunk-load-errors, cdn-caching, blue-green]
---

# Database Schema Evolution and Zero-Downtime Deployments

## The Fullstack Deployment Dilemma

A production web application cannot transition atomically between versions:
- Active users frequently leave browser tabs open for hours or days, executing client-side code compiled from an older release.
- Server infrastructure rolls out updates progressively over several minutes across multiple containers, pods, or serverless instances using Canary or Blue/Green deployment strategies.
- During a deployment window, Version 1 and Version 2 of the application server run concurrently behind load balancers, both reading from and writing to the identical underlying database.

If an engineering team deploys a breaking database migration—such as renaming a column from `phone_number` to `mobile_phone`, or dropping a table column—the database changes instantly. When active Version 1 servers or older client sessions dispatch requests expecting `phone_number`, database queries fail immediately, causing wide-scale transaction errors.

## The Expand and Contract (Parallel Change) Pattern

To evolve database schemas without downtime or client disruption, systems execute migrations according to the **Expand and Contract** (or Parallel Change) pattern across multiple independent deployment phases:

1. **Phase 1: Expand (Add Without Modifying Existing):**
   - The database migration adds the new column `mobile_phone` (configured as nullable or with a default value) alongside the existing `phone_number`.
   - Backend application code is updated to implement **dual writing**: any new record or update is written to both `phone_number` and `mobile_phone`. However, the application continues reading strictly from `phone_number`.
   - Deploy backend Version 1.1. Existing Version 1.0 clients and new Version 1.1 servers coexist safely without database errors.
2. **Phase 2: Historical Data Backfill:**
   - An asynchronous background script or batched database job copies historical data from `phone_number` to `mobile_phone` across all existing database rows in manageable batch chunks, avoiding table locks.
3. **Phase 3: Migrate Reads and Client Transition:**
   - Application code is updated to read from `mobile_phone`.
   - Frontend client applications are updated to utilize `mobile_phone` in forms and UI components.
   - Deploy backend Version 1.2 and frontend Version 1.2. The legacy column `phone_number` remains in the database and dual-writing continues to support lingering legacy client sessions.
4. **Phase 4: Contract (Remove Deprecated Artifacts):**
   - After monitoring confirms all active client traffic has transitioned to Version 1.2 (and older mobile app versions have been retired), dual writing is removed from application code.
   - A final database migration drops the deprecated column: `ALTER TABLE users DROP COLUMN phone_number;`.

## Backward-Compatible API Contracts and Deprecation Windows

Schema evolution necessitates parallel discipline at the API layer. API contracts must maintain backward compatibility across deployment transitions:
- **Additive Changes Only:** Adding new fields to an API response payload is backward-compatible for well-behaved clients that ignore unrecognized properties. Renaming or removing fields breaks existing clients.
- **Tolerant Reader Pattern:** Client deserializers should adhere to the Tolerant Reader pattern: extract only the explicit properties needed, handle unexpected fields gracefully, and provide sensible fallback defaults for missing optional values.
- **Contract Versioning:** When breaking changes are unavoidable, APIs expose versioned routes (e.g., `/api/v1/orders` vs `/api/v2/orders`) or request headers. Backend servers support the legacy endpoint across a declared deprecation grace period, monitoring access metrics until client traffic ceases before decommissioning the route.

## CDN Asset Versioning and the ChunkLoadError Hazard

Modern web build tools partition client applications into dozens of asynchronous JavaScript chunks loaded dynamically on demand (`import('./CheckoutModal.js')`). Each compiled chunk filename incorporates a cryptographic content hash:
`settings.3b91fa.js`

During zero-downtime rolling deployments, a frequent failure mode is the **`ChunkLoadError`**:
1. A user loads the initial HTML shell containing references to Version 1 asset hashes.
2. A new deployment deploys Version 2 to production.
3. The deployment script wipes the CDN storage bucket and uploads Version 2 assets (`settings.8c24d1.js`).
4. The user clicks a navigation link in their open tab, prompting the browser to dynamically fetch `settings.3b91fa.js`.
5. The CDN returns an HTTP 404 Not Found response because the old chunk was deleted. The application crashes with an uncaught `ChunkLoadError`.

Zero-downtime asset governance mandates that compiled hashed assets from previous releases must **never** be purged immediately from CDN object storage (such as AWS S3 or Google Cloud Storage). Hashed assets must be preserved with immutable cache headers (`Cache-Control: public, max-age=31536000, immutable`) for days or weeks after retirement, ensuring older open tabs can load lazy chunks seamlessly.

## Blue/Green and Canary Deployment Orchestration

Production fullstack infrastructure coordinates deployments across server clusters through phased traffic shifting:

- **Canary Deployments:** Routes a small fraction of real production traffic (e.g., 2% to 5%) to the newly deployed application version. Real-time telemetry evaluates HTTP error rates, latency percentiles, and database connection metrics. If error thresholds spike, traffic instantly reverts to the stable baseline without customer impact.
- **Blue/Green Deployments:** Maintains two identical production environments (Blue and Green). While Blue serves live customer traffic, Green is deployed with the new release and validated against production database mirrors. Once health checks pass, the edge router or load balancer atomically flips traffic routing from Blue to Green. If unexpected defects emerge, routing flips back to Blue instantaneously.
