# Master Plan V2: AI Infrastructure & Engineering PoC

This document updates the roadmap to align the project with AI Software Engineer and AI Infrastructure Lead roles ($150K+ USD), integrating advanced concepts of agents, quality evaluation, and operational optimization.

## 1. System Vision: From Simple RAG to Agentic RAG

The goal is not just to answer questions, but to create a system that reasons about data. The system will use specific tools to resolve complex queries (e.g., "Compare today's power with my best mark of 2024").

### New Intelligence Components:
- **Router Agent:** Orchestrator that decides whether to consult the vector base (concepts) or BigQuery (exact data).
- **Tool Set:** Python functions that execute dynamic SQL queries or semantic searches.
- **Reasoning Loop:** Thought cycle to validate if the retrieved answer is useful before delivering it.

---

## 2. Updated Roadmap: The 5 Layers of Success

### Phase 1: Critical Infrastructure (Terraform & GCP)
Maintaining a solid SRE base but oriented towards AI.
- **Setup:** GCS, BigQuery, and Artifact Registry.
- **IAM & Security:** Granular role configuration so the AI only accesses what is necessary (Principle of Least Privilege).
- **Networking:** Private endpoints to ensure biometric data does not travel over the public internet.

### Phase 2: Data & Embedding Pipeline (Data Engineering)
- **Ingestion:** Cloud Function or ETL job processing .FIT files.
- **Vector Store:** Implementation of BigQuery Vector Search for semantic search.
- **Metadata Enrichment:** Adding context tags (weather, equipment type, time of day) to improve retrieval.

### Phase 3: Agentic Backend (AI Engineering) - ✅ Implemented
This is where we demonstrate high-level engineering skills.
- **Framework:** Implementation with LangChain or LangGraph.
- **Context Injection:** Parallel retrieval of 6 biometric domains in ~3s.
- **FastAPI Service:** Async API optimized for low latency (Reasoning in ~3s with Gemini 2.5 Flash).

### Phase 4: The Evaluation Pipeline (AI Quality Assurance)
Key differentiator: demonstrating that we know how to measure AI "truth."
- **Framework:** Implementation of **Ragas** (Retrieval Augmented Generation Assessment).
- **Golden Metrics:** Faithfulness, Answer Relevance, and Context Precision.
- **Automated Testing:** Pipeline running evaluation tests for every prompt change.

### Phase 5: Observability & FinOps (Operational Excellence) - ✅ Implemented
- **Token Tracking:** Detailed logging of token consumption per request and per user in BigQuery.
- **Cost Analysis:** Dashboard translating tokens into real USD operational costs.
- **Performance Benchmarking:** Measurement of Time-to-First-Token (TTFT) and total latency (~6s end-to-end).

---

## 3. Demonstrated Skills vs. Required JD

| Project Concept | JD Skill | Salary Impact |
| :--- | :--- | :--- |
| Agentic RAG / LangGraph | Multi-agent AI workflows | High (Architecture) |
| Ragas / Eval Pipelines | LLM Evaluation Frameworks | Very High (Business Confidence) |
| Token & Cost Logging | Cost and Latency Optimization | Critical (SRE/FinOps Mindset) |
| FastAPI / Async Python | High-performance Backend | Base (Senior Engineering) |

---

## 🎯 Next Milestone: The Autonomous Planner
After consolidating the Data Lakehouse and the Reasoning Loop, the next big step is to give the AI "hands":
- **Goal:** Allow the LangGraph Agent to design and publish workouts directly to the user's Garmin calendar.
- **Integration:** Wrap the `garmin_toolkit.uploaders.workouts` module as a callable **Tool** for the Agent.
- **Workflow:** User asks for a plan -> AI reads biometrics in BigQuery -> Designs plan using 80/20 rule -> Calls `upload_workouts_to_garmin` tool -> Plan appears on the user's watch, adapted to their current recovery state.
