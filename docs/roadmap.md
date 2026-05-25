# Biometric AI Platform Roadmap

This roadmap tracks the evolution of the platform from a simple Garmin extractor to a high-performance, multi-agent AI Expert System.

## Phase 1: Core Biometric Integration (Completed ✅)
- [x] **SDK Foundation**: Integrate Garmin Training Toolkit SDK for raw telemetry extraction.
- [x] **Data Lakehouse**: Set up BigQuery tables for activities, telemetry, sleep, and body composition.
- [x] **Multi-Client Auth**: Robust authentication with automatic token refresh for multiple users.
- [x] **LangChain Integration**: Build foundational tools for LLM-driven data retrieval.

## Phase 2: Agentic Architecture & LLM Native Optimizations (Completed ✅)
- [x] **LangGraph Orchestration**: Transition to stateful agent flows with Semantic Routing.
- [x] **Polarized 80/20 Logic**: Implement strict coaching rules grounded in exercise science.
- [x] **Self-Healing Loops**: Automatic error recovery and tool-use validation.
- [x] **OpenAI-Compatible API**: High-performance REST API with SSE streaming support.

## Phase 3: Reliability, Safety & Precision (Completed ✅)
- [x] **Universal Goals**: Persistence for race targets and long-term objectives.
- [x] **Hybrid Telemetry Architecture**: Dual-view strategy (Global + 5-min Segments) for sub-second precision.
- [x] **Hydration Safety Protocol**: Automated electrolyte advice with clinical-risk mitigation.
- [x] **Autonomous Athletic Director**: Proactive nightly sync cycles for calendar optimization.
- [x] **Smart Context Aging**: Automatic filtering of stale subjective logs (3-day TTL).

## Phase 4: Scaling & SRE Foundations (Completed ✅)
- [x] **Multi-User Identity**: Strict isolation of biometric data and sessions by `user_id`.
- [x] **Hybrid Storage (OLTP/OLAP)**: Implementation of the [Firestore vs. BigQuery](./database-design-guidelines.md) split for sub-30ms context retrieval.
- [x] **Semantic Conversation Memory**: Firestore persistence for "Golden Nuggets" (preferences, medical quirks) across sessions.
- [x] **Dockerized Ecosystem**: Full containerization of the API and background workers.

## Phase 5: Parallel Multi-Agent Orchestration (Completed ✅)
- [x] **Parallel Execution (Fan-out)**: LangGraph refactor to run specialist agents (**Injury, Sleep, Nutrition**) in parallel, reducing latency by 60%.
- [x] **Agent Discovery Loop**: Background DataScientist task to audit 30-90 days of history for 'rare' success markers.
- [x] **Predictive Load Modeler**: Integrated AC Ratio simulation to project training impact before prescription.
- [x] **Rich HTML Dashboards**: Generation of high-fidelity historical artifacts with SVG visualizations stored in GCS.

## Phase 6: Advanced Intelligence & Predictive SRE (Current Focus 🚧)
- [x] **Immune Radar**: Statistical anomaly detection using **Z-Scores** (Standard Deviations) to predict illness based on HRV and RHR shifts.
- [x] **Asynchronous Onboarding**: Automated 90-day historical backfill managed via Firestore state without blocking the agent.
- [x] **SRE-Driven Data Science**: BigQuery **Dry Run** evaluation to ensure query cost efficiency and partitioning optimization.
- [ ] **Precision Nutrition 2.0**: Integration of real-time telemetry (HR per step) for exact carbohydrate and protein replenishment math.
- [ ] **Cross-User Pattern Discovery**: (Admin only) Discovering global performance trends across the entire athlete population.
- [ ] **Wearable-Agnostic Interface**: Expansion to Suunto and Whoop via the [Standardized Provider Interface](./architecture-plan.md).
