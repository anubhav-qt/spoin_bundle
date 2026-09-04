---
title: Web Rendering Architectures and Server Components
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: React 19 Documentation & Astro Islands Architecture Specification
source_date: 2024
topic_tags: [frontend-engineering, rendering-architectures, ssr, ssg, isr, islands-architecture, rsc, server-components]
---

# Web Rendering Architectures and Server Components

Web rendering architectures govern how application code, data, and layout instructions are distributed between edge servers and client browsers. Over recent web generations, architectures have evolved from monolithic single-page client bundles toward hybrid server-client primitives, selective hydration models, and component-level execution boundaries.

## Taxonomy: CSR, SSR, SSG, and ISR

Web rendering models partition work along temporal (build time vs request time) and spatial (server vs client) boundaries:

- **Client-Side Rendering (CSR / SPA):** The web server returns an empty HTML shell (`<div id="root"></div>`) and a JavaScript bundle. The browser downloads, parses, and executes the script, which queries backend APIs and dynamically constructs the DOM. While offering fluid client-side route transitions, CSR suffers from delayed First Contentful Paint (FCP) and heavy initial CPU parsing costs.
- **Server-Side Rendering (SSR):** The server executes component code per incoming HTTP request, populating dynamic data and returning fully rendered HTML. The browser displays visual content immediately upon HTML arrival, but cannot handle user interaction until client JavaScript downloads and executes a hydration pass.
- **Static Site Generation (SSG):** Pages are pre-rendered into static HTML and CSS files at build time and distributed across global Content Delivery Networks (CDNs). SSG delivers minimal Time-to-First-Byte (TTFB) and high availability, but build duration scales linearly with page count, making it unsuitable for rapidly changing datasets.
- **Incremental Static Regeneration (ISR):** Augments SSG by enabling individual static pages to be regenerated in the background on the server upon incoming traffic after an expiration window (`revalidate`), serving cached pages instantaneously while atomically updating the CDN cache.

## The Hydration Bottleneck and the "Uncanny Valley"

Traditional SSR implementations suffer from a fundamental architectural constraint known as monolithic hydration. When a server-rendered HTML page reaches the client, the visual presentation is complete, but the DOM lacks active JavaScript event listeners and reactive state bindings.

To achieve interactivity, the browser must:
1. Download the complete client JavaScript application bundle.
2. Parse and compile the script on the main thread.
3. Execute the entire component tree from the root node down to recreate the in-memory Virtual DOM.
4. Diff the regenerated virtual tree against the existing server-rendered HTML nodes to attach event listeners and reconcile initial state.

This gap creates the "Uncanny Valley" (or Time-to-Interactive delay): users observe rendered buttons, search inputs, and links, but interacting with them triggers no response because the main thread is blocked re-executing code that already ran on the server. Furthermore, monolithic hydration is all-or-nothing: a single slow component delays interactivity for the entire page.

## Streaming SSR with Out-of-Order Selective Hydration

Streaming SSR, popularized by React Suspense and HTTP/1.1 chunked transfer encoding, eliminates the monolithic hydration bottleneck by breaking HTML generation and hydration into progressive streams.

The server immediately flushes the primary document shell and static page sections as initial HTML chunks. Slow asynchronous data dependencies (such as complex database queries or external API calls) are wrapped in boundary markers (`<Suspense>`). While those queries resolve, the server streams lightweight fallback placeholders (e.g., loading skeletons).

As background data resolves, the server streams inline `<template>` chunks containing the resolved HTML, accompanied by minimal inline scripts that swap the fallback placeholder with the real content directly in the DOM. On the client, selective hydration hydrates completed sections independently. If a user clicks an unhydrated component before others, the runtime prioritizes that specific subtree's hydration ahead of the rest of the queue.

## Islands Architecture: Component-Level Partial Hydration

Pioneered by Astro and Fresh, the Islands Architecture abandons the concept of hydrating an entire page tree. Instead, an Islands-based application renders pages on the server as pure static HTML by default, shipping zero client-side JavaScript for typography, layouts, footers, and static marketing sections.

Dynamic, interactive UI elements exist as isolated "islands" embedded within the static HTML ocean. Each island functions as an autonomous mini-application that hydrates independently according to explicit client directives:
- `client:load`: Hydrates immediately upon page load for critical interactive controls.
- `client:idle`: Delays hydration until the main thread enters an idle phase after initial render.
- `client:visible`: Leverages `IntersectionObserver` to withhold JavaScript download and execution until the element scrolls into the user's viewport.

By isolating hydration to interactive components, Islands Architecture dramatically reduces client-side JavaScript payloads, eliminates unnecessary Virtual DOM diffing of static content, and protects Core Web Vitals.

## React Server Components (RSC) and Server Actions

Released as a core production feature in React 19 (December 2024), React Server Components (RSC) introduce an explicit language-level boundary between server-only and client components within a unified component tree:

- **Server Components (Default):** Execute exclusively on the server. They have direct access to backend resources (databases, filesystem, private microservices, environment secrets) and are never bundled into the client JavaScript download (0 KB client bundle size impact).
- **Client Components (`'use client'`):** Demarcate the boundary where client interactivity begins. They are compiled into client bundles to manage local state, event listeners, and browser APIs.
- **RSC Wire Protocol:** Rather than returning raw HTML or client JavaScript, Server Components serialize into an asynchronous streaming JSON-like stream (the RSC payload). This stream describes the rendered virtual DOM tree, including references to client component chunks and serialized props. The client runtime consumes this stream, interleaving interactive client components without losing active client-side UI state during data refetches.
- **Server Actions (`'use server'`):** Enable asynchronous server-side functions to be invoked directly from Client Components or standard HTML forms, managing data mutations, server revalidation, and optimistic updates through standardized primitives.
