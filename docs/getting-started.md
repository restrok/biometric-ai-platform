# 🚀 Getting Started

This guide will help you set up the Biometric AI Platform from zero.

## Prerequisites

1.  **Google Cloud Project (GCP):**
    *   Create a project (e.g., `bio-intelligence-dev`).
    *   Enable **BigQuery API** and **Cloud Storage API**.
    *   Install the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install).
    *   Authenticate locally: `gcloud auth application-default login`.

2.  **Python Environment:**
    *   Install [uv](https://github.com/astral-sh/uv).
    *   Python 3.11+.

3.  **Garmin Account:**
    *   A valid Garmin Connect account with activity data.

---

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/biometric-ai-platform.git
cd biometric-ai-platform
```

### 2. Setup API Environment
```bash
cd api
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync
```

### 3. Configure Environment Variables
Create a `api/.env` file:
```env
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_API_KEY=your-gemini-api-key
# Optionally include GOOGLE_APPLICATION_CREDENTIALS if not using default login
```

---

## 📊 Data Infrastructure Setup

### 1. Deploy Cloud Resources (Terraform)
If you haven't deployed the BigQuery datasets and GCS buckets yet:
```bash
cd infrastructure
terraform init
terraform apply -var-file="envs/dev.tfvars"
```

### 2. Initialize BigQuery Tables and Knowledge Base
Run the initialization scripts to create the necessary schemas and upload running principles to the RAG:
```bash
cd api
uv run scripts/init_profile_tables.py
uv run scripts/init_finops_bq.py

# Upload running principles from /knowledge_base folder
uv run scripts/upload_knowledge.py --reset
```

---

## 🔄 Synchronizing Data (Garmin to BigQuery)

### 1. Authenticate with Garmin
Run the browser-based authentication to generate session tokens:
```bash
cd api
uv run python -m garmin_training_toolkit_sdk.auth
```
*Note: This will save tokens to `~/.garminconnect/garmin_tokens.json`.*

### 2. Run the Incremental ETL
Fetch your latest activities and telemetry:
```bash
cd api
PYTHONPATH=src uv run python src/tools/etl_job.py
```

### 3. Update the Knowledge Base (RAG)
The AI agent uses a RAG (Retrieval-Augmented Generation) system to answer questions about exercise science. You can add your own research papers, training plans, or notes in Markdown format to the `/knowledge_base` directory.

To sync new files to the AI's research base:
```bash
cd api
# To add new files without deleting existing ones:
uv run scripts/upload_knowledge.py

# To specify a different folder:
uv run scripts/upload_knowledge.py --folder my_research_folder

# To wipe the research base and re-upload everything:
uv run scripts/upload_knowledge.py --reset
```
*Note: This process generates embeddings using Gemini and stores them in BigQuery.*

---

## 🤖 Running the AI Agent

### 1. Start the FastAPI Server
```bash
cd api
uv run python main.py
```

### 2. Interact with the Agent
Access the Swagger UI at `http://localhost:8000/docs` or use `curl`:
```bash
curl -X 'POST' \
  'http://localhost:8000/chat' \
  -H 'Content-Type: application/json' \
  -d '{"message": "Analyze my last run efficiency."}'
```

---

## 🧪 Testing
Run the evaluation and integration tests:
```bash
cd api
uv run pytest tests/
```
