---
title: Transport Layer Protocols and HTTP Wire Evolution
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: https://www.rfc-editor.org/rfc/rfc9110
source_date: 2022-06-06
topic_tags:
  - networking
  - tcp
  - udp
  - http
  - http2
  - http3
  - quic
  - websockets
  - server sent events
---

## Transport Layer Foundations: TCP and UDP Mechanics

Transport layer protocols govern how data moves between processes across host networks. Transmission Control Protocol (TCP, standardized in RFC 793 and modernized in RFC 9293) provides a connection-oriented, reliable, ordered byte stream. Before transmitting application data, TCP requires a three-way handshake (`SYN`, `SYN-ACK`, `ACK`), adding one full round-trip time (RTT) of latency. TCP guarantees in-order delivery via sequence numbers and receiver acknowledgments (`ACK`). Flow control is enforced through the receiver window (`rwnd`), capping unacknowledged bytes to prevent buffer overflow. Congestion control algorithms (such as CUBIC and BBR) dynamically adjust the congestion window (`cwnd`) based on packet loss or bandwidth-delay product measurements. A critical constraint of TCP is transport-level Head-of-Line (HoL) blocking: if a single segment is lost in transit, subsequent segments already held in the receiver kernel buffer cannot be read by the application until the missing segment is retransmitted.

User Datagram Protocol (UDP, RFC 768) provides a connectionless, minimal message transport without reliability, sequencing, flow control, or congestion management. A UDP packet has an 8-byte header containing source port, destination port, payload length, and checksum. UDP incurs zero handshake latency (0-RTT), carries no retransmission overhead, and delivers packets directly to the application layer in whatever order they arrive. UDP serves as the transport substrate for protocols requiring predictable latency over strict completeness (DNS, real-time media), as well as custom user-space transport protocols like QUIC.

## HTTP/1.1 and HTTP/2: From Plaintext Delimiting to Binary Framing

In June 2022, the Internet Engineering Task Force (IETF) obsoleted RFC 7230–7235 and RFC 7540, establishing a modular specification suite: RFC 9110 (HTTP Semantics), RFC 9111 (HTTP Caching), RFC 9112 (HTTP/1.1), RFC 9113 (HTTP/2), and RFC 9114 (HTTP/3). RFC 9110 defines uniform semantics—methods, status codes, and header fields—shared across all wire implementations.

HTTP/1.1 (RFC 9112) transmits plaintext messages over TCP. Persistent connections (`Connection: keep-alive`) amortize TCP handshakes across sequential requests on the same connection. While HTTP/1.1 introduced pipelining to allow dispatching requests without awaiting responses, servers must strictly return responses in the order received. Consequently, a stalled upstream request blocks all subsequent responses on that socket (application-level HoL blocking), leading clients to open up to six parallel TCP connections per host.

HTTP/2 (RFC 9113) addresses application-level HoL blocking by replacing plaintext delimited streams with a binary framing layer over a single TCP connection. Communication is divided into discrete binary frames (`HEADERS`, `DATA`, `SETTINGS`, `RST_STREAM`) multiplexed over independent bidirectional streams identified by stream IDs. HTTP/2 employs HPACK (RFC 7541) to compress repetitive headers using static and dynamic indexing tables. However, because HTTP/2 multiplexes streams over a single TCP byte stream, packet loss causes transport-level HoL blocking: when one TCP packet drops, all multiplexed HTTP/2 streams freeze until retransmission completes.

## HTTP/3 and QUIC: Eliminating Head-of-Line Blocking over UDP

HTTP/3 (RFC 9114) maps HTTP semantics onto the QUIC transport protocol (RFC 9000), which operates over UDP. QUIC integrates transport setup and TLS 1.3 cryptographic negotiation into a single 1-RTT handshake (or 0-RTT for resumed sessions). QUIC implements stream multiplexing natively at the transport layer: each stream maintains independent flow control and byte offsets. Dropping a packet on stream A delays only stream A, allowing streams B and C to proceed without stall.

To eliminate HoL blocking during header decompression, HTTP/3 replaces HPACK with QPACK (RFC 9204), which uses separate unidirectional control streams to synchronize encoder state asynchronously. Furthermore, QUIC identifies connections via opaque Connection IDs (CIDs) rather than the network 4-tuple `(source IP, source port, destination IP, destination port)`, allowing active client sessions to survive IP address changes (connection migration) across Wi-Fi and mobile networks.

## Real-Time Full-Duplex Channels: WebSockets versus Server-Sent Events

Applications requiring low-latency server-initiated communication rely on WebSockets or Server-Sent Events (SSE) instead of short or long HTTP polling.

The WebSocket Protocol (RFC 6455) provides full-duplex, bidirectional communication over a single long-lived TCP connection. The session begins with an HTTP/1.1 or HTTP/2 handshake featuring `Upgrade: websocket` and `Connection: Upgrade` headers, accompanied by a `Sec-WebSocket-Key`. Upon receiving `HTTP/1.1 101 Switching Protocols`, the socket ceases HTTP semantics and switches to WebSocket framing. WebSockets transmit data in lightweight frames (2 to 10 bytes overhead) supporting both UTF-8 text and raw binary formats (`ArrayBuffer`, `Blob`). Senders and receivers transmit independently at any moment. WebSockets do not include application-level message schemas, reconnection logic, or pub/sub multiplexing; these must be implemented in user code or via application protocols like STOMP or WAMP.

Server-Sent Events (SSE), standardized by WHATWG in the HTML Living Standard, provide a unidirectional channel where a server pushes text updates to a client over standard HTTP. The client initiates a standard HTTP `GET` request expecting the `text/event-stream` media type. The server leaves the connection open, streaming UTF-8 event blocks separated by double newlines:
```text
event: order_update
id: 1042
retry: 5000
data: {"order_id": 1042, "status": "shipped"}
```
SSE is natively supported in web browsers via the `EventSource` API. Unlike WebSockets, SSE automatically handles reconnection using the interval specified in the `retry` field. When reconnecting, the browser transmits a `Last-Event-ID` header containing the last received message ID, allowing the backend to replay missed events. SSE traverses HTTP proxies, firewalls, and load balancers without custom protocol negotiation, but is restricted to UTF-8 text; binary payloads require encoding (such as Base64), which adds roughly 33% bandwidth overhead.
