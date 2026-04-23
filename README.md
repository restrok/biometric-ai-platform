# Biometric AI Platform

This repository contains the core Agentic RAG and SRE Infrastructure system for the biometric training analysis platform.

## Overview

The `biometric-ai-platform` is a Product-Grade AI Ecosystem for athletic performance. It implements an **Agentic RAG** architecture that ingests Garmin fitness data into a **Native BigQuery Lakehouse**, performs second-by-second telemetry analysis, and provides research-backed training recommendations via a **LangGraph** agent.

## Core Architecture

1. **SDK Layer (`garmin-toolkit`)**: A custom Python SDK that acts as an Anti-Corruption Layer, enforcing strict Pydantic contracts on raw Garmin data.
2. **Data Pipeline**: An **Incremental ETL** job that Maintains a high-performance BigQuery Lakehouse with sub-second retrieval times.
3. **Reasoning Layer**: A LangGraph AI Agent (Gemini 2.5 Flash) that prioritizes real physiological data (Observed Max HR, Heart Rate Drift) over generic age-based formulas.

## Performance & Intelligence

The platform achieves sub-10 second end-to-end latencies for complex biometric reasoning:
- **Parallel Context Retrieval**: Highly optimized BigQuery client leveraging `ThreadPoolExecutor` to fetch Activities, Sleep, Training Status, User Profile, Body Composition, and Second-by-Second Telemetry in **~3.0 seconds**.
- **High-Performance Inference**: Utilizes `gemini-2.5-flash` within LangGraph to process dense "mechanical summaries" and return structured advice in **~3.0 seconds**.
- **Advanced Physiological Insights**: The agent goes beyond basic summaries, autonomously detecting phenomena like **Aerobic Decoupling** and **Efficiency Leaks** by correlating Heart Rate, Power (Watts), Ground Contact Time (GCT), and Vertical Oscillation over time.

## Repository Structure (Monorepo)

- **`api/`**: The Agentic Backend. Contains the FastAPI app, LangGraph reasoning nodes, and BigQuery retrieval tools.
- **`infrastructure/`**: IaC (Terraform) for GCP Storage (Native BQ + GCS Archival), IAM, and Networking.
- **`docs/`**: Comprehensive documentation on setup, architecture, and development.
- **`legacy_logic/`**: Exercise science research and domain rules used to ground the AI's recommendations.

## Documentation

- [🚀 Getting Started (Setup)](docs/getting-started.md)
- [🛠️ Developer Guide](docs/developer-guide.md)
- [📐 Architecture Plan](docs/architecture-plan.md)
- [🎯 Project Goals](docs/goal.md)
- [🗺️ Development Roadmap](docs/roadmap.md)

## Getting Started

### 1. Ingest Data (ETL)
```bash
cd api
PYTHONPATH=src uv run python src/tools/etl_job.py
```

### 2. Start the AI API
```bash
cd api
PYTHONPATH=src uv run python main.py
```
Access the **Swagger UI** at: `http://localhost:8000/docs`
