---
title: "Practical Backend Engineering: Field Tips, Operational Pitfalls, and Production Rules of Thumb"
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: https://github.com
source_date: 2026-09-05
topic_tags:
  - backend engineering
  - production tips
  - operational pitfalls
  - database traps
  - connection pooling
  - redis
  - distributed locks
---

## Database Transactions and Connection Pool Starvation

One of the most destructive anti-patterns in production backend systems is executing an external network call (such as a third-party payment gateway, external REST API, or cloud storage upload) inside an active database transaction.

When an application opens a transaction (`BEGIN`), it checks out a dedicated database connection from the connection pool and holds exclusive locks on modified rows. If an external HTTP call inside that transaction stalls for 5 to 30 seconds due to third-party network jitter, that database connection remains completely blocked. Under moderate concurrent traffic, the application's connection pool exhausts within seconds, queueing all subsequent incoming requests and taking down the entire API cluster.

Furthermore, database transactions provide an illusion of atomicity that breaks across external systems: a database `ROLLBACK` undoes local SQL writes, but cannot undo a credit card charge, an email dispatch, or an external webhook that already executed over the network.

**The Production Rule of Thumb:**
- **Separate transactions from network I/O:** Perform external network calls either *before* opening the database transaction or *after* committing it.
- **Use the Transactional Outbox:** If an event must be dispatched as a result of a database state change, write the event into an `outbox` table within the local transaction, and have a decoupled background worker or Change Data Capture (CDC) stream dispatch the external network request.
- **Enforce Database Timeouts:** Always configure explicit timeouts on database connections:
  - `statement_timeout` (e.g. 5000ms): Aborts queries that exceed a safe execution threshold.
  - `idle_in_transaction_session_timeout` (e.g. 10000ms in PostgreSQL): Terminates orphaned or forgotten transactions that remain idle while holding locks.

## The 64-Bit Integer JavaScript JSON Truncation Trap

Modern distributed databases and distributed ID generators (such as Twitter Snowflake, Sonyflake, and Instagram ID generators) use 64-bit unsigned integers (`uint64` / `int64`) for high-throughput primary keys.

JavaScript numbers are double-precision 64-bit binary format IEEE 754 values. In this format, the maximum safe integer is:
$$\text{Number.MAX\_SAFE\_INTEGER} = 2^{53} - 1 = 9,007,199,254,740,991$$
Any integer larger than $2^{53}-1$ cannot be represented precisely. A 64-bit ID such as `1583829583928194051` exceeds this threshold. When a backend serializes this ID as a bare integer into a JSON payload (`{"id": 1583829583928194051}`), browser clients and Node.js environments parsing the response with standard `JSON.parse()` silently round the lowest bits, mutating the ID into `1583829583928194000`. When the frontend subsequently issues a mutation (e.g. `DELETE /items/1583829583928194000`), the backend returns a `404 Not Found` or mutates the wrong record.

**The Production Rule of Thumb:**
- **Serialize 64-bit IDs as Strings:** Whenever emitting 64-bit integer IDs (or BigInt fields) in JSON API responses, always format them as strings (`{"id": "1583829583928194051"}`). Maintain internal mathematical integer representations in backend databases and memory, but treat identifiers as opaque strings at serialization boundaries.

## Cloud NAT Gateways and the 350-Second Idle TCP Drop

Backend services deployed in private VPC subnets route outbound traffic through managed cloud gateways (such as AWS NAT Gateway or Network Load Balancers). A widespread operational mystery is database connections or Redis connections suddenly throwing `Connection reset by peer` or hanging indefinitely during periods of low traffic.

**The Underlying Cause:**
AWS NAT Gateways and NLBs enforce a fixed, non-configurable **350-second idle timeout** for TCP connections. If a connection remains completely silent (no bytes transmitted in either direction) for 350 seconds, the NAT gateway silently drops the connection tracking state from its internal table without transmitting a `TCP RST` or `FIN` packet to either host. When the backend application eventually attempts to issue a query across what it believes to be an established socket, the NAT gateway rejects the unrecognized packet with a `TCP RST`, causing unexpected connection drops. If the client socket has no keepalive configured, it may hang waiting for a response until the OS-level TCP timeout (which can exceed 15 minutes).

**The Production Rule of Thumb:**
- **Configure Aggressive TCP Keepalives:** Set TCP keepalive parameters at the operating system or database driver connection level to probe well below the 350-second ceiling (e.g. `tcp_keepalive_time = 60`, `tcp_keepalive_intvl = 10`, `tcp_keepalive_probes = 5`).
- **Connection Pool Max Lifetime:** Configure application connection pool settings (such as `maxLifetime` or `idleTimeout` in HikariCP, asyncpg, or GORM) to close and cycle idle connections after 240 to 300 seconds, ensuring connections are retired gracefully before the network infrastructure purges them.

## Production Redis Hazards: `KEYS *` versus Cursor-Based `SCAN`

Redis operates as a single-threaded event loop for processing client commands. While Redis is capable of handling over 100,000 operations per second for $O(1)$ operations, commands with $O(N)$ algorithmic complexity block the entire event loop until completion.

A notorious production mistake is executing `KEYS *` (or `KEYS prefix:*`) to locate keys in production. If the Redis instance holds millions of keys, `KEYS *` forces the single thread to traverse the entire keyspace dictionary. During the several seconds or minutes this scan takes:
- All other concurrent client commands (reads, session lookups, cache checks) are completely blocked.
- Application servers experience connection timeouts.
- Sentinel or Redis Cluster nodes fail to receive heartbeats and trigger unnecessary, disruptive master failovers.

