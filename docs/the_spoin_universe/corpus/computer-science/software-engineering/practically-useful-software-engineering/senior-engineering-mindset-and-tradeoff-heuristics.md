---
title: Senior Engineering Mindset, Trade-Off Heuristics, and Architectural Decision Making
kind: topic_source
category: computer science
sub_category: software engineering
scope: topic
source: "A Philosophy of Software Design (Ousterhout), Systemantics (Gall), Architecture Decision Records (Nygard)"
source_date: 2024
topic_tags:
  - software-engineering
  - software-architecture
  - engineering-mindset
  - decision-making
  - cognitive-load
  - architecture-decision-records
---
## Gall's Law and the Evolutionary Primacy of Simple Working Systems

A foundational axiom of pragmatic software engineering is Gall's Law: a complex system that works is invariably found to have evolved from a simple system that worked. Conversely, a complex system designed from scratch never works and cannot be patched to make it work. You must start over with a simple working system.

In software architecture, this principle directly governs the division between monolithic and distributed topologies. Junior and mid-level engineers frequently attempt to construct distributed multi-service architectures on day one, introducing network serialization overhead, distributed transactions, partial failure cascades, and asynchronous data synchronization before the core domain boundaries have stabilized.

Senior engineers counter this impulse by building modular monoliths with strict internal package boundaries and shared in-process memory. Because in-process function calls cannot fail due to network partitions or dropped packets, the business logic and domain model can be rapidly refined without distributed systems overhead. When high-throughput boundaries or distinct organizational scaling needs genuinely demand physical isolation, extraction into an independent service succeeds because the data contracts and domain interfaces were already proven in a functioning monolith.

## Chesterton's Fence and the Forensic Audit of Legacy Constraints

Chesterton's Fence is an epistemological rule stating that before you remove an existing policy, structure, or piece of code, you must first understand the reason it was originally created. If you do not understand why a fence was erected, you cannot safely determine whether tearing it down will release a dangerous consequence.

In production codebases, legacy implementations often appear clumsy, verbose, or redundant to incoming engineers. An unfamiliar developer encountering a defensive null-check, a synchronized lock block, or an unusual retry delay instinctively brands it as technical debt and deletes it in the name of clean code.

Experienced developers treat legacy code as a forensic record of past production failures. That seemingly unneeded retry loop was often instituted to handle transient network timeouts from a downstream banking provider during nighttime maintenance windows; that odd database lock was implemented to prevent a race condition during concurrent webhook processing. A senior engineer audits git blame history, reads pull request discussions, searches incident postmortems, and consults domain owners before altering or pruning legacy safeguards. If the underlying historical constraint has genuinely expired—such as a legacy upstream API being retired—the code is removed cleanly with the reason documented in the commit.

## Deep Versus Shallow Modules and Cognitive Load Minimization

In software design, John Ousterhout defines the quality of an abstraction by the ratio of its interface complexity to the depth of functionality it conceals. A "deep module" provides extensive, powerful capabilities through a small, simple interface. The Unix file system abstraction is a classic deep module: four primary system calls—`open`, `read`, `write`, and `close`—present a straightforward interface while encapsulating immense internal complexity, including page caches, block allocation, journaling, elevator disk scheduling, and hardware drivers.

Conversely, a "shallow module" presents an interface that is complex relative to the minimal logic it implements. Shallow modules frequently emerge when developers create micro-classes, single-method interface delegations, or pass-through helper wrappers in a misguided quest for granular modularity. Instead of reducing cognitive load, shallow modules amplify it: an engineer attempting to understand system behavior must navigate twenty distinct files and indirection layers to locate three lines of actual business execution.

Senior engineers design software to minimize the total cognitive load required to modify a system safely. They bundle closely related state, validation, and side-effect logic into deep modules with cohesive, unmistakable entry points, isolating implementation details behind stable boundaries so that engineers reading call sites never need to retain internal mechanics in working memory.

## The Rule of Three and Premature Abstraction Penalties

A pervasive trap in software construction is premature abstraction: attempting to make code generic and extensible before the true problem space is understood. Driven by a dogmatic misapplication of the "Don't Repeat Yourself" (DRY) principle, developers merge two superficially similar routines into a shared generic function with multiple boolean flag parameters, dynamic branching conditions, and complex generics.

This creates the "wrong abstraction," which is dramatically more expensive to maintain than duplicated code. As requirements for the two routines diverge over time, the shared function accumulates conditional branches (`if (isTypeA && !skipValidation)`), transforming into a brittle tangle where modifications intended for one feature break unrelated workflows across the application.

Pragmatic engineers apply Sandi Metz's "Rule of Three": duplication is far cheaper than the wrong abstraction. Rather than abstracting upon the second instance of a pattern, experienced engineers tolerate duplication until a pattern manifests clearly across at least three distinct, independent use cases. Only when three implementations share identical structural behavior and reasons for change is an abstraction extracted. If the abstraction begins demanding conditional execution parameters, it is promptly inlined back into the calling sites.

## Architecture Decision Records and Structured RFC Governance

Senior software engineering recognizes that architectural drift and institutional amnesia are primary drivers of technical debt. When critical design decisions are made verbally in meetings or buried in chat channels, the contextual rationale is lost within months, leaving future engineers unable to distinguish intentional architectural compromises from accidental mistakes.

To eliminate this ambiguity, teams implement Architecture Decision Records (ADRs) and Request for Comments (RFC) frameworks:
- The RFC Process: Before implementing significant infrastructural or domain shifts, an engineer drafts an RFC detailing the problem statement, explicit non-goals, architectural alternatives considered with pros and cons, security and operational impacts, and an actionable migration plan. The RFC forces rigorous peer review and surface hidden assumptions before a single line of production code is written.
- Architecture Decision Records: Once agreed upon, immutable ADR markdown files are checked directly into the code repository alongside the source files (typically in `docs/adr/`). Each record captures four concrete fields: Status, Context (the technical problem and business forces), Decision (what was chosen), and Consequences (both positive benefits and negative operational tradeoffs). ADRs transform tribal lore into verifiable, version-controlled repository history.
