---
title: Database Models, Transaction Isolation, and Storage Engines
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: https://dl.acm.org/doi/10.1145/223784.223785
source_date: 1995-05-01
topic_tags:
  - databases
  - transactions
  - acid
  - isolation levels
  - snapshot isolation
  - b tree
  - lsm tree
  - cap theorem
  - pacelc
---

## Relational Foundations, ACID Guarantees, and Write-Ahead Logging

Relational database management systems (RDBMS) organize data into typed relations (tables) and provide transaction guarantees formalized under the ACID model (Jim Gray and Andreas Reuter):
- **Atomicity:** All operations within a transaction complete successfully, or all mutations are rolled back.
- **Consistency:** A transaction transitions the database from one valid state to another, preserving all explicit schema constraints (primary keys, foreign keys, unique checks) and business invariants.
- **Isolation:** The concurrent execution of multiple transactions results in a database state equivalent to some serial execution, preventing dirty data observation according to the configured isolation level.
- **Durability:** Once a transaction commits, its mutations survive subsequent power outages, operating system crashes, or hardware faults.

Durability and atomicity rely fundamentally on **Write-Ahead Logging (WAL)**. A database maintains an in-memory buffer pool where pages are modified. Under WAL protocol rules, dirty pages in the buffer pool are never written to permanent disk blocks before the corresponding log records describing the modification have been flushed to non-volatile storage (`fsync`). Because appending to the sequential WAL is orders of magnitude faster than random page writes, the database commits transactions with low latency. In the event of a crash, the recovery engine replays the sequential WAL from the last checkpoint (REDO) and rolls back uncommitted transactions (UNDO), restoring consistency without data loss.

## Transaction Isolation Levels and Concurrency Anomalies

The ANSI SQL-92 standard established four isolation levels defined by prohibiting three phenomena: Dirty Read, Non-Repeatable Read, and Phantom. In their 1995 paper *"A Critique of ANSI SQL Isolation Levels"*, Hal Berenson, Phil Bernstein, Jim Gray, Jim Melton, Elizabeth O'Neil, and Patrick O'Neil demonstrated that ANSI SQL-92 definitions were ambiguous, incomplete, and failed to account for commercial database behaviors.

The authors formalized concurrency phenomena:
- **Dirty Read ($P_1$):** Transaction 1 modifies a row. Transaction 2 reads the uncommitted row. Transaction 1 aborts. Transaction 2 acted on data that was never committed.
- **Non-Repeatable (Fuzzy) Read ($P_2$):** Transaction 1 reads a row. Transaction 2 modifies or deletes that row and commits. Transaction 1 reads the row again and observes the modified value or deletion.
- **Phantom ($P_3$):** Transaction 1 queries a range of rows matching a predicate (`WHERE status = 'pending'`). Transaction 2 inserts new rows matching that predicate and commits. Transaction 1 executes the query again and observes new rows.
- **Read Skew ($A5A$):** Transaction 1 reads row $X$. Transaction 2 updates row $X$ and row $Y$ and commits. Transaction 1 reads row $Y$, observing an inconsistent state where $X$ reflects pre-update state and $Y$ reflects post-update state.
- **Write Skew ($A5B$):** Two concurrent transactions read overlapping data sets, satisfy an integrity constraint, make disjoint writes based on their reads, and commit. For example, a hospital requires at least one physician on call ($D_1 + D_2 \ge 1$). Transaction 1 reads both doctors on call, sets $D_1 = \text{false}$, and commits. Concurrently, Transaction 2 reads both doctors on call, sets $D_2 = \text{false}$, and commits. Both transactions commit because their writes modified disjoint rows ($D_1$ vs $D_2$), but the resulting state leaves zero physicians on call, violating the invariant.

**Snapshot Isolation (SI):** Formalized by Berenson et al. (1995), Snapshot Isolation assigns each transaction a logical snapshot timestamp upon initiation. A transaction reads only data committed prior to its snapshot, rendering readers non-blocking to writers and writers non-blocking to readers. SI eliminates Dirty Reads, Non-Repeatable Reads, and Read Skew. Concurrent updates to the *same* row are detected via a "first-committer-wins" rule, which aborts the later transaction. 

**Why Snapshot Isolation is NOT Serializable:** Snapshot Isolation permits Write Skew ($A5B$) because conflict detection operates on row writes, not predicate read sets. When concurrent transactions update disjoint rows based on overlapping reads, SI allows both to commit. True serializability under snapshot performance requires **Serializable Snapshot Isolation (SSI)** (Cahill, Röhm, and Fekete, 2008), which tracks read-write anti-dependency cycles in a dependency graph and aborts one transaction when a dangerous structure forms.

## Storage Engine Architectures: B+ Trees versus LSM-Trees

