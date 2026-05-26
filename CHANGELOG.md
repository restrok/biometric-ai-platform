# Changelog

All notable changes to this project will be documented in this file.

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
