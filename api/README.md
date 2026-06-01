# Biometric AI Platform - API & Agent Layer

This directory contains the core Agentic reasoning and backend services for the platform.

## Architecture

*   **FastAPI:** Provides a high-performance, asynchronous REST API (`/chat`).
*   **LangGraph:** Orchestrates the reasoning loop of the AI Agent (powered by `gemma-4-31b-it`).
*   **LangChain:** Used for embedding and Vector Store retrieval.

## Authentication (Garmin)

The platform uses browser-based authentication to bypass Cloudflare. On Linux/Raspberry Pi, you must install the following dependencies before syncing for the first time:

```bash
uv run playwright install chromium
sudo .venv/bin/python3 -m playwright install-deps
uv run python -m garmin_training_toolkit_sdk.auth
```

## Key Features & Optimizations

*   **Parallel Context Retrieval (`src/tools/retriever.py`):** Uses `ThreadPoolExecutor` to fetch 7 different biometric domains (Activities, Sleep, Status, Profile, Body Composition, Health Status, Telemetry) concurrently from BigQuery in **~3.0 seconds**.
*   **Persistent Health Tracking:** Subjective data (feeling, fatigue, injuries) is persisted via the `log_health_status` tool and BigQuery, ensuring the coach has multi-session physical context.
*   **Interannual Analysis:** The retriever supports `start_date` and `end_date` parameters for longitudinal studies (e.g., comparing fitness between 2025 and 2026).
*   **High-Signal Telemetry:** The retriever condenses second-by-second activity data into "mechanical summaries" (BPM, Watts, Vertical Oscillation, Ground Contact Time).
*   **High-Performance Inference:** `gemma-4-31b-it` reasons over the dense telemetry to spot advanced physiological trends like **Aerobic Decoupling** and form breakdowns in just **~3.0 seconds**. Total request time: **~6.0s**.
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
