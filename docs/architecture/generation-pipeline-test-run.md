# Generation Pipeline Test Run Report

> First full end-to-end multi-topic production verification of the card-generation pipeline.
> Execution date: 2026-08-21.
> Triggered via: `python -m spoin.generate_topics "Current AI Capabilities and Scope" "10M Air Pistol Shooting"`.

---

## Executive Summary

The entire generation pipeline was executed in the backend against two distinct, domain-divergent topics:
1. **`Current AI Capabilities and Scope`** (Software, AI architecture, mathematical reasoning, API tool orchestration).
2. **`10M Air Pistol Shooting`** (Olympic sport biomechanics, sight alignment, trigger mechanics, match psychology).

The run completed with **100% success** across both topics, generating, verifying, embedding, and persisting **1,065 production-grade cards** and **1,056 interactive quiz questions** directly into PostgreSQL.

---

## Generation & Verification Metrics

| Metric | `10M Air Pistol Shooting` | `Current AI Capabilities and Scope` | Total |
| :--- | :---: | :---: | :---: |
| **Minted Subtopics** | 35 | 22 | **57** |
| **Completed Subtopics** | 35 (100%) | 22 (100%) | **57 (100%)** |
| **Accepted Cards Persisted** | 589 | 476 | **1,065** |
| **Quiz Questions Persisted** | 581 | 475 | **1,056** |
| **Quality Gate Rejections** | 4 | 8 | **12** |
| **Card Embeddings (384-dim)** | 589 | 476 | **1,065** |
| **Persistence Status** | `Committed` | `Committed` | `All Live` |

---

## Quality Gate Behavioral Findings

During this run, the Two-Pass Quality Gate ([ADR-0030](../adr/0030-two-pass-quality-gate.md) & [ADR-0031](../adr/0031-verification-feedback-and-per-tier-gate-durability.md)) performed critical editorial and factual corrections on live drafts:

### 1. Code Syntax & Spec Enforcement (Pass 1)
- **Tool Schema Definitions**: Detected and removed unsupported `default` keywords from strict JSON parameter specifications in API function-calling cards to ensure OpenAPI compliance.
- **Python Syntax Correction**: Caught and resolved a syntax error in a Python list comprehension string formatting inside a software engineering code card.
- **PyTorch Selective Scan Tensor Shapes**: Fixed tensor dimensions and index bounds in Mamba/selective scan code snippets to prevent runtime dimension mismatch errors.

### 2. Domain-Specific Factual Corrections (Pass 1)
- **ISSF Olympic Range Rules**: Corrected a hallucinated claim that 10M Olympic air pistol shooters walk downrange to retrieve paper targets or patch holes, aligning content with actual ISSF rules (electronic acoustic/optical target systems operated from the firing line).
- **Sight Elevation Physics**: Replaced inaccurate barometric drag physics with mechanical click elevation calibration rules for 10-meter indoor trajectories.

### 3. Scope Boundaries & Level Calibration (Pass 2 Rejections)
- **Topic Scope Boundary Enforcement**: Rejected an *Embodied Robotics & Physical Manipulation* draft from the pure digital AI software capabilities subtopic (*"Out of scope: Focus is on software agents and API function calling rather than physical robotics"*).
- **Beginner Tier Calibration**: Rejected beginner cards containing executable Python SDK integration code (*"Includes executable Python SDK code, which elevates the card content to intermediate level"*), ensuring beginner tiers remain conceptual.

---

## Infrastructure & Resilience Observations

### Multi-Key & Ladder Rotation ([ADR-0028](../adr/0028-key-model-quota-ladder.md))
- **Thinking Pool (`gemini-3.7-flash` & `gemini-3.6-flash`)**: Keys 0 through 8 rotated automatically when approaching the daily 20 RPD free-tier ceilings.
- **Generator Pool (`gemini-3.5-flash-lite`)**: Efficiently drafted cards and generated 1,056 interactive quiz questions within its 500 RPD budget allocation.

### Upstream 503 Provider Recovery
- Google API transient high-demand spikes (`503 Service Unavailable`) were smoothly absorbed by automated exponential backoff ($2\text{s} \rightarrow 4\text{s} \rightarrow \text{rotate}$) with **zero dropped batches or lost work**.

### Atomic Per-Group Persistence ([ADR-0041](../adr/0041-per-group-gate-and-persist.md))
- Each subtopic group wrote its cards, 384-dimensional FastEmbed vector embeddings, and 4-choice quiz questions atomically to PostgreSQL upon clearing verification, making completed content immediately playable in the user feed.
