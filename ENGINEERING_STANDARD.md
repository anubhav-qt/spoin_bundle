# The Engineering Standard & Project Blueprint

> **Reference Origin:** Extracted and codified from the architecture, tooling, and discipline of `spoin_bundle`.  
> **Purpose:** The definitive blueprint for building robust, maintainable, high-performance software projects across all domains and tech stacks.

---

## 1. Core Engineering Axioms

Every architectural decision and line of code in a project must adhere to these foundational principles:

### I. The Enforcement Axiom
> **"A hard architectural rule gets enforced twice, never documented once."**

- Rules written solely in markdown rot silently; a failing CI check does not.
- Layer 1 (Static Analysis / Lint): Use linter rules (e.g., `ruff` `banned-api` / ESLint boundary rules) to stop illegal cross-package imports before code runs.
- Layer 2 (AST-Level Architecture Tests): Write automated test suites (e.g., `tests/test_architecture.py`) using AST parsing to verify architectural boundaries, forbidden dependencies, and interface contracts in CI.

### II. The Trust Model for AI / External Services
> **"The generator is trusted for taste, never for constraints."**

- Anything that must be **factually true or bounded** (character limits, budget caps, schema compliance, difficulty ratings, reuse counts) must be calculated, validated, or enforced **outside** the external service/model.
- Anything that merely needs to be **good or creative** (prose, humor, synthesis, styling) is delegated to the model/service.
- Never write prompt instructions like *"Please keep response under 100 characters"* when a deterministic server-side validator or truncate/drop rule is required.

### III. Hard Wall Between Read Path and Write Path (CQRS)
> **"The user read path never waits on slow, unbounded, or external processes."**

- User-facing read requests (e.g., feed serving, search, dashboards) must execute in sub-100ms against pre-computed, indexed relational stores.
- Heavy computations, third-party calls, and AI generations belong exclusively to the **asynchronous write path** (background workers, batch pipelines, event ingest).
- Personalization and dynamic presentation are executed as **ranking and filtering over pre-computed shared corpora**, not per-user just-in-time generation.

### IV. Single Source of Truth & Zero-Business-Logic Clients
> **"If the web client can do something the mobile client can't, that is a bug, not a shortcut."**

- The API is the single source of truth for all business logic, authorization, data validation, and state machines.
- Client applications (Web, Mobile, CLI) are strictly responsible for **rendering and local UI state**.
- Clients never perform ad-hoc HTTP calls across components; all network interactions flow through a unified, typed API client layer (e.g., `lib/api.ts`).
- Types between backend and frontend are **generated from the live OpenAPI schema** (`packages/api-types`) and checked for drift in CI, never manually synchronized.

### V. "Why, Not What" Documentation Discipline
- Comments must explain **why** a non-obvious decision was made, what constraint forces it, or cite an ADR.
- If a comment merely restates what the code does, delete the comment.
- Domain models and schema fields must carry docstrings/comments with provenance and ADR references (e.g., `#:` Sphinx comments in SQLAlchemy models).
- Module docstrings link directly to the relevant architectural document in `docs/architecture/` rather than re-explaining architecture inline.

### VI. Observable Failure Semantics
> **"A failed system call and a rejected domain outcome are never the same number."**

- Distinguish clearly between **transient infrastructure failures** (quota exhaustion, timeouts, network blips, 429s, malformed responses) and **domain rejections** (failed quality gates, invalid business rules, duplicate records).

### VII. Testing Philosophy: Real State over Mocked State
- When testing database logic (foreign keys, cascading deletes, unique constraints, transactional integrity, date-scoped ledgers), test against a **real PostgreSQL instance**, not in-memory or mocked DBs.
- Mock only non-deterministic, rate-limited, or third-party external services (e.g., LLM APIs, payment gateways).

### VIII. Prompts & System Instructions as Modular Code Assets
> **"Prompts and system instructions are values assigned to variables, not inline strings."**

- In AI-agent and LLM-driven systems, system instructions, prompt templates, and few-shot examples must **never be inlined directly** into business logic, pipeline steps, or service classes.
- Store each prompt or system instruction in its own dedicated file inside an isolated prompts directory (e.g., `src/<project>/generation/prompts/<feature>.py` or `prompts/`).
- Pipeline and application code only imports the **named variable/constant** (e.g., `from spoin.generation.prompts.topics import TOPIC_GENERATION_PROMPT`).
- This decouples prompt iteration, versioning, review, and token budgeting from execution flow and control graphs.

---

## 2. Universal Repository Anatomy

A reference monorepo layout isolating concerns cleanly:

