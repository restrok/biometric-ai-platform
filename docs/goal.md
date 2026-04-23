# Project Goal

The ultimate goal is not just a tool to view your Garmin statistics; the goal is to build a miniature "Product-Grade AI Platform."
For a recruiter or a hiring manager at an AI startup, what you are providing is proof that you can handle the most expensive and complex infrastructure that exists today.

## 1. The Strategic Objective (The Goal)
Demonstrate that you are an AI Infrastructure Engineer—someone who understands that an LLM is just a small piece of a much larger system. The goal is to move from "managing servers" to "managing the lifecycle of intelligence."
You will demonstrate three critical capabilities:
- **Data Gravity:** How to move biometric data (Garmin) securely and efficiently to the cloud.
- **Context Injection (RAG):** How to make a generalist AI become an expert in you and your training without spending thousands of dollars re-training it.
- **Efficiency (FinOps):** How to run all of this professionally while spending only cents.

## 2. What are we generating? (The Deliverables)
What will live in your GitHub and in the cloud is the following:
### A. A Smart Data Lake (GCP)
An automated system where you upload data, and in seconds, the data is cleaned in BigQuery and transformed into vectors (embeddings) in a Vector DB.
**Value:** Demonstrates that you know how to build data pipelines for AI.

### B. A RAG Engine (Retrieval-Augmented Generation)
An API (on Cloud Run or GKE) that acts as an "AI Personal Trainer."
**How it works:** When you ask a question, the system searches your vector database for your best runs, passes them to the LLM as context, and the LLM responds with authority based on your own data.
**Value:** This is the technology used by leading AI startups.

### C. The "SRE Wrapper"
A Terraform repository that deploys everything with a single command and a dashboard (Grafana/Cloud Monitoring) that shows how much each question you ask the AI costs.
**Value:** This is what differentiates you from an average developer. It shows order, security, and cost control.

## 4. Strategic Vision: The "Garmin" Integration Case Study
If this platform were integrated natively into the Garmin ecosystem, it would transform from a data dashboard into an **Autonomous Intelligence Engine**. Here are the top 3 strategic integration paths:

### A. The "Dynamic Training Plan" (Native Ecosystem)
**The Problem:** Current training plans are static.
**The Solution:** The agent uses the `upload_workouts_to_garmin` tool to constantly overwrite the user's calendar based on daily recovery.
**User Experience:** If a user's HRV or Sleep Score is "Poor," the agent automatically replaces a scheduled "Tempo Run" with a "Rest Day" on their watch, explaining the scientific reasoning via a push notification.

### B. The "Coach-in-Your-Ear" (Connect IQ)
**The Problem:** Users only see analysis after syncing, often hours after a run.
**The Solution:** A Connect IQ (Monkey C) app that acts as the real-time interface for the agent's reasoning.
**User Experience:** Immediately after a workout, the user receives a briefing on their watch: *"Vertical Oscillation increased by 2cm in the last mile—you were fatiguing. Recommendation: 2 extra hours of recovery and focus on glute activation."*

### C. The "Intelligence API" (B2B Partner Strategy)
**The Problem:** Professional coaches struggle to analyze second-by-second telemetry for dozens of athletes.
**The Solution:** Expose the LangGraph nodes as a high-scale API for coaching platforms (Strava, TrainingPeaks).
**User Experience:** Coaches see an "AI Diagnostic" flag next to athletes, highlighting "Aerobic Decoupling" or form breakdowns automatically, allowing them to intervene before injury occurs.

---

### Performance Benchmark Reached (Update)
The system has reached a critical milestone in latency and reasoning capacity:
*   **End-to-End Latency:** ~6 seconds.
*   **Retrieval (Data Gravity):** ~3 seconds using `ThreadPoolExecutor` to query 6 biometric domains in BigQuery in parallel.
*   **Inference (Context Injection):** ~3 seconds using `gemini-2.5-flash`.
*   **Intelligence:** The AI is capable of processing dense second-by-second mechanical summaries (Power, HR, GCT, VO) to autonomously detect complex physiological phenomena such as **Aerobic Decoupling** and "efficiency leaks" in running technique, confirming the "Product-Grade" level of the platform.
