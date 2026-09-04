---
title: Asynchronous Message Brokers, Distributed Event Streaming, and Delivery Patterns
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: https://microservices.io/patterns/data/transactional-outbox.html
source_date: 2023-01-01
topic_tags:
  - messaging
  - rabbitmq
  - kafka
  - outbox pattern
  - debezium
  - idempotency
  - dead letter queue
---

## Broker Archetypes: Traditional Message Queues versus Log-Based Distributed Streaming

Asynchronous messaging decouples service execution, smooths traffic spikes, and provides event distribution. Backend systems employ two primary messaging architectures:

**Traditional Queue Brokers (AMQP 0-9-1 / RabbitMQ):**
- **Model:** Message-centric, broker-managed state.
- **Topology:** Publishers publish messages to **Exchanges**, which route messages to **Queues** based on binding rules and exchange types (`direct` for exact routing key matching, `fanout` for unconditioned broadcast, `topic` for wildcard string matching, and `headers` for metadata routing).
- **Consumption:** Push-based. The broker delivers messages to connected consumer workers, controlled by prefetch limits (`basic.qos`).
- **Lifecycle:** As soon as a consumer acknowledges a message (`basic.ack`), the broker **deletes** the message from memory and disk. 
- **Characteristics:** Designed for transient job queues. High queue depth under heavy load degrades performance because broker memory structures must manage individual message acknowledgment states.

**Log-Based Distributed Event Streaming (Apache Kafka):**
- **Model:** Append-only partitioned commit log, consumer-managed state.
- **Topology:** Data is organized into **Topics**, which are horizontally partitioned across cluster nodes. Each **Partition** is an immutable, ordered sequence of records appended sequentially to disk.
- **Consumption:** Pull-based. Consumers poll records from brokers in batches at their own processing rate. Consumers track their progress by committing integer **offsets** (the index of the last processed record in a partition).
- **Lifecycle:** Retention-based. Messages are **retained** for a configured time duration (e.g. 7 days) or storage quota, independent of consumption. Consuming a message does not delete it; multiple independent consumer groups can read the same partition at different offsets and rewind historical events.
- **Consumer Groups:** Enable parallel processing. Each partition within a topic is assigned to exactly one consumer instance within a consumer group. The maximum consumer parallelism for a group is bounded by the number of partitions in the topic.

## Message Delivery Guarantees and Consumer Idempotency

Distributed messaging platforms provide three classes of delivery guarantees:

1. **At-Most-Once:** Messages are delivered zero or one time. If a failure occurs during transit or worker execution, the message is lost. Used for high-volume, non-critical metrics or loss-tolerant sensor data.
2. **At-Least-Once (The Industry Baseline):** Messages are guaranteed never to be lost, but network retries or worker crashes may cause duplicate deliveries. A worker receives a message, processes it, and acknowledges it. If the worker crashes before sending the acknowledgment, or the network drops during ACK transmission, the broker redelivers the message to another consumer.
   - **Crucial Rule:** Because at-least-once is the standard operational guarantee, **every message consumer must be idempotent**. Processing the identical message multiple times must result in the exact same system state as processing it once.
3. **Exactly-Once / Effectively-Once:** Guarantees that each message modifies state exactly once. In Apache Kafka, this is achieved through idempotent producers (assigning a Producer ID and monotonically increasing sequence numbers per record) combined with the Transactional API. The Kafka Transaction Coordinator uses a Two-Phase Commit (2PC) protocol to atomically commit outgoing records across multiple topic partitions alongside consumer offset commits.

## The Dual-Write Problem and the Transactional Outbox Pattern

A fundamental reliability hazard in distributed systems is the **Dual-Write Problem**: when a service must modify an entity in its local database (e.g. inserting an `Order` row) and publish an event to a message broker (e.g. `OrderPlaced`), executing them as two distinct operations across network boundaries risks inconsistency:
- If the database write succeeds, but the process crashes or network fails before publishing to the broker, downstream systems never learn of the order.
- If the event is published to the broker first, but the database transaction rolls back, downstream systems process an event for a non-existent entity.

**The Solution: The Transactional Outbox Pattern (Chris Richardson):**
Instead of communicating across two systems, the application writes both the domain entity and an outbox record into the **same local database within a single ACID transaction**:
```sql
BEGIN;
INSERT INTO orders (id, customer_id, total) 
VALUES (1042, 88, 149.50);

INSERT INTO outbox (id, aggregate_type, aggregate_id, payload, created_at) 
VALUES ('uuid-01', 'Order', 1042, '{"event": "OrderPlaced", "total": 149.50}', NOW());
COMMIT;
```
Because both records are committed in the same database transaction, atomicity is guaranteed: either both are saved, or neither is.

**Relay via Change Data Capture (CDC):**
To transfer outbox records to the message broker without the polling overhead of `SELECT ... FOR UPDATE`, systems deploy **Change Data Capture (CDC)** engines like **Debezium**. Debezium connects directly to the database's write-ahead log (PostgreSQL WAL or MySQL binary log) via logical decoding. As soon as the transaction commits, Debezium reads the committed outbox record from the log and streams it to Kafka with sub-second latency, bypassing the query engine and imposing zero lock contention on application tables.

## Poison Pills and Dead-Letter Queue Architectures

A **poison pill** is a malformed, corrupt, or unexpected message payload that triggers an unhandled exception or crash in consumer application code whenever it is processed.

Under at-least-once delivery, an unhandled exception causes the consumer to terminate without acknowledging the message. The message broker redelivers the message to the next available worker, which also crashes. This creates an infinite crash loop that halts processing for the entire queue or partition.

**Mitigation via Dead-Letter Queues (DLQ):**
Consumers track message redelivery attempts using broker metadata headers (e.g. `x-delivery-count` in AMQP). When the failure count exceeds a configured threshold (typically 3 to 5 attempts):
1. The consumer forwards the failed message to a designated **Dead-Letter Queue (DLQ)** or Dead-Letter Exchange (DLX), attaching metadata about the failure (error stack trace, timestamp, originating worker).
2. The consumer acknowledges (`ACK`) the message in the primary queue, unblocking the processing pipeline for subsequent messages.
3. The DLQ triggers engineering alerts. Once bugs are resolved, messages in the DLQ can be inspected, replayed, or purged.

## Idempotency Keys in Distributed Mutation APIs

To make non-idempotent HTTP operations (such as `POST /payments/charge`) resilient against network timeouts and client retries, modern backends implement **Idempotency Keys** (standardized in production by Stripe and documented in IETF drafts).

The client generates a unique identifier (typically a UUID v4) and includes it in the request:
`Idempotency-Key: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d`

The server enforces idempotency through a state machine managed in an atomic datastore (Redis or SQL database):
1. **Lookup:** The server queries the store for the idempotency key.
2. **State = `COMPLETED`:** If the key exists and holds a completed state, the server bypasses business logic entirely and returns the cached HTTP status code, headers, and response payload.
3. **State = `PROCESSING`:** If the key exists with a processing state, another request with the same key is currently running. The server returns an HTTP `409 Conflict` or pauses until the initial request concludes to avoid concurrent duplicate execution.
4. **State = New:** The server atomically writes the key with status `PROCESSING`. It processes the business transaction, updates the key record to `COMPLETED` with the resulting response payload, and assigns a Time-To-Live (typically 24 to 72 hours).
