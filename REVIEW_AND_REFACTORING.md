# Review & Refactoring Recommendations

## Overview
Three files reviewed: `agent-config.json`, `agent-config.yaml`, and `agent_runner.py`. All are functional but have opportunities for robustness, maintainability, and safety improvements.

---

## 1. `agent-config.json` & `agent-config.yaml`

### Issues & Recommendations

#### A) **Duplicate Configuration (JSON & YAML)**
- **Issue**: Both JSON and YAML have identical content — redundant and hard to maintain.
- **Recommendation**: Choose one format. YAML is more readable; JSON is stricter and faster to parse. Suggest keeping **YAML only** and loading it in the runner.
- **Impact**: Reduces confusion, single source of truth.

#### B) **Missing Validation & Defaults**
- **Issue**: No fallback defaults if env vars are missing; no validation on config structure.
- **Recommendation**: 
  - Add a config validation schema (e.g., using `pydantic` or `jsonschema`).
  - Provide sensible defaults for optional fields (e.g., temperature, max_tokens).
  - Log warnings if required env vars are not set.

#### C) **Hardcoded Model Names & Endpoints**
- **Issue**: Model names (`claude-3.5`, `gpt-4-turbo`) are hardcoded in multiple places (config, runner).
- **Recommendation**: 
  - Make model names configurable, avoid repetition.
  - Store as constants or load from config.

#### D) **Cost Limit Guardrail Under-specified**
- **Issue**: `daily_usd_limit` and `on_exceed: switch_to_local` — but no tracking mechanism or reset logic defined.
- **Recommendation**:
  - Add cost tracking (log calls + costs).
  - Add timestamp for daily reset (UTC midnight, or explicit format).
  - Consider per-model spending limits.

#### E) **Timeout Values**
- **Issue**: Timeouts (20s, 25s, 60s) are reasonable but not justified or documented.
- **Recommendation**:
  - Add comments explaining why local gets 3x timeout.
  - Consider making these configurable per task.

#### F) **API Version Pinning**
- **Issue**: `api_version: "2025-01-01-preview"` — future date suggests this is a placeholder or aspirational.
- **Recommendation**:
  - Use a stable, released version (e.g., `2024-10-01` or `2024-08-01`).
  - Document why preview is needed if intentional.

---

## 2. `agent_runner.py`

### Issues & Recommendations

#### A) **Missing Dependencies**
- **Issue**: Imports `AzureOpenAI`, `requests` — but `requirements.txt` not guaranteed to have them.
- **Recommendation**:
  - Add to `requirements.txt`: `openai>=1.0.0`, `requests>=2.31.0`, `pyyaml>=6.0`.
  - Add import guards or early validation.

#### B) **Error Handling Too Lenient**
- **Issue**: Broad `except Exception` clauses swallow errors; doesn't distinguish retryable vs. fatal.
- **Recommendation**:
  - Catch specific exceptions (`requests.Timeout`, `AzureOpenAI.APIError`, etc.).
  - Log full stack traces at DEBUG level.
  - Return structured error response with error code and message.

#### C) **No Config Loading**
- **Issue**: Config file (`agent-config.yaml`) is created but never loaded in runner.
- **Recommendation**:
  - Add `load_config(path)` function to parse YAML/JSON.
  - Load routing policy, model names, timeouts from config (not hardcoded).

#### D) **Hardcoded System Prompt**
- **Issue**: "You are Inventory Analyst - Supply Chain Operations." is in the code.
- **Recommendation**:
  - Load from config or dedicated `agent.md` file (already referenced as `instructions_path`).
  - Support dynamic system prompt injection.

#### E) **No Logging or Observability**
- **Issue**: Only `print()` for errors — no structured logging, no cost tracking.
- **Recommendation**:
  - Use `logging` module with structured JSON output.
  - Log each API call (model, latency, cost estimate, success/failure).
  - Include request IDs for tracing.

#### F) **Global Client Initialization**
- **Issue**: `azure_client` is initialized at module load time — fails silently if env vars missing.
- **Recommendation**:
  - Wrap in a factory function or class.
  - Add explicit validation on first use.
  - Support hot-reload of credentials.

