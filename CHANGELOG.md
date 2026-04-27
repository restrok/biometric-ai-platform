# Changelog - Biometric AI Platform

All notable changes to this project will be documented in this file.

## [1.3.0] - 2026-04-26
### 🚀 Features
- **Skill-Based Architecture:** Converted the `biometric-coach` subagent into a specialized **Skill**. This modular approach improves portability and provides more rigid execution protocols.
- **LLM-Native Workout Generation (SDK):** Integrated significant enhancements to the Garmin Training Toolkit SDK (v0.4.0) to improve reliability for AI agents:
    - **`RepeatGroup` Support:** Added native support for automatic workout loops (e.g., 6x800m), drastically reducing token usage and generation errors.
    - **Distance-Based Steps:** Introduced `distance_m` field for precise track session definitions.
    - **Strongly Typed Targets:** Added explicit models for `HeartRateTarget`, `PaceTarget`, and `PowerTarget` to eliminate intensity ambiguity.
- **Enhanced Biometric Sync:**
    - **HRV History Backfilling:** Updated the ETL job to correctly iterate through and backfill 30 days of HRV history from the provider.
    - **`hrvSummary` Parsing:** Implemented specific logic to capture overnight HRV averages and peak readings from modern Garmin schemas.
- **Improved Tool CLI:** Updated `manage_tools.py` to support direct JSON argument passing via the CLI, improving manual debugging and scriptability.

### 🩹 Fixes & Compliance
- **Duration Accuracy:** Resolved a critical bug where minutes were being misinterpreted as seconds (and vice-versa). All durations are now correctly converted to Garmin API standards (seconds).
- **Telemetry Robustness:** Added safety null checks to `analyze_activity_efficiency` to prevent tool crashes on activities with missing data streams.
- **Ethical & Precision Protocol:** Baked a new mandatory protocol into the coaching engine to separate facts from interpretation and avoid overconfident recommendations.
- **Calendar Maintenance:** Added a mandatory pre-flight step to clear calendar dates before updating them, preventing workout duplicates.

## [1.2.0] - 2026-04-25
### 🚀 Features
- **Semantic Routing:** Implemented an intent classifier to skip heavy telemetry pulls for informational queries, reducing latency and token costs.
- **SSE Streaming:** Added Server-Sent Events support to the OpenAI-compatible `/v1/chat/completions` endpoint for real-time response rendering.
- **Autonomous Pagination:** Updated retrieval tools to support `limit` and `offset` for efficient large-dataset navigation.
- **External Agent Support:** Created a dedicated REST router for explicit tool access and a comprehensive integration guide.
- **Rich Schema Semantics:** Added Pydantic examples and descriptions to all tools for better LLM discovery and validation.

### 🛠️ Core & Refactoring
- **Native Self-Healing Auth:** Migrated robust Garmin session refresh logic (multi-client ID rotation) into the core `garmin-training-toolkit-sdk`.
- **OpenAI Compatibility:** Refactored main API to strictly adhere to the OpenAI chat specification for seamless integration with external tools (OpenClaw, LM Studio).
- **Tool Standardisation:** Refactored all internal tools into a unified `StructuredTool` architecture with automatic Pydantic schema generation.

### 🩹 Fixes & Compliance
- **CI/CD Pipeline:** Fully resolved 500+ linting issues and fixed async test execution markers.
- **Auth Resilience:** Resolved `401 Unauthorized` errors through automatic token recovery.
- **SDK Patching:** Fixed `AttributeError` in unit tests by standardizing tool object mocking.

## [1.1.0] - 2026-04-24
### 🚀 Features
- **Wellness Sync:** Implemented 7-day lookback for heart rate metrics and sleep synchronization.
- **Manual Biometrics:** Added support for manual weight tracking and height-based BMI calculations.
- **Pre-flight Checks:** Added an execution protocol to the Biometric Coach for safer data handling.

## [1.0.0] - 2026-04-23
### 🚀 Features
- **Garmin/BigQuery Core:** Initial integration of Garmin Connect data extraction to Google BigQuery Data Lake.
- **Autonomous Coach:** First release of the LangGraph-based Running Coach with Vector RAG support.
- **Telemetry Sync:** Incremental sync of activity metrics and minute-by-minute telemetry.

---
*Generated based on main branch history.*
