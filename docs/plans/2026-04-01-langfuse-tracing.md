# Langfuse Tracing Implementation Plan

**Goal:** Add optional Langfuse observability support to DeerFlow while preserving existing LangSmith tracing and allowing both providers to be enabled at the same time.

**Architecture:** Extend tracing configuration from a single LangSmith-only shape to a multi-provider config, add a tracing callback factory that builds zero, one, or two callbacks based on environment variables, and update model creation to attach those callbacks. If a provider is explicitly enabled but misconfigured or fails to initialize, tracing initialization during model creation should fail with a clear error naming that provider.

**Tech Stack:** Python 3.12, Pydantic, LangChain callbacks, LangSmith, Langfuse, pytest

---

### Task 1: Add failing tracing config tests

**Files:**
- Modify: `backend/tests/test_tracing_config.py`

**Step 1: Write the failing tests**

Add tests covering:
- Langfuse-only config parsing
- dual-provider parsing
- explicit enable with missing required Langfuse fields
- provider enable detection without relying on LangSmith-only helpers

**Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_tracing_config.py -q`
Expected: FAIL because tracing config only supports LangSmith today.

**Step 3: Write minimal implementation**

Update tracing config code to represent multiple providers and expose helper functions needed by the tests.

**Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_tracing_config.py -q`
Expected: PASS

### Task 2: Add failing callback factory and model attachment tests

**Files:**
- Modify: `backend/tests/test_model_factory.py`
- Create: `backend/tests/test_tracing_factory.py`

**Step 1: Write the failing tests**

Add tests covering:
- LangSmith callback creation
- Langfuse callback creation
- dual callback creation
- startup failure when an explicitly enabled provider cannot initialize
- model factory appends all tracing callbacks to model callbacks

**Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_model_factory.py tests/test_tracing_factory.py -q`
Expected: FAIL because there is no provider factory and model creation only attaches LangSmith.

**Step 3: Write minimal implementation**

Create tracing callback factory module and update model factory to use it.

**Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_model_factory.py tests/test_tracing_factory.py -q`
Expected: PASS

### Task 3: Wire dependency and docs

**Files:**
- Modify: `backend/packages/harness/pyproject.toml`
- Modify: `README.md`
- Modify: `backend/README.md`

**Step 1: Update dependency**

Add `langfuse` to the harness dependencies.

**Step 2: Update docs**

Document:
- Langfuse environment variables
- dual-provider behavior
- failure behavior for explicitly enabled providers

**Step 3: Run targeted verification**

Run: `cd backend && uv run pytest tests/test_tracing_config.py tests/test_model_factory.py tests/test_tracing_factory.py -q`
Expected: PASS

### Task 4: Run broader regression checks

**Files:**
- No code changes required

**Step 1: Run relevant suite**

Run: `cd backend && uv run pytest tests/test_tracing_config.py tests/test_model_factory.py tests/test_tracing_factory.py -q`

**Step 2: Run lint if needed**

Run: `cd backend && uv run ruff check packages/harness/deerflow/config/tracing_config.py packages/harness/deerflow/models/factory.py packages/harness/deerflow/tracing`

**Step 3: Review diff**

Run: `git diff -- backend/packages/harness backend/tests README.md backend/README.md`
