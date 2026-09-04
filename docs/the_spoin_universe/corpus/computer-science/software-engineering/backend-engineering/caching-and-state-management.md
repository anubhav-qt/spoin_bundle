---
title: Caching Topologies, Invalidation Strategies, and Cache Stampede Mitigations
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: http://www.vldb.org/pvldb/vol8/p886-vattani.pdf
source_date: 2015-04-01
topic_tags:
  - caching
  - redis
  - cache aside
  - cache stampede
  - xfetch
  - eviction policies
  - session management
---

## Memory Topologies: In-Process versus Remote Distributed Caches

Caching accelerates data retrieval by retaining high-frequency results in low-latency volatile storage. Backend systems deploy caching across two primary topologies:

**In-Process (Local Memory):**
Caches reside directly in application process memory (e.g. Google Guava, Caffeine in Java, or process dictionaries in Go/Node.js).
- **Latency:** Sub-microsecond pointer access. Data requires zero network I/O or inter-process serialization.
- **Constraints:** Competes directly with application heap space; large caches increase garbage collection pause times in managed runtimes. In a horizontally scaled cluster, each server instance maintains a private cache, leading to data divergence across nodes (Node A serves version 1 while Node B serves version 2). When application processes restart during rolling deployments, all local caches are wiped, exposing downstream databases to cold-start traffic surges.

**Remote Distributed Caches:**
Caches operate as dedicated, centralized memory clusters accessed over the network (e.g. Redis, Memcached, Dragonfly).
- **Latency:** Sub-millisecond (typically 0.5ms to 2.0ms over internal network links).
- **Advantages:** Provides a single, globally consistent cache state accessible by all application instances. Memory and CPU scale independently of backend application servers. Node restarts and deployments do not invalidate the cache.

**Multi-Tier (L1/L2) Hybrid Topology:**
High-throughput systems often deploy an L1 in-process cache (with a short 5–30 second TTL) in front of an L2 Redis distributed cache. When a record is updated on one node, an invalidation message is published across a pub/sub bus (such as Redis Pub/Sub) to evict the corresponding L1 entry on peer nodes.

## Caching Patterns: Cache-Aside, Write-Through, Write-Behind, and Refresh-Ahead

Applications interact with caches using four core architectural patterns:

**1. Cache-Aside (Lazy Loading):**
The application code directly coordinates both the cache and the database:
- **Read Path:** The application checks the cache. On a hit, it returns the value. On a miss, it queries the database, writes the result to the cache with an expiration interval (TTL), and returns the payload.
- **Write Path:** The application updates the database, then invalidates (deletes) the cached key.
- **Trade-off:** Memory-efficient because only actively requested items are cached. The first access incurs a cache-miss latency penalty. Invalidation avoids race conditions where concurrent updates overwrite newer values.

**2. Write-Through:**
The application writes exclusively to the cache abstraction. The cache synchronously writes the update to the primary database within the same transaction and returns success only after both stores confirm the write.
- **Trade-off:** Guarantees data freshness and eliminates cache-database discrepancies, but increases write latency by combining cache and database round-trips.

**3. Write-Behind (Write-Back):**
The application writes to the cache, which acknowledges success immediately. The cache then batches and writes dirty updates asynchronously to the primary database in background intervals.
- **Trade-off:** Provides ultra-low write latency and write coalescing (collapsing 100 increments into a single database update). The severe risk is data loss: if the cache node crashes before dirty buffers flush to disk, unwritten mutations are lost permanently.

**4. Refresh-Ahead:**
The cache monitors key access frequency. If a key is frequently read and nearing its TTL expiration, the cache proactively triggers an asynchronous background fetch from the database to refresh the value before it expires.
- **Trade-off:** Eliminates cache-miss latency for hot records, but consumes database read capacity if access predictions prove inaccurate.

## Eviction Policies and Memory Lifecycle

