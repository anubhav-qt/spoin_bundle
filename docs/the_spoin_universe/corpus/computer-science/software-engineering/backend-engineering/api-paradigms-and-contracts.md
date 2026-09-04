---
title: API Architectural Styles, Interface Contracts, and Edge Routing
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: https://www.rfc-editor.org/rfc/rfc9110
source_date: 2022-06-06
topic_tags:
  - api design
  - rest
  - graphql
  - grpc
  - protocol buffers
  - webhooks
  - api gateway
---

## REST Constraints and the Richardson Maturity Model

Representational State Transfer (REST) is an architectural style defined by Roy Fielding (2000) for distributed hypermedia systems. REST mandates six architectural constraints: client-server separation, statelessness (all session state is held by the client), cacheability, a uniform interface, a layered system (intermediaries like proxies and gateways remain transparent to the client), and optional code-on-demand.

The Richardson Maturity Model (introduced by Leonard Richardson in 2008) classifies HTTP API implementations into four tiers of REST adoption:
- **Level 0 (The Swamp of POX):** The API exposes a single URI endpoint and uses a single HTTP method (typically `POST`) as an opaque transport tunnel for remote procedure calls (e.g. XML-RPC, SOAP, JSON-RPC).
- **Level 1 (Resources):** The API decomposes system capabilities into individual resource URIs (such as `/orders/1042`), but continues to rely on a single HTTP method (`POST`) for all operations.
- **Level 2 (HTTP Verbs):** The API aligns operations with standardized HTTP methods defined in RFC 9110 and returns appropriate HTTP status codes (such as `200 OK`, `201 Created`, `204 No Content`, `400 Bad Request`, `404 Not Found`, and `409 Conflict`). This is the dominant architectural level of production "RESTful" APIs.
- **Level 3 (Hypermedia Controls / HATEOAS):** Responses embed hypermedia controls (`_links`, HAL, JSON:API) that advertise permissible next state transitions dynamically. Clients navigate the application graph through discovered links rather than hardcoding URI routing schemes.

RFC 9110 defines critical behavioral contracts across HTTP methods:
- **Safe Methods:** Methods whose semantics are strictly read-only and produce no state mutation on the origin server (`GET`, `HEAD`, `OPTIONS`, `TRACE`). Safe methods are cacheable by default.
- **Idempotent Methods:** Methods where the intended effect on server state of multiple identical requests is identical to that of a single request. `PUT` (complete resource replacement) and `DELETE` (resource removal) are idempotent: executing `DELETE /items/5` repeatedly leaves the item absent, regardless of whether the HTTP response transitions from `204 No Content` to `404 Not Found`. `GET` and `HEAD` are safe and trivially idempotent.
- **Non-Idempotent Methods:** `POST` (submits payload for resource-specific processing or creation) and `PATCH` (applies partial modifications) are non-idempotent by default. Repeating a `POST` creates duplicate resources or triggers duplicate side effects. `PATCH` can be idempotent when setting absolute field values, but is non-idempotent when applying delta mutations (such as incrementing an integer).

## GraphQL Schema Execution and the N+1 Query Resolution

GraphQL (developed at Facebook in 2015 by Lee Byron and standardized by the GraphQL Foundation) provides a query language and runtime for API interactions. Clients issue query documents against a single HTTP endpoint (`POST /graphql`), specifying the exact field projection required. This design eliminates both over-fetching (retrieving unused attributes) and under-fetching (requiring sequential round-trips to aggregate related resources).

A GraphQL server defines its contract using the Schema Definition Language (SDL), establishing object types, fields, queries, mutations, and subscriptions. The execution engine parses an incoming query string into an Abstract Syntax Tree (AST), validates it against the schema, and executes field resolver functions recursively via depth-first traversal. Each field resolver matches the signature `resolve(parent, args, context, info)`.

Independent resolver execution introduces the **N+1 query problem**. If a query fetches 100 users and their associated posts, the user resolver executes one query to fetch the list (`SELECT * FROM users LIMIT 100`), and the post resolver triggers 100 independent queries (`SELECT * FROM posts WHERE user_id = ?`), generating $1 + 100 = 101$ database queries.

The standard mitigation is **DataLoader** (introduced by Lee Byron, 2015). DataLoader leverages asynchronous microtask scheduling (such as the event loop tick) to coalesce individual lookup requests into a single batched database query (`SELECT * FROM posts WHERE user_id IN (1, 2, ..., 100)`). DataLoader also maintains an in-memory memoization cache for the duration of a **single HTTP request**, ensuring that duplicate requests for the same entity ID within a single query execution return cached instances. DataLoader instances must never be shared across separate HTTP requests or users, as cross-request cache persistence creates data leakage and authorization bypass vulnerabilities.

