---
title: Reactivity, Component Models, and State Topologies
kind: topic_source
category: computer science
sub_category: software engineering
scope: survey
source: React Architecture Documentation & TC39 Signals Specification Proposal
source_date: 2024
topic_tags: [frontend-engineering, reactivity, virtual-dom, signals, state-management, fiber, client-state]
---

# Reactivity, Component Models, and State Topologies

Modern frontend engineering structures user interfaces into composable, encapsulated component trees that synchronize view representations with underlying application state. Framework architectures manage this synchronization through divergent reactivity paradigms, ranging from coarse-grained Virtual DOM reconciliation to fine-grained reactive dependency graphs and specialized state topologies.

## Virtual DOM Reconciliation and the React Fiber Architecture

The Virtual DOM (VDOM) paradigm abstracts direct browser Document Object Model manipulation behind an in-memory tree representation of lightweight JavaScript objects. When application state mutates, the component tree re-executes, generating a new Virtual DOM snapshot that is algorithmically diffed against the preceding snapshot to compute the minimal set of real DOM mutations.

The React Fiber architecture refactored traditional recursive call-stack reconciliation into an iterative singly-linked tree of Fiber nodes (`child`, `sibling`, `return`). Fiber converts rendering into a cooperative, interruptible scheduler:
- The *Render Phase* traverses the Fiber tree asynchronously, computing changes without touching the real DOM. Work can be paused, yielded to handle high-priority browser input events, or discarded if newer state arrives.
- The *Commit Phase* operates synchronously, applying computed DOM insertions, updates, and deletions in a single batch, preventing intermediate visual inconsistencies.

Fiber maintains a double-buffering model: a `current` tree corresponds to the visual DOM currently rendered on screen, while a `workInProgress` tree is constructed in memory during the render phase. Upon successful completion of the commit phase, the engine atomically swaps pointers.

## Fine-Grained Reactivity and Signals

Fine-grained reactivity models, pioneered by SolidJS and adopted by modern frameworks (Svelte 5 Runes, Preact Signals, Vue 3, and the TC39 Stage 1 Signals proposal), decouple reactivity from component boundary re-execution entirely. State is represented through primitive reactive cells:
- `Signal.State`: A mutable value container that tracks active subscribers.
- `Signal.Computed`: A memoized derived calculation that automatically records dependencies upon evaluation and caches its result until an upstream dependency invalidates.
- `Effect`: A reactive observer that runs side-effects when its captured dependencies transition.

Dependency tracking operates automatically via a global subscriber stack. When a computed value or effect evaluates, it pushes itself onto the subscriber stack. Any Signal read during that execution registers the top-of-stack observer as a subscriber.

When a Signal mutates, it notifies its direct subscribers. Updates traverse a directed acyclic graph (DAG) using topological sorting. This prevents "glitches"—transient states where derived values evaluate against partially updated dependencies in diamond-shaped dependency graphs.

## Architectural Tradeoff: Virtual DOM Diffing vs Fine-Grained Signals

The architectural divergence between Virtual DOM and Fine-Grained Signals represents a fundamental tradeoff between mental model simplicity and runtime execution efficiency:

Virtual DOM frameworks treat components as pure functions of state that execute repeatedly. This simplifies functional composition and dynamic templating, but incurs overhead: every state update triggers top-down component re-renders, allocating new object trees and diffing nodes, requiring manual memoization optimizations (`useMemo`, `useCallback`, `React.memo`) to avoid redundant re-renders.

Fine-Grained Signals execute component setup code exactly once during initial mount. Component functions do not re-execute when state updates; instead, the Signal links directly to the specific real DOM text node or attribute binding. Mutating a signal updates only the targeted DOM node with zero diffing overhead and minimal garbage collection pressure, but introduces tracking overhead for reactive subscription graphs.

## State Management Topologies: From Flux to Atomic State

Application state architectures partition data along distinct topological boundaries based on scope, lifetime, and mutation frequency:

1. **Local Component State:** Encapsulated within a single component instance lifecycle (e.g., input field values, toggle states). State terminates when the component unmounts.
2. **Context / Inversion of Control:** Shares data across an ancestor component subtree without explicit prop drilling. While convenient for ambient settings (themes, user localization), context updates trigger re-renders across all consuming components unless split into fine-grained context providers.
3. **Unidirectional Global Stores (Flux / Redux / Zustand):** Centralizes application state into a single immutable store. State transitions occur exclusively by dispatching explicit action objects processed through deterministic reducer functions. This guarantees predictable, debuggable state transitions with comprehensive time-travel debugging capabilities.
4. **Atomic State (Recoil / Jotai):** Replaces centralized monolithic stores with isolated, composable units of state called atoms. Components subscribe directly and exclusively to individual atoms, ensuring that updating one atom re-renders only its precise subscribers without affecting the wider component hierarchy.

## Server-Cache State Synchronization

A critical architectural advance in modern frontend development is the formal decoupling of client UI state from asynchronous Server State. Libraries such as TanStack Query and SWR treat server data not as persistent local state, but as a temporary, asynchronous client-side cache of remote database records.

Server-cache architectures resolve complex operational challenges out of the box:
- **Automatic Request Deduplication:** Merges simultaneous requests for identical query keys across disparate components into a single network round-trip.
- **Stale-While-Revalidate Caching:** Serves stale data from the local memory cache immediately to satisfy instant rendering, while asynchronously executing background network fetches to update data transparently.
- **Garbage Collection and Polling:** Automatically purges unused cache entries after configurable inactive durations and handles exponential-backoff retries during network failures.
- **Optimistic UI Updates:** Updates local UI state immediately upon user submission while holding a rollback snapshot, reverting the change seamlessly if the background mutation request fails on the remote server.