Storage engines determine how data is organized, indexed, and retrieved on physical media.

**B+ Trees (Read-Optimized):**
Used in standard relational engines (PostgreSQL, MySQL InnoDB, SQLite). B+ Trees are self-balancing $M$-way search trees where internal nodes store routing keys and leaf nodes store row data or tuple pointers. Leaf nodes are linked sequentially for fast range scans.
- **Advantages:** Predictable $O(\log N)$ point lookups and range scans. Only 3 to 4 disk page lookups are required even for massive tables when internal index nodes fit in RAM.
- **Bottlenecks:** High **write amplification** during random writes. Modifying a 50-byte record requires reading, modifying, and flushing an entire $8\text{KB}$ or $16\text{KB}$ page in place, causing random I/O and page fragmentation.

**Log-Structured Merge-Trees (LSM-Trees, Write-Optimized):**
Introduced by Patrick O'Neil et al. (1996) and used in RocksDB, Cassandra, ScyllaDB, and ClickHouse. LSM-Trees decouple writes from in-place disk modifications:
1. **WAL:** Sequential disk log ensuring crash recovery.
2. **MemTable:** In-memory sorted buffer (e.g. SkipList) absorbing all `INSERT`, `UPDATE`, and `DELETE` operations sequentially.
3. **SSTables (Sorted String Tables):** When the MemTable reaches a threshold (e.g. 64MB), it is flushed sequentially to disk as an immutable SSTable. Deletions are appended as markers called **tombstones**.
4. **Compaction:** Background threads merge overlapping SSTables, discard overwritten keys, purge expired tombstones, and organize data into leveled tiers.
- **Advantages:** Converts random application writes into sequential disk I/O, providing high write throughput.
- **Bottlenecks:** High **read amplification**. Finding a key may require checking the MemTable and multiple SSTable files on disk.
- **Mitigation:** Engines maintain **Bloom filters** (probabilistic bit arrays in RAM) for each SSTable. Bloom filters determine with zero false negatives whether a key is absent from an SSTable, eliminating disk I/O for missing keys.

## Distributed Data Theorems: CAP, PACELC, and ACID versus BASE

Distributed data architectures must account for network failure boundaries and latency trade-offs.

**The CAP Theorem (Brewer 2000, proven by Gilbert & Lynch 2002):**
Under an active network **Partition (P)** where nodes cannot communicate:
- You must choose between **Consistency (C)** (linearizability: every read receives the most recent write or an error) and **Availability (A)** (every non-failing node returns a non-error response, potentially containing stale data).
- Partitions are unavoidable in physical networks. CAP dictates behavior during partitions, not during normal operation.

**The PACELC Theorem (Daniel J. Abadi, 2012):**
Abadi expanded CAP to capture the trade-offs present during normal, partition-free operations:
- **If Partition (P):** Trade off **Availability (A)** versus **Consistency (C)**.
- **Else (E) (Normal Operation):** Trade off **Latency (L)** versus **Consistency (C)**.
- **Classifications:**
  - **PC/EC systems:** (e.g. Google Spanner, CockroachDB). Choose Consistency over Availability during partitions; choose Consistency over Latency normally (synchronous replica coordination before acknowledging writes).
  - **PA/EL systems:** (e.g. Cassandra, DynamoDB eventual consistency). Choose Availability over Consistency during partitions; choose Latency over Consistency normally (replicate asynchronously, serving local reads immediately).

**ACID versus BASE:**
While ACID systems emphasize immediate consistency and pessimism, distributed systems often adopt **BASE**:
- **Basically Available:** Systems guarantee availability by responding from local partitions, though responses may be degraded.
- **Soft State:** Data values may drift or change over time without user interaction as background replication runs.
- **Eventual Consistency:** In the absence of new mutations, all replicas converge to identical state over time.

## Object Storage Architecture and the S3 Consistency Model

Object storage (such as Amazon S3 or Google Cloud Storage) manages unstructured data as discrete objects identified by unique string keys within a bucket namespace. Unlike block storage (which modifies individual disk blocks) or POSIX file systems (which support partial file updates and directory locks), object storage operations are atomic and whole-object: updating an object requires replacing the entire payload.

**The S3 Consistency Milestone (December 1, 2020):**
Historically, Amazon S3 operated under an eventual consistency model for object overwrites (`PUT` to an existing key) and `DELETE` operations, where stale data could be returned briefly during metadata replication. On December 1, 2020, AWS deployed **strong read-after-write consistency** for all `PUT`, `GET`, `LIST`, and `DELETE` requests across all AWS regions. Reading or listing an object immediately after creation, update, or deletion reflects the latest state instantly. Big data and analytics workloads no longer require external coordination layers (such as S3Guard) to prevent consistency anomalies.
