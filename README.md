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
- **Power & Efficiency Analytics**: The ETL pipeline calculates `avg_power` from telemetry, enabling historical **Watts per Kilogram (W/kg)** trend analysis.
- **Parallel Context Retrieval**: Highly optimized BigQuery client leveraging `ThreadPoolExecutor`.

## Intelligence & Safety

To ensure high-quality coaching and prevent overreaction to "noisy" data, the platform implements several advanced reasoning protocols:

### 1. Noise Reduction (The "3-Run Rule")
The agent does not react to single outliers or "hero runs." It is instructed to look for **reproducible physiological evidence** across a window of 3-5 activities. For example, a heart rate zone shift is only suggested if telemetry shows stability (no significant drift) across multiple 45+ minute efforts.

### 2. Cold Start Protocol (New Users)
For users with zero historical data, the system transitions from **Prescription** to **Discovery Mode**:
- **Safety Valve**: Refuses to prescribe high-intensity (Zone 4/5) sessions until a baseline is established.
- **Calibration Phase**: Recommends 1-2 weeks of easy Zone 2 runs to gather initial efficiency metrics (GCT, VO, HR drift).
- **Smart Baselines**: Uses the **Karvonen Formula** (Age + Resting HR) to estimate zones until empirical data takes over.

### 3. Scientific Guardrails
The agent's reasoning loop is bounded by conservative exercise science:
- **Volume Cap**: Weekly volume increases are capped at 10%.
- **Polarized Balance**: Enforces the 80/20 rule (80% low intensity).
- **Recovery Override**: Prioritizes rest if Sleep Score (<60) or HRV indicates high fatigue, regardless of performance goals.

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
