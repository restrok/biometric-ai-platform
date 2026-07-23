# SRE Standards, Guardrails & Observability

This document defines the Site Reliability Engineering (SRE) standards, execution safety guardrails, and observability frameworks implemented across the platform.

---

## 1. Agent Execution Safety Guardrails

### 🛡️ SRE Dry-Run Mandate (`data_scientist.py`)
To prevent unbounded cloud costs caused by autonomous LLM query generation:
1. **Dry-Run Validation:** Before executing any exploratory SQL query, the Data Scientist agent MUST invoke `execute_exploratory_query_dry_run`.
2. **Byte Scan Ceiling:** If the dry-run indicates an `estimated_bytes_processed` exceeding **500 MB**, execution is blocked automatically.
3. **Partition Enforcement:** Queries MUST apply partition filters (e.g. `WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)`).

### 🧐 Response & Action Discrepancy Gating (`graph.py`)
The `node_validator` reviews agent outputs before client delivery:
- **Action Verification:** If the response text claims an action was taken (e.g. "Scheduled", "Uploaded", "Deleted"), the node verifies that a corresponding tool call was emitted. Hallucinated text actions without tool execution are rejected.

---

## 2. Observability & FinOps Framework

### 📊 Tracing & Telemetry (`telemetry.py`)
- **OpenTelemetry & Langfuse:** Tracks multi-agent node latency, LLM prompt tokens, completion tokens, and function call chains.
- **Dual Logging System:** Outputs human-readable logs to the console and structured JSON events to `api.log` for log aggregation.

### 💰 FinOps Audit Logs (`finops.py`)
- Every LLM invocation records model name, input/output tokens, execution latency, and estimated cost in USD.
- Logs are asynchronously ingested into BigQuery (`finops_logs`) for cost monitoring per user and per feature.

---

## 3. CI/CD & Quality Control

- **Static Analysis & Linting:** `ruff check` and `ruff format` enforced across the codebase.
- **Type Checking:** `mypy` strict type checking on `src/` and `tools/`.
- **Automated Test Suite:** Pytest suite with mocked Garmin providers and LLM integration test skips for quota safety.
