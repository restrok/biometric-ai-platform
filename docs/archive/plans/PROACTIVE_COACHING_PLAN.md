# 🏃 Proactive Biometric Coaching - Architecture & Implementation Plan

> **Status:** ✅ DONE

## 🎯 High-Level Objective
Transition the Biometric AI Platform from a **reactive** (Request-Response) system to a **proactive** coaching engine. The engine should automatically ingest data, detect critical physiological anomalies, and push high-signal alerts to the user via the `telegram-agent-orchestrator`.

---

## 🔍 Context & Discoveries (As of May 10, 2026)

### 1. User Profile: The "Silent Athlete" (Updated May 21, 2026)
- **Biotipo Ectomorfo:** Metabolismo "horno" con alta disipación térmica. Capacidad de almacenamiento limitada, requiere nutrición inmediata post-entreno (ventana de 30m) para evitar catabolismo.
- **High-Revving Heart:** Corazón con volumen sistólico moderado y frecuencia alta. **Z2 Alta (AeT ~160-165 bpm)** es el estado de flujo aeróbico normal.
- **Late Steady State:** El cuerpo alcanza el equilibrio metabólico real (Segunda Respiración) recién a los 8km de carrera.
- **Failing Thirst Response:** User does not feel thirst durante sesiones intensas pese a un **Cardiac Drift >10%**.
- **Neuromuscular Fatigue:** GCT aumenta bajo fatiga mecánica, perdiendo "stiffness" elástico.

### 2. Completed Work (Ready for Production)
- ✅ **High-Reliability Auth:** `ProviderFactory` centraliza el refresco proactivo de tokens e invalida la caché de memoria automáticamente.
- ✅ **Secret Manager Auto-Repair:** El sistema repara secretos dañados en GCP usando archivos locales automáticamente cuando detecta un fallo de versión.
- ✅ **Surgical ETL Sync:** El proceso de sincronización ahora solo sobreescribe ventanas de 14 días, preservando todo el historial pasado.
- ✅ **Proactive Failure Alerts:** Integración total con Telegram para notificar fallos de 401 o re-login en tiempo real.
- ✅ **Cost Optimization:** Destrucción automática de versiones antiguas de secretos en GCP (Mantenimiento de versión única).

---

## 🏛️ Proposed Proactive Architecture

We will implement a **Decoupled Notification Flow**:

1.  **Orchestrator (`telegram-agent-orchestrator`):**
    - Expose a generic `POST /api/notify` endpoint.
    - Payload: `{ "user_id": "fsirio", "agent_id": "biometric-coach", "message": "..." }`.
    - Function: Map `user_id` to Telegram `chat_id` and push the message.

2.  **Biometric Platform (`biometric-ai-platform`):**
    - **Background Worker:** A non-blocking loop in `main.py` (FastAPI) triggers `run_etl()` every 6 hours (configurable via `PROACTIVE_INTERVAL_HOURS`).
    - **Proactive Analyzer:** After sync (enabled via `ENABLE_PROACTIVE=true`), if certain thresholds are met (e.g., HRV < Baseline or Drift > 5%), the platform generates a summary and `POST`s it to the Orchestrator's notify endpoint.

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
