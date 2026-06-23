# Changelog

All notable changes to this project will be documented in this file.

## [0.5.0] - 2026-06-23
### 🚀 Features
- **Local LLM Support (LM Studio):** Added support for running the multi-agent system on local LLM endpoints using LM Studio (`LLM_PROVIDER=lmstudio`) or OpenAI-compatible proxies. Implemented request kwarg sanitization to strip Google-specific parameters (`automatic_function_calling`).
- **Refactored Physiological Calculations:** Centralized calculations and thresholds in `src/utils/physiology.py`. Refactored `calculate_ac_ratio` to calculate the Acute:Chronic Workload Ratio (ACWR) accurately by reindexing data up to today (avoiding skew from rest days). Added `UserCalibrationProfile` Pydantic model to load personal calibration thresholds dynamically.
- **WORK Segment Telemetry Filtering:** Refactored `analyze_activity_efficiency` to filter activity telemetry for active "WORK" segments, replacing hardcoded limits with dynamic session-average metrics.
- **Enhanced Semantic Memory Extractor:** Added strict exclusion filters to prevent the memory extraction agent from saving coaching scripts, system instructions, or calendar commands.
- **Synchronous ETL Flag:** Added `background` (boolean) parameter to `sync_biometric_data` to permit synchronous runs, resolving race conditions in test environments and short-lived CLI tools.
- **Coaching Adaptive Apparel & Thermal Compensation:** Added project-level rules in `.agents/AGENTS.md` for athlete running clothing preferences (shorts in cold weather) with 4 custom physiological warm-up and temperature protection strategies.

### 🩹 Fixes & Refactoring
- **GCP Token Metadata / Local Model Pricing:** Resolved bugs in `finops.py` during local model token extraction.
- **File Handle Leak Cleanups:** Fixed open file handle leaks in `provider_factory.py` when loading and caching user-specific Garmin tokens.
- **Static Type Safety:** Added type annotations and resolved 5 critical `mypy` static type checking violations across scripts and tool definitions.
- **Codebase Re-formatting:** Standardized codebase styling using `ruff format` and sorted imports via `ruff check --fix`.

## [0.4.1] - 2026-06-01
### Changed
- **Model Rollback:** Reverted default model to `gemma-4-31b-it` due to free-tier rate limits on Gemini 3.1 Flash Lite.
- **Configurable Models:** Implemented `CORE_MODEL_NAME` environment variable to allow dynamic model switching without code changes.

## [0.4.0] - 2026-05-25
### 🚀 Features
- **Model Migration:** Successfully migrated to `gemini-3.1-flash-lite` as the default core model for all agent nodes.
- **Model Discovery Tool:** Added `list_available_models` diagnostic tool and script (`api/scripts/list_models.py`) to prevent "Model Not Found" errors.
- **Fatigue Correlation Analysis:** Manual BigQuery exploration scripts implemented to identify "Breaking Points" (Aerobic Decoupling > 10%).
- **Architectural Resilience:** Added Section 13 to `architecture-plan.md` documenting mitigations for dual-write consistency and context window bloat.

### 🩹 Fixes
- **Immune Radar:** Fixed `NoneType` error in Z-score calculations when telemetry data was missing.
- **Profile Manager:** Fixed `NameError` preventing calibration markers from being saved to Firestore.
- **Syntax Error:** Fixed graph initialization error caused by misplaced constant during refactoring.

## [0.3.1] - 2026-05-18
### 🚀 Features
- **Health Status Tooling:** Added `log_health_status` tool for the AI Coach to record discomfort, fatigue, and physical "niggles."
- **Smart Recovery Protocol:** The coach now prioritizes reported health status before prescribing high-intensity workouts.
- **Multi-Year Analysis:** Capability to perform year-over-year analysis comparing efficiency metrics between 2025 and 2026.
- **Security Integration:** Integrated with **GCP Secret Manager** for secure storage of Garmin tokens and AI Studio API Keys.
- **Infrastructure as Code:** Terraform modules for automated provisioning of Secret Manager resources.

### 🩹 Fixes & Compliance
- **Retriever Tooling:** Optimized BigQuery search engine to handle dates stored as INT64 (nanoseconds) with support for dynamic filtering.
- **Biometric Skill:** Updated execution protocol to include mandatory `latest_health_status` verification in every session.
- **Documentation:** Complete update of `roadmap.md` and `architecture-plan.md` reflecting health tracking maturity.
- **Data Integrity:** Fixed type discrepancy (FLOAT64 vs STRING) in average power (`avg_power`) synchronization during manual imports.
- **Schema Fix:** Resolved schema error in `recent_activities` table preventing upsert of swimming/pool fields in running activities.
