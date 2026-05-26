# 🚀 Getting Started

This guide will help you set up the Biometric AI Platform from zero.

## Prerequisites

1.  **Google Cloud Project (GCP):**
    *   Create a project (e.g., `your-project-id`).
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
The infrastructure is modularized and uses a remote GCS backend for state management.

1.  **Configure Variables**:
    ```bash
    cd infrastructure
    cp terraform.tfvars.example terraform.tfvars
    # Edit terraform.tfvars with your GCP Project ID and Billing Account
    ```

2.  **Configure Backend**:
    Create a `backend.tfvars` (ignored by git) to specify where to store your state:
    ```hcl
    bucket = "your-tf-state-bucket-name"
    prefix = "terraform/state"
    ```

3.  **Initialize and Apply**:
    ```bash
    terraform init -backend-config=backend.tfvars
    terraform apply
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

## 🔄 Synchronizing Data (Provider to BigQuery)

### 1. Authenticate with your Provider
For Garmin, run the browser-based authentication to generate session tokens. 

**Note for Linux/Raspberry Pi users:** You must first install the browser and its system dependencies:
```bash
cd api
# Install the browser
uv run playwright install chromium
# Install system libraries (requires sudo)
sudo .venv/bin/python3 -m playwright install-deps
```

Then run the authentication script:
```bash
# Authenticate a specific user
uv run python -m garmin_training_toolkit_sdk.auth
```
*Note: For multi-user setups, rename the resulting token file to `garmin_tokens_<user_id>.json` in your `.garminconnect/` folder.*

### 2. Run the Incremental ETL
Fetch your latest activities and telemetry:
```bash
# Option A: Command line
cd api
PYTHONPATH=src uv run python src/tools/etl_job.py

# Option B: API endpoint
curl -X 'POST' 'http://localhost:8000/sync' -H 'X-User-ID: your_id'
```

---

## 🤖 Running the AI Agent

### 1. Start the FastAPI Server
```bash
cd api
uv run python main.py
```

### 2. Interact with the Agent
The API supports **Multi-User Context Isolation** via the `X-User-ID` header:

*   **Chat (Agentic RAG):** `POST /v1/chat/completions`
    ```bash
    curl -X 'POST' \
      'http://localhost:8000/v1/chat/completions' \
      -H 'Content-Type: application/json' \
      -H 'X-User-ID: fsirio' \
      -d '{
        "model": "biometric-coach",
        "messages": [{"role": "user", "content": "Analyze my last run efficiency."}]
      }'
    ```
*   **Manual Sync:** `POST /api/v1/tools/biometric/sync`
*   **Profile Management:** `POST /api/v1/tools/zones/update`
    ```bash
    curl -X 'POST' \
      'http://localhost:8000/api/v1/tools/zones/update' \
      -H 'Content-Type: application/json' \
      -H 'X-User-ID: fsirio' \
      -d '{"z1_max": 143, "z2_max": 165, "z3_max": 176, "z4_max": 186}'
    ```

---

## 🧪 Testing
Run the evaluation and integration tests:
```bash
cd api
uv run pytest tests/
```

---

## 🏗️ Running with Docker

For production-like environments or home servers (e.g., Raspberry Pi), you can run the platform using Docker Compose.

### 1. Build and Start
```bash
docker-compose up -d --build
```

### 2. Monitoring Logs
```bash
docker-compose logs -f api
```

The container automatically manages the **2-hour Garmin token refresh loop**, ensuring your connection stays alive 24/7.
