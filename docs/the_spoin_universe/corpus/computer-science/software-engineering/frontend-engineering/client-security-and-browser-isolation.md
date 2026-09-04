---
title: Client Security and Browser Isolation
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: W3C Web Application Security Working Group & MDN Web Security Documentation
source_date: 2024
topic_tags: [frontend-engineering, security, sop, xss, csp, cors, trusted-types, subresource-integrity]
---

# Client Security and Browser Isolation

## The Same-Origin Policy (SOP) Foundation

The Same-Origin Policy (SOP) serves as the foundational security boundary of the web platform. Under SOP, an origin is defined strictly by the tuple of `<scheme, host, port>`:
- Two URLs share an identical origin if and only if all three components match exactly (`https://example.com:443`).
- Differences in protocol (`http` vs `https`), subdomain (`api.example.com` vs `app.example.com`), or port (`:8080` vs `:443`) establish distinct, isolated origins.

SOP restricts client scripts running in one origin from reading or manipulating the Document Object Model (DOM), cookies, session storage, local storage, or `XMLHttpRequest` / `fetch` response bodies originating from a different origin.

While browsers permit cross-origin *embedding* of passive resources (such as images via `<img>`, external scripts via `<script>`, and stylesheets via `<link>`), JavaScript running in the embedding origin cannot inspect the internal byte streams or header contents of those embedded cross-origin resources.

## Cross-Site Scripting (XSS) Mechanics and Defenses

Cross-Site Scripting occurs when an attacker injects malicious client executable code (typically JavaScript) into an application context, executing with the full privileges of the victim's session:

- **Stored XSS:** Malicious payloads are permanently stored in the backend database (e.g., in a forum post or profile comment) and served to subsequent users during standard page rendering.
- **Reflected XSS:** Malicious payloads are embedded directly in request URLs or parameters (e.g., search queries) and immediately reflected back in the server response without storage.
- **DOM-Based XSS:** The attack payload never touches the backend server. The client-side JavaScript itself reads untrusted input from an insecure DOM source (`location.search`, `location.hash`, `document.referrer`) and insecurely passes it directly to an execution sink (`innerHTML`, `outerHTML`, `document.write()`, `eval()`).

Defenses against XSS require a multi-layered approach:
1. **Context-Aware Encoding:** Escaping sensitive characters (`&`, `<`, `>`, `"`, `'`) when interpolating data into HTML text contexts.
2. **Robust Sanitization:** Utilizing battle-tested sanitizers like DOMPurify to strip executable scripts, event handlers (`onload`, `onerror`), and dangerous schemes (`javascript:`) before DOM insertion.
3. **The W3C Trusted Types API:** Locks down dangerous DOM sinks at the engine level. When enforced, browsers reject plain strings assigned to `element.innerHTML`, requiring developers to supply a validated `TrustedHTML` object generated via an audited policy.

## Content Security Policy (CSP Level 3) Nonce Architecture

Content Security Policy (CSP) is an HTTP response header that restricts the sources from which browsers are permitted to load and execute scripts, styles, images, and fonts, providing a primary defense-in-depth mitigation against XSS:

`Content-Security-Policy: default-src 'self'; script-src 'nonce-rAnd0m123' 'strict-dynamic'; object-src 'none'; base-uri 'none';`

- **Cryptographic Nonces:** The web server generates a cryptographically random, single-use base64 string (a nonce) per incoming HTTP request, injecting it into both the CSP header and valid `<script nonce="...">` tags. Any injected inline script lacking the exact nonce is blocked by the browser.
- **`strict-dynamic` Directive:** Simplifies deployment by specifying that any script explicitly trusted via a valid nonce is permitted to load child dependency scripts dynamically, eliminating the need to maintain fragile domain whitelists.
- **`object-src 'none'`:** Disables legacy plugins and Flash runtimes.
- **`frame-ancestors 'none'`:** Prevents clickjacking attacks by forbidding external domains from rendering the page within an `<iframe>`, superseding the legacy `X-Frame-Options` header.

## Cross-Origin Resource Sharing (CORS) Mechanics

Cross-Origin Resource Sharing (CORS) provides a controlled exception mechanism allowing servers to relax the Same-Origin Policy for explicit cross-origin HTTP requests.

- **Simple Requests:** Standard `GET`, `HEAD`, or `POST` requests using standard content types (`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`) do not trigger a preflight. The browser dispatches the request directly, appending an `Origin: https://app.example.com` header. The server responds with `Access-Control-Allow-Origin: https://app.example.com`.
- **Preflight Requests (`OPTIONS`):** Requests that utilize non-simple HTTP verbs (`PUT`, `DELETE`, `PATCH`) or custom headers (`Authorization`, `Content-Type: application/json`) trigger an automatic browser preflight check. Before dispatching the actual request, the browser sends an `OPTIONS` request querying `Access-Control-Request-Method` and `Access-Control-Request-Headers`. Only if the server responds with confirming `Access-Control-Allow-Methods` and `Access-Control-Allow-Headers` will the browser dispatch the real payload.
- **Critical Misconception:** CORS is an enforcement mechanism implemented by the *browser client*, not a server firewall. If CORS headers are missing, the server still receives and processes the incoming request; the browser simply prevents client JavaScript from inspecting the returned response payload.

## Subresource Integrity (SRI) and Browser Process Isolation

Modern web applications depend heavily on third-party Content Delivery Networks (CDNs) for static assets, introducing supply-chain risks if a CDN is compromised:

- **Subresource Integrity (SRI):** Enables browsers to verify that fetched third-party scripts have not been maliciously manipulated. Markup declares a cryptographic hash attribute: `<script src="https://cdn.example.com/lib.js" integrity="sha384-oqVuAfXRKap7fdgcCY5uykM6+R9GqQ8K/uxy9rx7HNQlGYl1kPzQho1wx4JwY8wC" crossorigin="anonymous">`. Before executing the script, the browser hashes the downloaded file and compares it against the declared digest; if the digests do not match, execution is blocked.
- **Cross-Origin Opener Policy (COOP):** `Cross-Origin-Opener-Policy: same-origin` isolates top-level browsing contexts, preventing cross-origin popup windows from obtaining references to `window.opener`.
- **Cross-Origin Embedder Policy (COEP):** `Cross-Origin-Embedder-Policy: require-corp` guarantees that a document can only load external resources that have explicitly opted into cross-origin sharing. Enforcing COOP and COEP enables browsers to unlock high-resolution timers (`performance.now()`) and multi-threaded shared memory (`SharedArrayBuffer`) safely without vulnerability to Spectre-style side-channel attacks.