When a cache exhausts its configured memory threshold, eviction policies select which keys to drop:
- **Least Recently Used (LRU):** Evicts items that have gone the longest duration without an access. Well-suited for temporal locality patterns.
- **Least Frequently Used (LFU):** Maintains access counters per key and evicts items with the lowest access frequency. Effective for stable working sets, but requires counter decay mechanisms to prevent old, historically popular keys from monopolizing memory.
- **First In, First Out (FIFO):** Evicts entries based purely on insertion order, ignoring subsequent reads.
- **Time-To-Live (TTL):** Evicts keys after an absolute duration. Eviction is handled lazily (evaluating expiration upon access) or actively (background threads sampling random subsets of expired keys, as in Redis).

## Cache Stampede: The Thundering Herd Problem and XFetch Mitigation

High-scale caches are vulnerable to cache stampedes (thundering herd events). A heavily accessed key expires or is invalidated, and hundreds or thousands of concurrent requests miss the cache simultaneously. All concurrent threads attempt to recompute the expensive query against the database at the exact same millisecond, exhausting database connection pools and crashing the backend.

- **Mitigation via Mutex / Singleflight:** When a cache miss occurs, the worker attempts to acquire a distributed lock (or process-level lock, such as Go's `singleflight`). Only the lock holder executes the database query; all other concurrent requests wait or subscribe to the single in-flight result.
- **Mitigation via Probabilistic Early Expiration (XFetch):**
  Formalized by Andrea Vattani, Flavio Chierichetti, and Keegan Lowenstein in *"Optimal Probabilistic Cache Stampede Prevention"* (VLDB 2015). Instead of waiting for hard expiration, individual read operations probabilistically decide whether to recompute early based on:
  $$\text{time}() - \beta \cdot \delta \cdot \ln(\text{rand}()) \ge \text{expiry}$$
  - $\text{time}()$: Current epoch time.
  - $\beta$: Constant multiplier ($\beta > 0$, default 1.0). Higher values trigger earlier recomputation.
  - $\delta$: Time duration taken to execute the computation on the previous refresh.
  - $\text{rand}()$: Uniformly distributed random float in $(0, 1]$.
  - $\text{expiry}$: Absolute expiration timestamp of the cached entry.
  As $\text{time}()$ approaches $\text{expiry}$, the probability of early recomputation grows exponentially toward 1. Exactly one worker recomputes early; the entry is updated in the background, and the cache never suffers a hard miss under continuous load.

## Cache Penetration and Cache Avalanche Defenses

Beyond stampedes, backend caches must defend against penetration and avalanche failure modes:

**1. Cache Penetration:**
Clients issue queries for keys that exist in neither the cache nor the database (e.g. automated attacks scanning non-existent IDs). Every request bypasses the cache and queries the database.
- **Cache Null Objects:** Store a sentinel "null" value in the cache with a short TTL (e.g. 60 seconds).
- **Bloom Filters:** Place a Bloom filter containing all valid primary keys in front of the cache. If the filter indicates a key is absent (which carries zero false negatives), the request is rejected immediately without database contact.

**2. Cache Avalanche:**
A large proportion of cached items are initialized with the identical TTL, causing them to expire at the exact same second and unleashing an avalanche of database traffic.
- **TTL Jitter:** Add random variance to TTL allocations: $\text{TTL}_{\text{actual}} = \text{TTL}_{\text{base}} + \text{random}(-\Delta, \Delta)$.

## Backend State and Distributed Session Architecture

Managing user session state across stateless application instances involves three common architectures:
- **Sticky Sessions (Session Affinity):** The edge load balancer inspects client cookies or IP addresses and routes subsequent requests to the specific server that initiated the session. This creates uneven traffic distribution and causes users to be logged out whenever an application instance crashes or deploys.
- **Centralized Session Store:** Application servers remain completely stateless. User session payloads are stored in a centralized, high-availability Redis cluster using the session ID as key. Any backend node can process any request, allowing frictionless autoscaling and zero-downtime rolling updates.
- **Stateless Tokens (JWT):** Session claims are cryptographically signed and stored on the client. Eliminates server-side session lookups, but complicates token revocation before expiration.