```
├── .claude/ or .agents/      # Agent-specific configs, rules, and skills
├── apps/
│   ├── api/                  # Core API service (FastAPI / Express / Go / etc.)
│   │   ├── src/<project>/
│   │   │   ├── core/         # Config, DB sessions, telemetry, security
│   │   │   ├── domain/       # Database models, domain enums, pure entities
│   │   │   ├── api/          # HTTP routers, wire schemas (Pydantic), auth
│   │   │   ├── <read_path>/  # Deterministic read engines (feed, search, etc.)
│   │   │   ├── <write_path>/ # Async generators, ingest pipelines, transformers
│   │   │   └── generation/
│   │   │       └── prompts/  # Dedicated folder: 1 file per prompt / system instruction
│   │   │           ├── __init__.py
│   │   │           ├── topics.py      # Exports TOPIC_SYSTEM_PROMPT, etc.
│   │   │           └── quality.py     # Exports QUALITY_GATE_PROMPT, etc.
│   │   ├── tests/
│   │   │   ├── test_architecture.py  # AST boundary & architectural unit tests
│   │   │   └── ...                   # Integration and unit test suites
│   │   ├── alembic/ / prisma/        # Version-controlled DB migrations
│   │   ├── Dockerfile
│   │   └── pyproject.toml / package.json
│   ├── worker/               # Background workers (shares the backend core/domain)
│   │   └── ...               # Worker entrypoints claiming queued jobs
│   └── web/                  # Frontend UI (Next.js / Vite / React Native)
│       ├── app/ / src/
│       ├── lib/api.ts        # The ONLY file allowed to communicate with the API
│       └── ...
├── packages/
│   └── api-types/            # Auto-generated TypeScript types from backend OpenAPI
├── docs/                     # Durable knowledge hub
│   ├── adr/                  # Architectural Decision Records (0001-..., TEMPLATE.md)
│   ├── architecture/         # High-level architecture, content models, pipelines
│   ├── design/               # Living mockups and UI design specifications
│   └── tasks/                # Granular task specs and tracker (README.md)
├── CLAUDE.md / AGENTS.md     # Fast context bootstrapping for AI agents & contributors
├── docker-compose.yml        # Zero-friction local development stack
├── Makefile / make.ps1       # Standardized task runner targets
└── README.md                 # Project vision, mental model, and DX guide
```

---

## 3. Architectural Enforcement in Code

### 1. Linter Boundary Bans
Configure your linter to prevent leaky abstractions. For example, in Python using `pyproject.toml` (Ruff):

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"langchain".msg = "Only src/<project>/generation/langchain_impl.py may import langchain (ADR-0002)."
"langgraph".msg = "Only src/<project>/generation/pipeline.py may import langgraph (ADR-0024)."

[tool.ruff.lint.per-file-ignores]
"src/<project>/generation/langchain_impl.py" = ["TID251"]
"src/<project>/generation/pipeline.py" = ["TID251"]
```

### 2. AST Architectural Unit Tests (`test_architecture.py`)
Run automated architectural boundary verification as part of every test run:

```python
import ast
import pathlib
import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "my_project"
READ_PATH = [SRC / "feed", SRC / "api" / "routers" / "feed.py"]
FORBIDDEN_READ_MARKERS = ("langchain", "openai", "google.genai", "my_project.generation")

def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found

def test_no_heavy_sdk_in_read_path():
    for root in READ_PATH:
        for py_file in root.rglob("*.py") if root.is_dir() else [root]:
            offenders = {imp for imp in _imports(py_file) if any(imp.startswith(m) for m in FORBIDDEN_READ_MARKERS)}
            assert not offenders, f"{py_file} reaches forbidden module {offenders}"
```

### 3. Batched-by-Design Interfaces
Never create single-item entry points for operations that incur network overhead, rate limits, or batch economics:

```python
# GOOD: Forces batching at the architectural boundary
class ContentGenerator(ABC):
    @abstractmethod
    async def generate_items(self, prompts: list[PromptSpec]) -> list[GeneratedItem]: ...

# FORBIDDEN: Single-item wrappers that encourage unmetered loops
# async def generate_item(self, prompt: PromptSpec) -> GeneratedItem: ...
```

---

## 4. Contract-Driven Type Safety

### Backend to Frontend Schema Generation
1. API exposes OpenAPI spec (e.g. FastAPI `/openapi.json`).
2. Run codegen script (`make api-types` via `openapi-typescript`).
3. CI verifies that `packages/api-types` matches the current API schema with zero diff.
4. Frontend imports types strictly from `packages/api-types`:

```typescript
// apps/web/lib/api.ts
import type { components, paths } from "@project/api-types";

export type CardResponse = components["schemas"]["CardPublic"];

