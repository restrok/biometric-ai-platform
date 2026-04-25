# Biometric AI Platform

This repository contains the core Agentic RAG and SRE Infrastructure system for the biometric training analysis platform.

## Overview

The `biometric-ai-platform` is a Product-Grade AI Ecosystem for athletic performance. It implements an **Agentic RAG** architecture that ingests multi-brand fitness data (Garmin, and future providers) into a **Native BigQuery Lakehouse**, performs second-by-second telemetry analysis, and provides research-backed training recommendations via a brand-agnostic **LangGraph** agent.

## Core Architecture

1. **Provider Layer (`garmin-training-toolkit-sdk`)**: A standardized, LLM-native SDK that implements a **Provider Pattern**. It abstracts proprietary brand logic behind a "Common Language" (Semantic Pydantic models).
2. **Data Pipeline**: An **Incremental ETL** job that maintains a high-performance BigQuery Lakehouse.
3. **Reasoning Layer**: A LangGraph AI Agent (Gemini 2.5 Flash) that prioritizes real physiological data and persists user-specific discoveries (like custom HR zones) back to the Data Lake.

## Performance & Intelligence

- **Standardized Provider Interface**: Swappable hardware providers (Garmin, Suunto, etc.) without changing agent logic.
- **Persistent Bio-Profiles**: The agent autonomously discovers physiological thresholds (like AeT) and updates the user's profile in BigQuery.
- **Actionable API**: Beyond chat, the API exposes endpoints for deterministic synchronization and profile management.
- **Parallel Context Retrieval**: Highly optimized BigQuery client leveraging `ThreadPoolExecutor`.

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
