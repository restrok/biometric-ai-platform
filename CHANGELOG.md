# Changelog - Biometric AI Platform

All notable changes to this project will be documented in this file.

## [1.4.1] - 2026-05-13
### Fixed
- **Critical Hydration Safety:** Implemented a safety cap of 1.5L for proactive hydration recommendations and refined the messaging to be advisory rather than mandatory, mitigating hyponatremia risks.
- **Cardiovascular Drift Messaging:** Renamed "Silent Dehydration" to "Cardiovascular Drift" in proactive alerts for better clinical accuracy and reduced alarmism.

## [0.2.0] - 2026-05-05
### Added
- **Universal Goals Feature**: New `user_goals` table in BigQuery and `manage_goals` tool to persist long-term user objectives.
- **Robust Multi-User Injection**: Automated `user_id` injection in the LangGraph `tool_node` to ensure data isolation without LLM intervention.
- **Telemetry Optimization**: Implemented Dynamic Effort Segmentation in BigQuery to reduce LLM token usage by 60-80% while preserving precision.
- **Multi-User Identity Enforcement**: Updated all analysis, health, and uploader tools to strictly filter and operate by `user_id`.

### Fixed
- **API Stability**: Switched Intent Classifier to Gemma 31B and added fallback to 'full' intent to resolve 500 errors on the 26B model.
- **Data Integrity**: Completed backfill of `user_id` for all historical BigQuery data to prevent cross-user data leakage.
- **Logging**: Silenced recurring `enable_auto_call` warnings by refactoring LLM configuration to match the updated LangChain interface.

## [Unreleased] - 2026-05-04

### Added
- **Injury & Health Tracking System:**
  - Nueva tabla nativa en BigQuery `user_health_status` para persistencia de datos subjetivos.
  - Herramienta `log_health_status` para que el Coach AI registre malestar, fatiga y "niggles" físicos.
  - Protocolo de recuperación inteligente: El coach ahora prioriza el estado de salud reportado antes de prescribir entrenamientos de alta intensidad.
- **Historical Analysis Engine:**
  - Soporte para rangos de fechas (`start_date`, `end_date`) en la herramienta `retrieve_biometric_data`.
  - Capacidad de realizar análisis interanuales comparando métricas de eficiencia entre 2025 y 2026.
- **Secret Management Infrastructure:**
  - Integración con **GCP Secret Manager** para el almacenamiento seguro de tokens de Garmin y API Keys de AI Studio.
  - Soporte multi-usuario inicial mediante el prefijo de secretos por ID de usuario.
- **Cloud Readiness:**
  - Módulos de Terraform para el aprovisionamiento automatizado de Secret Manager.
  - Soporte para carga de tokens desde Secret Manager en entornos sin archivos locales.

### Changed
- **Retriever Tooling:** Optimización del motor de búsqueda de BigQuery para manejar fechas almacenadas como INT64 (nanosegundos) con soporte para filtrado dinámico.
- **Biometric Skill:** Actualizado el protocolo de ejecución para incluir la verificación obligatoria del `latest_health_status` en cada sesión.
- **Documentation:** Actualización completa del `roadmap.md` y `architecture-plan.md` reflejando la madurez del sistema de seguimiento de salud.

### Fixed
- Corregida la discrepancia de tipos (FLOAT64 vs STRING) en la sincronización de potencia media (`avg_power`) durante importaciones manuales.
- Solucionado el error de esquema en la tabla `recent_activities` que impedía el upsert de campos de natación/piscina en actividades de carrera.

## [1.4.0] - 2026-05-02
### 🚀 Features
- **Self-Healing Authentication (SDK v0.6.0):** Migrated to the stable PyPI release of the `garmin-training-toolkit-sdk`. This introduces native handling for session refreshes and client ID rotation, eliminating "403 Forbidden" errors.
- **Robust Calendar Synchronization:** Implemented a new granular calendar management system that correctly handles month boundaries and standardized unscheduling, preventing workout duplicates.
- **Provider-Centric ETL:** Refactored core ETL pipelines (Activities, Sleep, HRV) to utilize the high-level `Provider` interface, ensuring all data synchronization inherits the new self-healing capabilities.
- **Scheduled Workouts Tracking:** Added a 14-day forward-looking sync for the Garmin calendar, providing the coaching engine with full awareness of upcoming sessions.

### 🩹 Fixes & Compliance
- **Redundant SDK Decoupling:** Removed legacy git-based SDK dependencies in favor of standard package management.
- **Standardized Tool Interface:** Updated `clear_calendar` and `remove_workout` to align with the latest `BaseProvider` protocols.
- **Linting & Style:** Cleaned up unused imports and standardized the internal tool interfaces.

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