#### G) **Streaming Not Handled**
- **Issue**: Ollama response is streamed (line-by-line JSON), but no streaming for Azure/Claude.
- **Recommendation**:
  - Normalize all responses (stream or buffer).
  - Add optional streaming support for long-running tasks.

#### H) **No JSON Schema Validation**
- **Issue**: Config defines `output_schema` for `variance_assignment` task, but runner never validates output.
- **Recommendation**:
  - Add post-processing validation using `jsonschema` or `pydantic`.
  - Return validation errors to caller.

#### I) **Hard-coded Timeouts & Cascading Logic**
- **Issue**: Timeouts are passed to `requests.post()` but routing policy is implicit (try Azure → Claude → local).
- **Recommendation**:
  - Make routing policy configurable (cascade, parallel, round-robin).
  - Use config timeouts, not hardcoded.
  - Add retry backoff from config.

#### J) **No Cost Estimate**
- **Issue**: Despite guardrails in config, no cost calculation in runner.
- **Recommendation**:
  - Add token counting before sending (Azure, Claude SDKs support this).
  - Calculate estimated cost per call.
  - Track against daily limit; fail or switch if exceeded.

#### K) **Anthropic API Not Imported**
- **Issue**: Using raw `requests.post()` for Claude; should use official SDK for consistency.
- **Recommendation**:
  - Add `anthropic>=0.7.0` to requirements.
  - Use `Anthropic` client (similar to `AzureOpenAI`).

---

## 3. Cross-Cutting Concerns

#### A) **No Task-Specific Routing**
- **Issue**: Config defines 3 tasks (variance_assignment, diagnostics_why_processor, offline_batch), but runner has no `task` parameter.
- **Recommendation**:
  - Add `run_agent(prompt, task="variance_assignment", ...)` parameter.
  - Load task-specific settings (model, output_schema, max_tokens) from config.

#### B) **No Async Support**
- **Issue**: All calls are synchronous; no concurrency for parallel fallback or batch processing.
- **Recommendation**:
  - Add `async def run_agent_async()` variant.
  - Use `httpx.AsyncClient` or `aiohttp`.
  - Support concurrent calls to multiple models for comparison.

#### C) **Secrets Not Rotated or Validated**
- **Issue**: API keys are read once at startup; no refresh or validation.
- **Recommendation**:
  - Add key validation on startup.
  - Support env var refresh without restart (e.g., via SIGHUP or endpoint).
  - Log key validity checks (without exposing keys).

#### D) **No Testing or Mocking**
- **Issue**: No unit tests; external dependencies (Azure, Claude, Ollama) make testing hard.
- **Recommendation**:
  - Add `mock` fixtures for each LLM provider.
  - Test routing logic, error handling, config loading separately.
  - Example: `pytest` with `responses` or `unittest.mock`.

#### E) **Documentation Gaps**
- **Issue**: No docstrings, no README, no example env file.
- **Recommendation**:
  - Add `.env.example` with all required vars and defaults.
  - Add docstrings to all functions.
  - Add usage examples (single prompt, batch, task-specific).

---

## Summary of Priority Fixes

### High Priority (implement first)
1. Load config file (YAML) in runner instead of hardcoding.
2. Replace broad `except Exception` with specific error handling.
3. Add `Anthropic` SDK instead of raw HTTP.
4. Add structured logging (`logging` module).
5. Add task parameter and task-specific config loading.

### Medium Priority
6. Add config validation (pydantic or jsonschema).
7. Add cost tracking and daily limit enforcement.
8. Remove duplicate JSON/YAML (keep YAML only).
9. Add docstrings and type hints.
10. Add `.env.example` and README.

### Nice-to-Have
11. Add async/await support.
12. Add streaming support across all models.
13. Add unit tests with mocking.
14. Add credential refresh mechanism.

---

## Files to Keep/Store

- ✓ `agent-config.yaml` (refactored)
- ✓ `agent_runner.py` (refactored)
- ✗ `agent-config.json` (consolidate into YAML)
- ✓ `.env.example` (new)
- ✓ `README.md` (new)

