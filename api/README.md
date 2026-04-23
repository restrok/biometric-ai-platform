# Biometric AI Platform - API & Agent Layer

This directory contains the core Agentic reasoning and backend services for the platform.

## Architecture

*   **FastAPI:** Provides a high-performance, asynchronous REST API (`/chat`).
*   **LangGraph:** Orchestrates the reasoning loop of the AI Agent (powered by `gemini-2.5-flash`).
*   **LangChain:** Used for embedding and Vector Store retrieval.

## Key Features & Optimizations

*   **Parallel Context Retrieval (`src/tools/retriever.py`):** Uses `ThreadPoolExecutor` to fetch 6 different biometric domains (Activities, Sleep, Status, Profile, Body Composition, Telemetry) concurrently from BigQuery in **~3.0 seconds**.
*   **High-Signal Telemetry:** The retriever condenses second-by-second activity data into "mechanical summaries" (BPM, Watts, Vertical Oscillation, Ground Contact Time).
*   **High-Performance Inference:** `gemini-2.5-flash` reasons over the dense telemetry to spot advanced physiological trends like **Aerobic Decoupling** and form breakdowns in just **~3.0 seconds**. Total request time: **~6.0s**.
*   **FinOps Tracking (`src/utils/finops.py`):** Asynchronously logs every LLM call's token usage, latency, and USD cost to a BigQuery `finops_logs` table.
*   **Vector Search (`src/tools/research_assistant.py`):** A LangChain tool that searches a BigQuery Native Vector Database for exercise science principles to ground the AI's recommendations.

## Directory Structure

*   `main.py`: FastAPI entrypoint.
*   `src/agent/`: LangGraph definitions and system prompts.
*   `src/tools/`: The tools available to the Agent (Retriever, Vector Search, Garmin Uploader) and the ETL job.
*   `src/utils/`: FinOps and logging utilities.
*   `scripts/`: Initialization scripts for BigQuery schemas and vector store backfills.
*   `tests/`: Agentic evaluation pipelines (Ragas integration planned).

## Running the API

Ensure your `.env` is configured with `GOOGLE_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, and `GOOGLE_CLOUD_PROJECT`.

```bash
uv run python main.py
```
