---
title: Web Performance and Core Web Vitals
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: Google Chrome Web.dev Core Web Vitals Guidance & W3C Web Performance Working Group
source_date: 2024
topic_tags: [frontend-engineering, web-performance, core-web-vitals, lcp, inp, cls, code-splitting, resource-hints]
---

# Web Performance and Core Web Vitals

## Core Web Vitals Metrics and Production Thresholds

The Core Web Vitals framework isolates three distinct dimensions of user experience: loading performance, interface responsiveness, and visual stability:

1. **Largest Contentful Paint (LCP):** Measures perceived loading speed by recording the render timestamp of the largest visual image, video poster, or text block within the viewport.
   - *Good:* $\le 2.5\text{ seconds}$
   - *Needs Improvement:* $2.5\text{s} - 4.0\text{s}$
   - *Poor:* $> 4.0\text{ seconds}$
2. **Interaction to Next Paint (INP):** Measures continuous interface responsiveness by evaluating the latency of every user click, tap, and keyboard interaction throughout the entire session. INP officially replaced First Input Delay (FID) as a stable Core Web Vital on March 12, 2024.
   - *Good:* $\le 200\text{ milliseconds}$
   - *Needs Improvement:* $200\text{ms} - 500\text{ms}$
   - *Poor:* $> 500\text{ milliseconds}$
3. **Cumulative Layout Shift (CLS):** Measures visual stability by quantifying unexpected layout shifts that occur during the page lifecycle.
   - *Good:* $\le 0.10$
   - *Needs Improvement:* $0.10 - 0.25$
   - *Poor:* $> 0.25$

## Largest Contentful Paint (LCP) Diagnostic Breakdown

Optimizing LCP requires breaking the metric down into four distinct temporal phases:
- **Time to First Byte (TTFB):** The elapsed time from initial navigation until the browser receives the first byte of the HTML response. High TTFB indicates server-side compute delays, database query latency, or excessive CDN edge hops.
- **Resource Load Delay:** The time between initial HTML arrival and the browser discovering and initiating the fetch for the LCP resource. Hidden background CSS images or client-rendered image components delay resource discovery.
- **Resource Load Duration:** The duration required to download the LCP asset over the network, driven by file size, image encoding (AVIF/WebP vs legacy JPEG), and bandwidth constraints.
- **Element Render Delay:** The time between when the LCP asset finishes downloading and when the browser completes layout, paint, and compositing to render it on screen. Render delay is primarily caused by render-blocking stylesheets or main-thread JavaScript execution.

Prioritizing the LCP element using the `fetchpriority="high"` HTML attribute prompts browser speculative parsers to allocate maximum network stream bandwidth to the primary hero image ahead of non-critical assets.

## Interaction to Next Paint (INP) Mechanics and Optimization

Unlike First Input Delay (which measured only the initial interaction on page load), INP evaluates all discrete user interactions throughout the page lifecycle, reporting the worst interaction latency (or 98th percentile for pages with hundreds of user actions).

Every user interaction encompasses three sequential phases:
1. **Input Delay:** The duration an input event spends waiting in the browser task queue because the main thread is occupied executing long tasks (tasks exceeding 50ms).
2. **Processing Duration:** The time required to execute author-defined JavaScript event callbacks registered for that interaction.
3. **Presentation Delay:** The time required after event handlers complete for the browser engine to recalculate styles, execute layout, paint display lists, and submit the new composited frame to the GPU for presentation.

Optimizing INP requires breaking monolithic JavaScript tasks into non-blocking chunks using `scheduler.yield()` or `setTimeout()`, deferring non-urgent state transitions with concurrent rendering (`startTransition`), avoiding synchronous layout thrashing during event callbacks, and keeping event handlers lightweight.

## Cumulative Layout Shift (CLS) and Layout Stability

Cumulative Layout Shift quantifies unexpected spatial displacements of visible elements between frames. Layout shift occurs when an element changes its start position (top/left coordinates) relative to viewport boundaries without being preceded by a direct user gesture (such as clicking an accordion).

The Layout Shift Score is calculated as:
$$\text{Layout Shift Score} = \text{Impact Fraction} \times \text{Distance Fraction}$$
- The *Impact Fraction* measures the total area of the viewport affected by unstable elements across both the initial and moved frames.
- The *Distance Fraction* measures the greatest distance any unstable element moved relative to the viewport's height or width.

Primary causes of high CLS include images and video containers rendered without explicit HTML `width` and `height` attributes (or CSS `aspect-ratio`), dynamic third-party ad insertions that push content down, and Web Fonts causing Flash of Invisible Text (FOIT) or Flash of Unstyled Text (FOUT) when switching font metrics. Modern browsers reserve appropriate aspect ratio dimensions before image bytes arrive if HTML dimension attributes are declared.

## Critical Resource Hints and Preloading Strategies

Resource hints inform the browser's networking stack about upcoming resource requirements before the HTML parser encounters them in markup:

- `<link rel="preload" as="..." href="...">`: Instructs the browser to initiate an immediate, high-priority fetch for an essential resource required in the current page view (such as the LCP hero image or primary Web Font). Preloading resources not used within 3 seconds of page load triggers browser console warnings and wastes mobile bandwidth.
- `<link rel="preconnect" href="...">`: Resolves DNS lookup, TCP handshake, and TLS negotiation ahead of time with a critical third-party origin (such as an external API or font CDN), eliminating up to 3 round-trip times (RTTs) before the first asset request.
- `<link rel="dns-prefetch" href="...">`: Resolves DNS resolution early without executing full TLS handshakes, providing a lightweight fallback for secondary origins.
- `<link rel="prefetch" href="...">`: Instructs the browser to download resources during network and CPU idle periods for high-probability subsequent route navigations.

## JavaScript Bundle Governance: Code Splitting and Tree Shaking

Unchecked client JavaScript bundle growth directly degrades Core Web Vitals by inflating download duration, extending V8 parsing/compilation times, and increasing main-thread contention. Bundle governance relies on two structural techniques:

- **Route-Based Code Splitting and Dynamic Imports:** Rather than shipping a monolithic single-page application bundle, applications leverage ES dynamic imports (`import('./FeatureModal.js')`) to partition code into discrete asynchronous chunks. The browser downloads and compiles only the code strictly necessary to render the active route and immediate viewport, loading secondary features on demand.
- **Tree Shaking (Dead Code Elimination):** Relies on the static module structure of ECMAScript modules (`import` and `export` statements are static and cannot be conditionally declared inside runtime blocks). Build bundlers (such as Rollup, esbuild, and Webpack) construct an Abstract Syntax Tree of the application, trace imported symbol references through the dependency graph, and exclude unused exported functions and variables from the final emitted distribution bundle.
