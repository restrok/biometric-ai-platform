# 🏃 Proactive Biometric Coaching - Architecture & Implementation Plan

## 🎯 High-Level Objective
Transition the Biometric AI Platform from a **reactive** (Request-Response) system to a **proactive** coaching engine. The engine should automatically ingest data, detect critical physiological anomalies, and push high-signal alerts to the user via the `telegram-agent-orchestrator`.

---

## 🔍 Context & Discoveries (As of May 10, 2026)

### 1. User Profile: The "Silent Athlete"
- **Failing Thirst Response:** User does not feel thirst during or after high-intensity runs, even with significant **Cardiac Drift (>6%)**.
- **Perception Gap:** User feels "10/10" (mentally ready) while objective biometrics (**HRV 38ms - UNBALANCED**) indicate significant systemic stress.
- **Neuromuscular Fatigue:** Ground Contact Time (GCT) increases significantly (292ms → 301ms) late in sessions despite steady power, indicating lost "stiffness" and injury risk.

### 2. Completed Work (Ready for Production)
- ✅ **Multi-User Token Rotation:** `garmin_auth.py` now scans `/root/.garminconnect` for all user token files and refreshes them concurrently.
- ✅ **Robust BQ Schema Alignment:** `upsert_to_bq` automatically aligns Pandas DataFrame types with BigQuery table schemas (fixing `ArrowTypeError` and `400 BadRequest`).
- ✅ **HRV Baseline Integration:** The SDK and BigQuery now capture `status` (e.g., UNBALANCED), `baseline_low`, and `baseline_high`.
- ✅ **Clean Slate Sync:** Calendar sync now wipes all historical/future user-specific scheduled data to ensure BigQuery perfectly mirrors Garmin (Source of Truth).

---

## 🏛️ Proposed Proactive Architecture

We will implement a **Decoupled Notification Flow**:

1.  **Orchestrator (`telegram-agent-orchestrator`):**
    - Expose a generic `POST /api/notify` endpoint.
    - Payload: `{ "user_id": "fsirio", "agent_id": "biometric-coach", "message": "..." }`.
    - Function: Map `user_id` to Telegram `chat_id` and push the message.

2.  **Biometric Platform (`biometric-ai-platform`):**
    - **Background Worker:** Implement a non-blocking loop in `main.py` (FastAPI) that triggers `run_etl()` every 2-4 hours.
    - **Proactive Analyzer:** After sync, if certain thresholds are met (e.g., HRV < Baseline or Drift > 5%), the platform generates a summary and `POST`s it to the Orchestrator's notify endpoint.

---

## 🛠️ Implementation Roadmap

### Phase 1: Proactive Infrastructure (COMPLETED ✅)
1.  **Notification Hook:** Add the notification endpoint to the Orchestrator.
2.  **Auto-Sync Loop:** Add a background task in `biometric-coach-api` to run the ETL periodically.
3.  **Handoff Logic:** Create a utility in the API to send messages to the Orchestrator via the new endpoint.

### Phase 2: Deep Insight Features (COMPLETED ✅)
1.  **Hydration Safety Protocol:** (UPDATED 🛡️)
    - Calculate `Cardiac Drift` and `Estimated Sweat Rate`.
    - If Drift > 5%, push a message: *"Cardiovascular Drift Detected. Consider rehydrating with X liters (capped at 1.5L for safety)."*
2.  **HRV Stress Alert:** (DONE ✅)
    - Monitor HRV status and baseline.
    - If UNBALANCED or LOW, push a message: *"Recovery Alert: HRV Unbalanced. Today should be a Rest Day."*
3.  **Neuromuscular Guardrail:** (DONE ✅)
    - Monitor `GCT vs Power` ratio.
    - If GCT increases > 4% at steady power, push alert: *"Form breakdown detected. Next session must include recovery strides."*
4.  **RPE vs. HRV Tracking:** (DONE ✅)
    - After each sync, ask user for RPE (1-10) via Telegram.
    - Contrast RPE with next-day HRV to calibrate the "Perception Gap" index.

---

## 📋 Handoff Note for Next Agent
The current environment is the `biometric-ai-platform`. The user is moving the CLI to a higher directory to access both this project and `telegram-agent-orchestrator`. Use this document to initialize the new context. Both projects should be treated as a unified system for the "Proactive Coaching" objective.