**The Production Rule of Thumb:**
- **Always use `SCAN` instead of `KEYS`:** The `SCAN` command is cursor-based and iterates over the collection incrementally without blocking the server. Each invocation returns a small batch of keys and a new cursor offset (e.g. `SCAN 0 MATCH user:* COUNT 1000`), allowing the event loop to interleave normal client operations between scan steps.
- **Disable dangerous commands:** In production `redis.conf` configurations, rename or disable dangerous commands entirely:
  ```text
  rename-command KEYS ""
  rename-command FLUSHALL ""
  rename-command FLUSHDB ""
  ```

## Distributed Locking Realities: Advisory Locks versus Fencing Tokens

Engineering teams frequently use Redis as a distributed lock manager (often implementing the Redlock algorithm) to protect critical sections across microservice nodes. However, as demonstrated by distributed systems researcher Martin Kleppmann (2016), distributed locks implemented without storage-layer validation are merely **advisory locks for efficiency, not for correctness**.

**The Asynchronous Pause Flaw:**
1. Client 1 acquires a distributed lock with a 10-second TTL to update a shared resource in storage.
2. Client 1 enters an unexpected operating system stop-the-world garbage collection (GC) pause, an I/O page fault, or a network partition lasting 15 seconds.
3. While Client 1 is paused, its lock lease expires in Redis.
4. Client 2 acquires the lock (now free) and writes update $V_2$ to the storage system.
5. Client 1's GC pause concludes. Unaware that its lock expired, Client 1 continues its execution and writes update $V_1$ to storage, silently overwriting Client 2's data and corrupting state.

**The Production Rule of Thumb:**
- **Enforce Fencing Tokens for Correctness:** If a distributed lock protects data integrity, the lock service must return a **fencing token**—a monotonically increasing integer incremented every time a lock is granted. The target storage system must inspect the token and reject any write carrying a token lower than the latest token it has already processed.
- **Use Consensus Engines for Strict Mutual Exclusion:** When absolute correctness without fencing is required, rely on consensus-backed systems like `etcd` or `ZooKeeper`, or use database row-level locking (`SELECT ... FOR UPDATE`), rather than advisory in-memory TTL locks.

## Application Graceful Shutdown Lifecycle (`SIGTERM` Sequencing)

In containerized and Kubernetes environments, deployments, horizontal autoscaling, and node drains frequently terminate backend server instances. When a container runtime terminates a pod, it transmits a `SIGTERM` signal, waits for a grace period (default 30 seconds), and sends `SIGKILL` if the process has not exited.

A common failure mode is an application that terminates immediately upon receiving `SIGTERM`: closing its database connection pool and severing active TCP sockets. In-flight client HTTP requests abort mid-execution, generating bursts of HTTP `502 Bad Gateway` errors across the edge load balancer.

**The Proper Graceful Shutdown Sequence:**
1. **Intercept `SIGTERM`:** Catch the termination signal in the application runtime.
2. **Transition Health Check:** Immediately mark the application's readiness probe endpoint (`GET /health/ready`) as failing (e.g. returning HTTP `503 Service Unavailable`). This instructs edge load balancers, reverse proxies, and Kubernetes ingress controllers to stop routing new traffic to this node.
3. **Wait for Ingress Deregistration (The Flap Window):** Sleep for 5 to 10 seconds before shutting down listeners. This window allows external load balancers and DNS caches to complete their asynchronous routing table updates.
4. **Stop Accepting New Connections:** Stop accepting new incoming requests on the HTTP/gRPC listener while keeping existing keep-alive connections alive.
5. **Drain In-Flight Requests:** Allow active in-flight requests a bounded duration (e.g. 15 to 20 seconds) to complete processing and flush responses.
6. **Teardown Persistence Resources:** Close background queue consumers, flush telemetry buffers, and finally close database connection pools and Redis clients.
7. **Exit cleanly with status code `0`.**

## Asynchronous Workers: Consumer Lag and Invariant-Based Idempotency

In event-driven architectures and worker pools, two operational traps frequently create silent data corruption:

**1. Monitoring Queue Depth instead of Consumer Lag:**
Engineering teams often set alerts on queue depth (total messages waiting in queue). In log-based streaming (such as Apache Kafka), queue depth is meaningless because messages are retained for days.
- **The Metric that Matters: Consumer Lag.** Consumer lag measures the numerical delta between the latest offset produced by publishers and the latest offset committed by a consumer group ($L = \text{Offset}_{\text{highwater}} - \text{Offset}_{\text{consumer}}$). An increasing lag indicates workers have stalled, died, or are falling behind incoming throughput.

**2. The Inadequacy of "Check-Then-Insert" Idempotency:**
When consuming messages under at-least-once delivery, checking for prior execution with an application-level read:
```python
# BROKEN CONCURRENCY:
if not db.find_processed_event(event_id):
    db.insert_processed_event(event_id)
    execute_side_effect()
```
If two duplicate messages are processed concurrently by two worker threads, both workers execute the `find_processed_event` check simultaneously, both find zero matching records, and both execute the side-effect twice.
- **The Invariant Rule:** Idempotency must be enforced by the storage engine using **database-level unique constraints** or atomic primitive operations:
  ```sql
  INSERT INTO processed_events (event_id, processed_at) 
  VALUES (:event_id, NOW()) 
  ON CONFLICT (event_id) DO NOTHING;
  ```
  Only if the row was successfully inserted does the worker proceed with downstream side effects.
