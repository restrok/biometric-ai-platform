# Master Plan V2: AI Infrastructure & Engineering PoC

This document updates the roadmap to align the project with AI Software Engineer and AI Infrastructure Lead roles ($150K+ USD), integrating advanced concepts of agents, quality evaluation, and operational optimization.

## 1. System Vision: From Simple RAG to "Biometric OS"

The goal is to move beyond simple data retrieval. We have built a system that reasons about physiological data, persists user-specific discoveries (like Aerobic Threshold), and takes autonomous action regardless of the hardware provider.

### Core Intelligence Components:
- **Standardized Provider Interface:** A brand-agnostic protocol that allows swapping Garmin for Suunto, Whoop, or Apple Health without changing agent logic.
- **Agentic reasoning:** A LangGraph-powered brain that prioritizes real telemetry (e.g., HR stability) over generic formulas.
- **Persistent Bio-Profiles:** Autonomous discovery and database persistence of unique user physiological thresholds.

---

## 2. Updated Roadmap: The 6 Layers of Success

### Phase 1: Critical Infrastructure (Terraform & GCP) - ✅ Implemented
- **Setup:** GCS, BigQuery, and Artifact Registry.
- **IAM & Security:** Granular role configuration ensuring the Principle of Least Privilege.
- **Networking:** Private endpoints to ensure biometric data remains secure.

### Phase 2: Data & Embedding Pipeline (Data Engineering) - ✅ Implemented
- **Ingestion:** Incremental ETL job processing activities and second-by-second telemetry.
- **Vector Store:** BigQuery Native Vector Search for exercise science grounding.
- **Sync Tool:** Agent-triggered data refresh (`sync_biometric_data`).

### Phase 3: Agentic Backend & Multi-Brand Architecture - ✅ Implemented
- **Framework:** LangGraph orchestrator with specialized nodes for retrieval and analysis.
- **Provider Pattern:** Decoupled SDK architecture using Abstract Base Classes (ABCs).
- **Semantic Tooling:** LLM-native tool definitions using semantic fields (`min_target`, `max_target`).

### Phase 4: Autonomous Action & Persistence - ✅ Implemented
- **Planner:** Agent can now design and upload training plans directly to the provider's calendar.
- **Profile Manager:** Agent can autonomously update the user's BigQuery profile with new physiological findings.
- **Standardized Tools:** Generic tools for clearing calendars, removing workouts, and uploading plans.

### Phase 5: Observability & FinOps (Operational Excellence) - ✅ Implemented
- **Token Tracking:** Detailed logging of token consumption and USD cost per request in BigQuery.
- **Latency Monitoring:** Measurement of parallel retrieval vs. reasoning cycles.
- **SRE Mindset:** Automated health checks and robust error handling in the agentic loop.

### Phase 6: The Evaluation Pipeline (AI Quality Assurance) - 🏃 In Progress
Key differentiator: demonstrating that we know how to measure AI "truth."
- **Framework:** Implementation of **Ragas** (Retrieval Augmented Generation Assessment).
- **Golden Metrics:** Faithfulness, Answer Relevance, and Context Precision.
- **Automated Testing:** CI/CD pipeline running evaluation tests for every prompt change.

---

## 3. Demonstrated Skills vs. Required JD

| Project Concept | JD Skill | Salary Impact |
| :--- | :--- | :--- |
| Agentic RAG / LangGraph | Multi-agent AI workflows | High (Architecture) |
| Provider Pattern / ABCs | Software Design Patterns | High (Senior Engineering) |
| Ragas / Eval Pipelines | LLM Evaluation Frameworks | Very High (Business Confidence) |
| Token & Cost Logging | Cost and Latency Optimization | Critical (SRE/FinOps Mindset) |
| FastAPI / Async Python | High-performance Backend | Base (Senior Engineering) |

---

## 🎯 Next Milestone: The Proactive Coach (Telegram Bot)

The next major expansion is the **Coach Bot**, a standalone module designed to run on a Raspberry Pi 5.

### System Architecture:
- **Host:** Docker container on local edge hardware.
- **Mode:** Long Polling (Zero network/port configuration required on the router).
- **Trigger:** Dual-mode (Reactive via messages and Proactive via scheduled jobs).

### Goals:
1.  **Proactive Check-ins:** The bot should message the user every morning (e.g., 8:00 AM) analyzing sleep/HRV and providing a motivational health insight.
2.  **Reactive Commands:** Support commands like `/status` (daily summary) or `/coach` (instant training advice).
3.  **Cross-Module Logic:** Import the `agent_executor` from the existing API to maintain reasoning consistency.

### SRE/Vibe-coding Requirements:
- **Secure by Design:** Use `TELEGRAM_USER_ID` filtering to ensure the bot only responds to its owner.
- **Healthchecks:** Implement a simple logging healthcheck so the bot's status can be monitored via `docker logs`.
- **Motivational Factor:** System prompt must prioritize recovery if biometric data indicates high fatigue, switching from "Push Harder" to "Prioritize Rest" automatically.
