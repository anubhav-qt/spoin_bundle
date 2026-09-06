---
title: Server Concurrency Architectures, I/O Multiplexing, and Connection Sizing
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing
source_date: 2020-04-01
topic_tags:
  - concurrency
  - io multiplexing
  - epoll
  - reactor pattern
  - goroutines
  - connection pooling
  - hikaricp
  - littles law
---

## The C10K Problem and Operating System I/O Multiplexing

The **C10K problem** (formulated by Dan Kegel in 1999) highlighted the inability of existing web servers to handle 10,000 concurrent client connections over standard operating system primitives. Classic servers allocated one OS thread or process per network socket. Because an OS thread carries a dedicated kernel stack (typically 2MB to 8MB), 10,000 idle TCP connections consumed tens of gigabytes of memory purely in stack space, while excessive CPU context switching between active threads overwhelmed the OS scheduler.

Operating systems addressed this scaling limit by advancing from synchronous blocking I/O to event-driven I/O multiplexing:
- **Blocking I/O:** A thread executing a `read()` syscall blocks in the kernel until bytes arrive. Handling multiple sockets demands multiple threads.
- **Non-blocking I/O:** Sockets configured with `O_NONBLOCK` return immediately with `EAGAIN` or `EWOULDBLOCK` when no data is ready. Polling thousands of non-blocking sockets in user space wastes substantial CPU cycles.
- **`select(2)` and `poll(2)`:** Allow a single thread to monitor multiple file descriptors. However, both scale with **$O(N)$ complexity**: on every check, the application must copy an array of all $N$ file descriptors into the kernel. The kernel scans all $N$ descriptors, and user code loops through the entire list to identify which descriptors transitioned to ready. This becomes unviable beyond a few hundred descriptors.
- **`epoll(7)` (Linux), `kqueue(2)` (BSD/macOS), and `IOCP` (Windows):** Provide **$O(1)$ event-driven notification**. Descriptors are registered once with the kernel via `epoll_ctl`. The kernel maintains a ready list populated by hardware network interrupts. When the thread invokes `epoll_wait()`, it sleeps until events occur, returning *only* the specific descriptors ready for reading or writing. Operating system overhead scales with the volume of active I/O, rather than total open connections, enabling a single thread to manage hundreds of thousands of idle connections.

## Server Execution Architectures: Threads versus Event Loops

Backend runtimes organize work according to three primary execution models:

**1. Thread-Per-Request / Multi-Process (Apache Prefork, Classic Rails, Traditional Java Servlet):**
Each incoming client connection is assigned a dedicated operating system thread from a thread pool.
- **Advantages:** Simple programming model; code executes sequentially. An intensive CPU calculation in one thread does not block concurrent requests handled by peer threads.
- **Disadvantages:** High memory overhead per connection. Sockets idling in keep-alive hold OS threads hostage. If active thread count significantly exceeds the number of physical CPU cores, context-switching overhead and CPU cache thrashing degrade overall throughput.

**2. Event-Driven Reactor Pattern / Single-Threaded Event Loop (Node.js/libuv, Nginx, Netty):**
A single thread (or one thread per physical CPU core) runs an infinite loop driving non-blocking I/O over `epoll` or `kqueue`. Sockets waiting for network data consume negligible resources.
- **Advantages:** Extreme connection density. Thousands of concurrent WebSockets or HTTP/2 connections run within tens of megabytes of RAM.
- **Disadvantages: Event Loop Starvation.** Because a single thread executes all application logic, any synchronous, long-running CPU computation (such as synchronous cryptography, massive JSON parsing, or unoptimized regex matching) freezes the entire event loop, halting all concurrent requests across the entire server instance. Intensive CPU tasks must be offloaded to worker thread pools.

## Lightweight User-Space Concurrency: M:N Schedulers

Modern backend languages (such as Go with goroutines, Java with Project Loom Virtual Threads, and Erlang/Elixir on the BEAM virtual machine) implement **M:N concurrency**. The runtime multiplexes $M$ lightweight user-space green threads onto $N$ underlying OS kernel threads.

- **Minimal Memory Overhead:** While an OS thread stack requires 1MB–8MB of fixed memory, a Go goroutine begins with a dynamic **2KB stack** allocated in heap memory that expands and contracts as needed. A backend can comfortably launch 500,000 goroutines simultaneously on moderate hardware.
- **User-Space Context Switching:** The language runtime scheduler executes context switches at function call boundaries, channel communications, or non-blocking I/O invocations without executing a kernel-mode trap. This reduces context-switch latency from microseconds to nanoseconds.

## Database Connection Pooling Lifecycle and Overhead

Establishing a new database connection from scratch for each incoming HTTP request introduces severe performance degradation:
1. TCP three-way handshake (1 network round trip).
2. TLS handshake and cipher negotiation (1 to 2 network round trips).
3. Database authentication, credential exchange, and permission authorization.
4. Process or thread allocation inside the database server (e.g. PostgreSQL forks a complete OS process per connection, allocating private catalog cache and `work_mem` space).

This connection handshake consumes between 50ms and 250ms of latency per request and drives database CPU utilization to 100% purely on connection setup. Connection poolers (such as **HikariCP** in Java, **asyncpg pool** in Python, or **PgBouncer** for PostgreSQL) maintain a pool of pre-established, authenticated database connections, allowing application requests to borrow an active connection, execute queries, and return it immediately.

## Pool Sizing Theory: Brett Wooldridge's Formula and Little's Law

A widespread engineering misconception is that larger connection pools increase database throughput (e.g. configuring 100 or 200 connections for an 8-core database server).

**The Physical Hardware Limit (Brett Wooldridge, author of HikariCP):**
A database server is bounded by physical hardware: CPU cores and disk I/O channels. When the number of concurrent active queries exceeds the number of physical CPU cores, the database engine spends progressively more time on thread context switching, OS scheduler latency, and internal buffer lock contention than on executing SQL queries.
Wooldridge established the authoritative sizing formula:
$$\text{pool\_size} = (\text{cpu\_core\_count} \times 2) + \text{effective\_spindle\_count}$$
On modern servers utilizing high-speed NVMe SSDs, an effective spindle count is typically treated as a small constant (e.g. 1). Thus, a database running on a 16-core CPU server achieves maximum throughput with a connection pool size between 32 and 35. Increasing the pool size beyond this threshold increases query latency and reduces aggregate throughput.

**Little's Law ($L = \lambda W$):**
In queueing theory, Little's Law states that the long-term average number of items in a stationary system ($L$) equals the arrival rate ($\lambda$) multiplied by the average time an item spends in the system ($W$):
- $L$: Average concurrent database connections in active use.
- $\lambda$: Query arrival rate (queries per second).
- $W$: Average query execution time (seconds).

If an application receives 1,000 queries per second ($\lambda = 1000$) and average query execution duration is 10 milliseconds ($W = 0.01\text{s}$), the average number of concurrent connections needed is:
$$L = 1000 \times 0.01 = 10 \text{ connections}$$
Configuring connection pools far in excess of $L$ causes traffic surges to queue within the database kernel rather than shedding load cleanly at the application gateway.
