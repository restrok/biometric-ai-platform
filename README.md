# 🏃 Biometric AI Platform: Multi-Agent Sports Physiology Engine

An enterprise-grade, multi-agent sports physiology platform built with **LangGraph**, **FastAPI**, and a **Hybrid GCP Lakehouse (Firestore + BigQuery + BigQuery Vector Search)**.

The platform continuously analyzes endurance athlete telemetry (heart rate, power, Ground Contact Time, vertical oscillation, HRV, sleep) to provide personalized, science-grounded coaching, prevent overtraining, and automatically synchronize structured workouts to Garmin devices.

---

## 📸 Showcase & Key Capabilities

Experience how the AI Coach reasons across multiple biometric domains. Run these in your preferred client or via the REST API.

### 1. Holistic Recovery & Readiness (Gemma 4 31B)
> *"Look at my sleep quality from last night and my HRV trend. Given today's workout, am I ready for a high-intensity session tomorrow?"*  
*Highlights: Multi-domain parallel fan-out (Sleep + Injury + Nutrition).*  
![Recovery Readiness Analysis](./docs/assets/screenshots/telemetry-analysis.png)

### 2. Deep Telemetry & Sprint Analysis (Gemma 4 31B)
> *"Analyze my last run activity. How was my efficiency during that final sprint?"*  
*Highlights: Mechanical cost vs. power output, Ground Contact Time drift.*  
![Sprint Efficiency](./docs/assets/screenshots/gemma-sprint-analysis.png)

### 3. Scientific Grounding (BigQuery Vector Search RAG)
> *"Explain the 'Polarized 80/20' model and why you keep warning me about the 'Gray Zone.' Use my recent data to show my Z3 time."*  
*Highlights: BigQuery Vector Search with Gemini Embeddings (`gemini-embedding-001`).*  
![Scientific RAG](./docs/assets/screenshots/scientific-rag.png)

---

## ✨ Why Choose Biometric AI?

### 🔬 Science-Backed, Not Generic
Generic plans don't know when you slept poorly. Our AI Coach uses **Agentic RAG (Retrieval-Augmented Generation)** grounded in exercise physiology to dynamically adjust your training based on the **Polarized (80/20) Model**.

### 🫀 Second-by-Second Telemetry Analysis
We don't just look at average heart rate. The platform analyzes **Ground Contact Time (GCT), Vertical Oscillation, and Power (Watts)** to detect subtle form breakdowns and Aerobic Decoupling (Cardiac Drift)—catching fatigue before it causes an injury.

### 🛡️ Safety & Intelligence First
- **The "3-Run Rule":** The AI won't overreact to a single bad day or "hero run." It requires reproducible evidence across multiple activities before adjusting training zones.
- **Smart Calibration:** For new athletes, the engine enters a "Discovery Mode," prescribing easy Zone 2 runs until a personal physiological baseline is established.
- **Recovery Overrides:** If your HRV tanks or your Sleep Score drops below 60, the AI intervenes, prioritizing biological rest over rigid workout targets.

---

## 🚀 Highlights & Features

- **Parallel Multi-Agent Engine:** Fast fan-out execution across specialized agents (**Injury Prevention**, **Sleep & Circadian**, **Metabolic Nutrition**).
- **BigQuery Vector Search RAG:** Deep retrieval of research-backed sports science literature via vector search.
- **SQL-Native ACWR Engine:** BigQuery View computing rolling Acute:Chronic Workload Ratios dynamically.
- **Immune Radar:** Proactive stress monitoring via 21-day rolling Z-scores of HRV and Resting Heart Rate.
- **SRE & FinOps Guardrails:** Dry-run scan ceilings (500 MB) and automated token/cost tracking per request.
- **Semantic Memory:** Persists long-term facts, preferences, and injury history across user sessions.

---

## 📚 Documentation & Technical Specifications

For full system architecture diagrams, database schemas, and developer specifications, check our [Documentation Index](docs/README.md):

- [📐 System Architecture & Multi-Agent Overview](docs/architecture/system-overview.md) — Detailed LangGraph topology, Mermaid diagrams, and agent mandates.
- [🗄️ Database Architecture](docs/architecture/database-design.md) — Firestore OLTP, BigQuery OLAP, and ACWR view specs.
- [🛡️ SRE & Observability Standards](docs/architecture/sre-and-observability.md) — Dry-run cost ceilings, OpenTelemetry, and FinOps logging.
- [🚀 Getting Started Guide](docs/guides/getting-started.md) — Local installation & environment configuration.
- [🛠️ Developer Guide](docs/guides/developer-guide.md) — Testing, linting, and development workflows.
- [🔌 External Agent API Guide](docs/guides/external-agent-api-guide.md) — REST endpoints and multi-tenant headers.

---

## ⚡ Quick Start

### 1. Installation
```bash
git clone https://github.com/restrok/biometric-ai-platform.git
cd biometric-ai-platform/api
uv sync
```

### 2. Environment Configuration
Create a `.env` file in `api/`:
```env
GOOGLE_CLOUD_PROJECT=bio-intelligence-dev
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
LLM_PROVIDER=google
CORE_MODEL_NAME=gemma-4-31b-it
DS_MODEL_NAME=gemma-4-31b-it
```

### 3. Verification & Execution
```bash
# Run tests and quality checks
PYTHONPATH=. uv run pytest
uv run ruff check

# Start the API service
uv run python main.py
```
*Access the interactive API console at: `http://localhost:8000/docs`*
