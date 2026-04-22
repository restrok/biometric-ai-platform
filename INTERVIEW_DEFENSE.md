# 🎯 Technical Interview Defense Guide: AI Infrastructure Platform

**Context:** Use this document to prep for $150K+ AI Software/Infrastructure Engineering roles. This frames the `biometric-ai-platform` and `garmin-toolkit` not as side projects, but as a professional **Enterprise AI Ecosystem**.

---

## 1. The Elevator Pitch
**Interviewer:** *"Tell me about your Biometric AI Platform."*

**Your Answer:** 
"I built a Product-Grade Agentic RAG Platform that provides research-backed training analysis. It's a decoupled ecosystem: 
1. A custom **Python SDK** (`garmin-toolkit`) that acts as an Anti-Corruption Layer, enforcing strict Pydantic contracts on biometric data.
2. An **Incremental Data Pipeline** that maintains a Native BigQuery Lakehouse, minimizing API load and GCP costs.
3. A **LangGraph-powered AI Agent** that bridges the gap between generic science and athlete reality by combining second-by-second telemetry with subjective 'Talk Test' feedback."

---

## 2. Key Architectural Decisions (The "Why")

### Q: Why use Incremental Sync instead of periodic full-loads?
**A: Efficiency and Rate-Limit Management.**
"Fetching 30 days of data on every run is an anti-pattern. I built an Incremental Sync engine that queries BigQuery for the `MAX(date)` of existing records and only requests the 'delta' from the Garmin API. This reduces network overhead, respects third-party rate limits, and ensures the platform scales efficiently as the user's history grows to years of data."

### Q: Why move from External GCS tables to Native BigQuery tables?
**A: Performance and Functional Richness.**
"External tables are great for zero-cost start-ups, but they lack performance for real-time AI agents. By transitioning to **Native BigQuery tables**, I gained sub-second query performance and native `WRITE_APPEND` support. This allows my LangGraph agent to retrieve and analyze thousands of rows of telemetry (second-by-second heart rate data) without the LLM timing out."

### Q: How do you handle "The Gray Zone" in your AI logic?
**A: Rule-Based Prompt Engineering + Detailed Telemetry.**
"Generic AI coaches just follow formulas. My agent is a 'Collaborative Sports Scientist'. It analyzes the user's **Talk Test** feedback (e.g., 'I can talk at 160 bpm') and validates it against the stability of their heart rate in the BigQuery telemetry. If the HR is stable and doesn't drift, the agent overrides the standard '220-age' formula and proposes **Custom HR Zones**, effectively moving the user's Aerobic Threshold based on objective performance data."

### Q: Tell me about your FinOps strategy. 
**A: The Zero-Surcharge Architecture.**
"The entire platform is designed to run in the **GCP Free Tier**. I use GCS for archival/audit logs (Parquet), Native BigQuery for the active Lakehouse (under 1TB/month query limit), and Google AI Studio (Gemini 1.5/2.5 Flash) for the reasoning engine. This demonstrates an ability to build production-ready AI infra with zero infrastructure spend during the R&D phase."

---

## 3. The "Deep Dive" Scenarios

### Q: How do you handle missing data (e.g., the user doesn't wear the watch at night)?
**A: Fail-Safe Retrieval Logic.**
"I implemented a 'Graceful Degradation' strategy in the retriever. If the BigQuery query for sleep or HRV returns empty because the user didn't wear the watch, the system doesn't crash. Instead, the retriever injects an 'Informational Context' into the prompt. The AI then acknowledges the lack of data and adjusts its recommendation (e.g., 'I see no sleep data, so I'll recommend an easy recovery run to be safe'). This builds trust with the user."

### Q: Why LangGraph instead of a simple OpenAI Assistant?
**A: Controllability and Observability.**
"I needed a stateful 'Reasoning Loop'. LangGraph allows me to define a clear cycle: **Retrieve -> Analyze -> Propose**. By separating the retrieval node from the analysis node, I can strictly control what context the LLM sees, preventing 'context stuffing' and ensuring the AI stays grounded in the scientific principles (80/20 rule) stored in my `legacy_logic/` documents."

---

## 4. Behavioral / "Lessons Learned"

**Interviewer:** *"What would you do differently if you had a $10,000 budget?"*

**Your Answer:**
"I would move the ETL job from a local script to **Google Cloud Dataflow** or **Workflows** for automated daily triggers. I'd also implement **Ragas** (RAG Evaluation) at scale, using a gold-standard dataset of exercise science questions to automatically score my agent's recommendations for accuracy and safety on every deployment."
