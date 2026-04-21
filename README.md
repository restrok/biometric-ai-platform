# Biometric AI Platform

This repository contains the core Agentic RAG and SRE Infrastructure system for the biometric training analysis platform.

## Overview

The `biometric-ai-platform` is designed to be a "Product-Grade AI Platform" at a miniature scale. It ingests fitness data (originally extracted by `garmin-training-toolkit`), processes it through a Vector DB, and exposes an Agentic RAG API to serve as a personal AI trainer.

## Repository Structure (Monorepo)

This project follows a monorepo approach to separate infrastructure from application logic while keeping them versioned together:

- **`api/`**: The Agentic Backend. Contains the Python FastAPI application, LangGraph agents, LLM tool definitions, and Ragas evaluation pipelines. Managed using `uv`.
- **`infrastructure/`**: The SRE/Terraform definitions. Contains reusable Terraform modules (`network`, `storage`, `iam`) and environment definitions (e.g., `dev`) to provision the GCP resources required by the platform.
- **`ai-infra/`**: Documentation imported from the original planning phase. Contains architectural goals, roadmaps, and plans.

## Documentation

- [Project Goals](ai-infra/goal.md)
- [Architecture Plan](ai-infra/architecture-plan.md)
- [Development Roadmap](ai-infra/roadmap.md)

## Getting Started

### Prerequisites

- [uv](https://github.com/astral-sh/uv) (for Python package management)
- [Terraform](https://developer.hashicorp.com/terraform/install) (for Infrastructure as Code)

### API Development

```bash
cd api
uv run hello # Or activate the virtual environment
```

### Infrastructure Development

```bash
cd infrastructure/environments/dev
terraform init
terraform plan
```