export const api = {
  feed: {
    async getNextBatch(limit: number): Promise<CardResponse[]> {
      const res = await fetch(`${API_URL}/api/v1/feed?limit=${limit}`, { credentials: "include" });
      if (!res.ok) throw new ApiError(res.status, await res.text());
      return res.json();
    }
  }
};
```

---

## 5. Decision Management & Living Documentation

### Architectural Decision Records (ADRs)
Every non-trivial technical decision must be captured in `docs/adr/NNNN-title.md` using the standard format:

- **Context & Problem Statement**: What technical, cost, or UX reality forced this decision?
- **Decision Drivers**: Key forces (cost, latency, complexity, team velocity).
- **Considered Options**: Concrete alternatives evaluated with pros & cons.
- **Decision Outcome**: The chosen path and the exact justification.
- **Consequences**: Positive, negative, and neutral trade-offs accepted.
- **Superseding Links**: If ADR-0020 supersedes ADR-0005, both documents must cross-link each other explicitly.

### Task Specs as Sources of Truth
- Every major deliverable starts as a task spec in `docs/tasks/NNNN-feature-name.md`.
- Tasks define: Goal, Non-goals, Key architectural invariants, Files to touch, Step-by-step implementation plan, and Verification checklist.
- The task index in `docs/tasks/README.md` serves as the live status board.

### Living Design Specs & Mockups
- Visual specifications are authored as **working, standalone HTML/CSS mockups** under `docs/design/mockups/`, not un-inspectable images or transient chat links.

---

## 6. Developer Experience (DX) Standards

A project is only as good as its onboarding friction. Every project must guarantee:

### The 10-Minute / 1-Day Promise
1. **Clone → Running Stack in < 10 minutes** using `docker compose up` on a clean machine with only Docker and Git.
2. **Clone → Merged Pull Request in < 1 day** without needing out-of-band explanations.

### Standardized Command Interface (`Makefile` / `make.ps1`)
Every repository provides uniform standard commands regardless of tech stack:
- `make setup` : Installs dependencies, sets up hooks, configures environment.
- `make dev`   : Starts local development environment / containers.
- `make test`  : Runs automated test suites.
- `make check` : Runs strict typechecking (`mypy --strict` / `tsc --noEmit`), linter (`ruff` / `eslint`), and architectural verification.
- `make api-types` : Re-generates client contracts from backend schemas.

### Database State Governance
- The development database must start **clean and blank by default** via migrations (`alembic upgrade head` / `prisma migrate deploy`).
- Destructive operations (`drop database`, `truncate`, resetting shared test DBs) require explicit developer confirmation.
- Fixtures and synthetic seeding are decoupled from default startup.

---

## 7. AI-Assisted Agent Bootstrap & Pair-Programming Protocols

Provide an upfront root instructions file (`CLAUDE.md` / `AGENTS.md`) for AI pair-programmers to ensure high-velocity, zero-drift assistance:

### 1. Agent Bootstrap Rules
1. **Bootstrap Reading Order**: Directs the agent to `docs/architecture/` and relevant ADRs before modifying code.
2. **Database Access Boundaries**: Stating read-only vs. mutation permissions.
3. **Generalizing Invariants**: Stating core non-negotiable rules (e.g. no business logic in UI, CQRS separation).
4. **Style and Type Discipline**: Explicit requirements on `mypy --strict`, comment discipline ("why, not what"), and banned patterns.

### 2. UI Verification Protocol: Automatic vs. Human Testing
UI and interactive features are significantly faster, higher-fidelity, and more intuitive for the human developer to test and evaluate in real-time than simulated browser scripts.

- **Choice Prompting**: Whenever a UI change or frontend feature is implemented, the AI agent must **explicitly ask the user** whether they want the AI to run automated tests or if the human developer prefers to test it manually.
- **Human Testing Checklist Requirement**: Whenever human testing is selected, the AI **must provide a clear, structured verification checklist** containing:
  1. **Starting Route / State**: Exact URL path, query params, and prerequisites.
  2. **Step-by-step Actions**: Specific user interactions (clicks, keyboard navigation, form inputs, viewport resizes).
  3. **Visual & Behavioral Expectations**: What should render, animation transitions, loading states, and theme/font styling.
  4. **Edge Cases**: Empty states, network error simulations, boundary validation.

---

## 8. New Project Initialization Checklist

When bootstrapping a new project under this standard:

- [ ] **Step 1: Monorepo Topology**: Set up `apps/api`, `apps/worker` (if async jobs exist), `apps/web`, `packages/api-types`, and `docs/`.
- [ ] **Step 2: AI Prompt Modularization**:
  - Create dedicated `prompts/` directory for any AI agent/LLM features.
  - Enforce one file per prompt/system instruction; import variables by name only.
- [ ] **Step 3: Tooling & Strictness**:
  - Configure linter with import boundary restrictions.
  - Enable strict typechecking (`mypy --strict`, `tsconfig.json` `strict: true`).
  - Add pre-commit hooks for formatting, linting, and typecheck.
- [ ] **Step 4: Architectural Tests**:
  - Create `test_architecture.py` asserting module isolation and interface patterns.
- [ ] **Step 5: Contract Sync**:
  - Set up OpenAPI generation script and CI contract drift check.
- [ ] **Step 6: Documentation Foundations**:
  - Initialize `docs/adr/`, `docs/architecture/overview.md`, and `docs/tasks/`.
  - Create root `CLAUDE.md` / `AGENTS.md` and `README.md`.
- [ ] **Step 7: Zero-Friction DX & Verification Protocol**:
  - Author `docker-compose.yml`, `.env.example`, and root `Makefile` / `make.ps1`.
  - Incorporate the Human UI Verification checklist protocol into agent workflows.
- [ ] **Step 8: CI Pipeline**:
  - Wire GitHub Actions / CI to run `make check` (lint + types + architecture tests + contract sync) on every PR.