## gRPC Wire Protocol and Protocol Buffers Serialization

gRPC is an open-source remote procedure call framework hosted by the Cloud Native Computing Foundation (CNCF). gRPC uses Protocol Buffers (proto3) as its Interface Definition Language (IDL) and binary serialization format. In proto3, messages are defined with typed fields assigned integer field tags (e.g. `string name = 1;`). Protobuf encodes data using Tag-Length-Value (TLV) and variable-length integers (varints), producing serialized payloads significantly smaller than equivalent JSON or XML. Backward and forward compatibility is maintained by ensuring field tags are never modified or reused; deprecated tags are marked `reserved`.

gRPC operates natively over HTTP/2 (and HTTP/3), using HTTP/2 streams to support four RPC archetypes:
1. **Unary:** Single request message yielding a single response message.
2. **Server Streaming:** Single request message yielding a stream of response messages.
3. **Client Streaming:** Stream of request messages yielding a single response message.
4. **Bidirectional Streaming:** Two independent streams transmitting messages concurrently.

Every message transmitted inside an HTTP/2 `DATA` frame is prefixed with a **5-byte header**:
- Byte 0: `Compressed-Flag` (0 for uncompressed payload; 1 for payload compressed via the algorithm declared in the `grpc-encoding` header).
- Bytes 1–4: `Message-Length` (unsigned 32-bit integer in big-endian byte order).
- Bytes 5 onward: Serialized Protocol Buffer payload.

At the transport layer, gRPC requests return an HTTP status of `200 OK` under normal operation, even when the RPC method fails. Application-level success or failure is conveyed via HTTP/2 **Trailers** appended after data frames:
- `grpc-status`: An integer error code (e.g. `0` for OK, `3` for INVALID_ARGUMENT, `4` for DEADLINE_EXCEEDED, `5` for NOT_FOUND, `14` for UNAVAILABLE).
- `grpc-message`: An optional error description string.
- `grpc-status-details-bin`: An optional binary trailer containing a serialized `google.rpc.Status` message to convey rich error structures and field validation failures.

## Webhook Callbacks and Asynchronous Integration

Webhooks implement a reverse API pattern: rather than an external client polling an API for updates, the service acts as an HTTP client and dispatches an HTTP `POST` request to a customer-registered callback URL when a domain event occurs.

Securing webhooks requires verifying authenticity and mitigating replay attacks:
- **HMAC Signatures:** The sender signs the raw payload with a pre-shared secret using HMAC-SHA256 and transmits the hex digest in a custom header (e.g. `X-Signature-256` or `Stripe-Signature`). The receiver computes the HMAC over the raw request body using its local secret and verifies equality using a constant-time comparison to prevent timing attacks.
- **Timestamp Verification:** Senders include a Unix epoch timestamp in the signature header. Receivers reject requests whose timestamp deviates from local clock time by more than a tolerance window (typically 300 seconds), defeating network replay attacks.

Because external receiver endpoints may experience latency or downtime, webhook dispatch systems decouple event generation from delivery using persistent message queues. Dispatchers execute retries according to an exponential backoff schedule with jitter (e.g. retrying at intervals of 5s, 1m, 15m, 1h, 6h, 24h). Receiver endpoints are expected to return an HTTP `2xx` response within 5 seconds; long-running processing must be offloaded to an asynchronous background worker after acknowledging the webhook.

## Reverse Proxies and Edge API Gateways

In microservice and distributed backend architectures, edge reverse proxies (such as Nginx, Envoy, Traefik, or HAProxy) decouple client-facing networking from internal service runtimes. The proxy terminates incoming public TLS connections, offloading cryptographic overhead and managing TLS certificates.

API gateways operate at Layer 7 (Application Layer), inspecting incoming requests to execute cross-cutting policies:
- **Path-Based Routing:** Routes traffic based on URI prefix and method (e.g. dispatching `/api/v1/billing/*` to internal billing microservices while routing `/api/v1/auth/*` to identity services).
- **Traffic Shaping and Rate Limiting:** Enforces volumetric limits per IP, API key, or tenant identifier at the perimeter, dropping abusive traffic before downstream compute resources are consumed.
- **Header Transformation and Context Injection:** Injects trace context headers (such as `traceparent` and `X-Request-ID`), strips sensitive internal headers, and enforces Cross-Origin Resource Sharing (CORS) headers.
- **Protocol Translation:** Transcodes external HTTP/1.1 or REST calls into internal gRPC calls, insulating backend microservices from external transport constraints.
