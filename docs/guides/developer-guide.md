# 🛠️ Developer Guide

This guide explains the internal architecture and development workflows for the Biometric AI Platform.

## 🏗️ Core Architecture

The platform is designed as a **Parallel Agentic RAG** system, leveraging a hybrid storage engine.

```mermaid
graph TD
    User([User Request]) --> Router{Intent Classifier}
    Router -- Tool Need --> Retriever[Hybrid Context Retriever]
    
    subgraph "Parallel Analysis Phase (Fan-out)"
        Retriever --> Injury[🛡️ Injury Prevention]
        Retriever --> Sleep[🧬 Sleep & Circadian]
        Retriever --> Nutrition[⚖️ Metabolic Nutrition]
    end
    
    Injury --> Analyzer[Head Coach / Analyzer]
    Sleep --> Analyzer
    Nutrition --> Analyzer
    
    subgraph "Data & State Layer"
        Retriever --> FS[(Firestore OLTP)]
        Retriever --> BQ[(BigQuery OLAP)]
        FS --> Profiles[(User Profiles)]
        FS --> Memories[(Semantic Memory)]
        BQ --> Telemetry[(Biometric Telemetry)]
    end
    
    Analyzer -- "Action" --> Tools[Action Tools]
    Tools -- "State Update" --> FS
    Tools -- "Historical Backup" --> BQ
    
    Analyzer --> Validator[Response Validator]
    Validator --> User
```

### 1. Hybrid Data Layer (Firestore & BigQuery)
The system separates real-time operational state from massive analytical data following the [Database Design Guidelines](./database-design-guidelines.md).
*   **Firestore (OLTP):** The source of truth for the agent's immediate context. Stores user profiles, custom heart rate zones, active goals, and **Semantic Memories** ("Golden Nuggets"). Access is optimized for sub-30ms point lookups.
*   **BigQuery (OLAP):** The analytical data lake. Stores millions of rows of high-resolution biometric telemetry and historical execution logs. Optimized for the **Data Scientist** agent's exploratory SQL queries and long-term trend analysis.
*   **Asynchronous Onboarding:** New users trigger an automated 90-day historical backfill via the `etl_job.py`. This process runs in the background and is tracked via the `full_etl_synced` flag in Firestore.

### 2. SDK Layer (`garmin-toolkit`)
*   Acts as an **Anti-Corruption Layer**.
*   Implements a **Standardized Provider Interface** (Provider Pattern) to support multiple hardware brands.
*   **LLM-Native Models**:
    - **`RepeatGroup`**: Enables concise definition of interval sessions (e.g., 10x400m) in a single JSON block.
    - **Strongly Typed Targets**: Uses `HeartRateTarget`, `PaceTarget`, and `PowerTarget` with explicit fields (e.g., `min_bpm`) to remove ambiguity.
    - **Auto-Conversion**: The SDK handles the heavy lifting of converting high-level LLM intent (minutes, meters) into proprietary brand requirements (seconds, m/s).
*   **Introspection capabilities**: Extends the provider interface with `get_workout_templates()` to allow querying the user's established workout library efficiently.

### 3. Reasoning Layer (Agent Skills)
The platform's intelligence is modularized into **Skills**.
*   **`biometric-coach` Skill**: A portable set of instructions (`SKILL.md`) that transforms any agentic framework into an Exercise Physiologist.
*   **Multi-Tenancy Support**: The reasoning layer is user-aware. It extracts `user_id` from the `AgentState` (populated via the `X-User-ID` request header) to isolate data retrieval and device synchronization.
*   **Ethical & Precision Protocol**: Mandatory rules for separating data facts from physiological interpretation and avoiding overconfidence.
*   **State Graph Nodes (`api/src/agent/graph.py`):**
    - `retriever`: Fetches 7 context domains (Activities, Sleep, HRV, Scheduled Workouts, etc.) from BigQuery in parallel.
    - `analyzer`: Uses **Gemini 3.1 Flash Lite** with the coach skill to reason over the retrieved context.
    *   `tools`: Executes external actions. Standard tools include:
        *   `upload_training_plan`: Schedules tailored workouts on the user's device.
        *   `list_workouts`, `batch_remove_workouts`, `prune_unused_workouts`: Advanced workout library management leveraging SDK introspection to prevent capacity limits.
        *   `sync_biometric_data`: Triggers the ETL pipeline to refresh BigQuery.
        *   **update_user_zones**: Persists detected physiological thresholds to the user profile.
        *   **search_knowledge_base**: Native BigQuery vector search for exercise science.
        *   **generate_historical_report**: Computes long-term evolution and exports artifacts to GCS.

### 4. Historical Reporting Architecture
To avoid overwhelming the LLM context with years of data, historical analysis is offloaded to a specialized tool:
1.  **Computation**: The tool queries BigQuery for the full user history and calculates physiological metrics (Acute/Chronic Load, Efficiency Z-Scores).
2.  **Artifact Generation**: A detailed Markdown report is generated and uploaded to a private GCS bucket.
3.  **Secure Access**: The tool returns a **Signed URL** (valid for 1 hour) and a high-level summary.
4.  **Lean Context**: The agent only sees the summary, keeping the conversation fast and token-efficient.

### 5. Dynamic SSO Authentication Flow
The platform implements a Zero-CLI authentication model, allowing users to link their Garmin accounts directly through the chat interface.

```mermaid
sequenceDiagram
    participant User
    participant Agent
    participant GarminSSO as Garmin SSO Portal
    participant SM as Google Secret Manager
    
    User->>Agent: "Coach, connect my Garmin"
    Agent->>Agent: get_garmin_auth_url()
    Agent-->>User: Provides secure SSO link
    User->>GarminSSO: Logs in & resolves MFA
    GarminSSO-->>User: Redirects to ticket page
    User->>Agent: Pastes redirect URL/Ticket
    Agent->>Agent: complete_garmin_auth(ticket)
    Agent->>SM: Persists OAuth Tokens (per-user)
    Agent-->>User: "Connection Successful ✅"
```

### 6. Secret Management & Token Persistence
*   **Encrypted Storage:** All Garmin OAuth tokens are stored in **Google Secret Manager** using the naming convention `garmin-tokens-{user_id}`.
*   **Automated Lifecycle:** A background loop in `api/main.py` refreshes all active user sessions every 2 hours, rotating `di_client_id` to ensure high availability and pushing updated tokens back to the cloud.
*   **Zero-State Architecture:** The API is designed to be stateless; it can be restarted or redeployed without losing user sessions as long as GCP Secret Manager is accessible.

### 7. Intelligence Implementation (Phase 6)

*   **Parallel Expert Analysis (Fan-out):** Domain specialists (**Injury, Sleep, Nutrition**) analyze the context in parallel, significantly reducing request latency while providing multi-dimensional insights.
*   **Immune Radar (Statistical SRE):** Implements an anomaly detection algorithm in `api/src/agent/proactive.py`. It uses **Z-Scores** to compare daily HRV and RHR against a 21-day rolling average. Large deviations (e.g., HRV Z < -1.5) trigger a proactive alert for impending illness.
*   **Data Scientist Dry Run (Cost Control):** The Data Scientist agent is mandated to call `execute_exploratory_query_dry_run` before any BigQuery execution. This allows the system to evaluate scan costs and enforce query optimization (partition filtering) before incurring analytical costs.
*   **Semantic Memory Extraction:** A post-analysis node that extracts facts (preferences, constraints) from the conversation and persists them in Firestore, ensuring the coach maintains a long-term "Golden Nugget" profile for each athlete.

        ---

        ## 💎 Engineering Standards

All contributions must adhere to the following quality gates:

### 1. Python Standards
- **Linter & Formatter:** We use `ruff`. Run `uv run ruff check --fix .` and `uv run ruff format .` before committing.
- **Static Analysis:** `mypy` is mandatory for type checking. Run `uv run mypy .` to ensure type safety.
- **Style Guide:** Follow the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).

### 2. Infrastructure Standards
- **Terraform Formatting:** Always run `terraform fmt -recursive` in the `infrastructure/` directory.

### 3. Language & Documentation
- **Language:** Strictly English (US) for all code, comments, and documentation.
- **Docs-as-Code:** Keep the `docs/` directory updated. Use Mermaid.js for architecture diagrams.

        ---

        ## 🛠️ Development Workflows


### 1. Adding a New Tool
1.  Define the tool function in `api/src/tools/`.
2.  Use the `@tool` decorator from `langchain_core.tools`.
3.  Add the tool to the `tools` list in `api/src/agent/graph.py`.
4.  Bind the tool to the LLM and update the `ToolNode`.

### 2. Modifying the System Prompt
The `SYSTEM_PROMPT` is the "brain" of the agent. It is located in `api/src/agent/graph.py`. When updating it:
*   Maintain the **Exercise Physiologist** persona.
*   Keep the **Grounding Rules** for scientific accuracy.
*   Ensure **Response Structure** remains consistent (Tables, Bold Headers).

### 3. Local Debugging
To debug the agent without starting the FastAPI server, use the `reproduce_issue.py` pattern:
```python
from src.agent.graph import graph
initial_state = {"messages": [HumanMessage(content="Query")]}
result = await graph.ainvoke(initial_state)
```

---

## 🚀 Project Operational Rules

### Environment & Tools
- **Python (Runtime):** ALWAYS use `uv run` for script execution or troubleshooting within the `api/` directory. This ensures all dependencies (pandas, pydantic, etc.) are correctly loaded from the virtual environment.
- **Tool Execution:** Internal tools should be invoked via `uv run scripts/manage_tools.py call <tool_name> '<args>'`.
- **BigQuery:** This is the primary source of truth for all historical biometric context. Tables are partitioned by a `user_id` column.
- **Garmin Tokens:** Persisted at `~/.garminconnect/garmin_tokens_<user_id>.json`.
- **Model Discovery:** To check available models and their exact API identifiers (especially when using free-tier keys), use the following command:
  ```bash
  curl "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_API_KEY"
  ```

### Authentication Setup (Linux/Raspberry Pi)
On headless Linux systems, the browser-based authentication requires manual system setup:
1.  **Install Browser:** `uv run playwright install chromium`
2.  **Install Libraries:** `sudo .venv/bin/python3 -m playwright install-deps`
3.  **Run Auth:** `uv run python -m garmin_training_toolkit_sdk.auth`

---

## 📊 Observability & FinOps
*   **FinOps Logging:** Every LLM call is logged to `biometric_data_dev.finops_logs` in BigQuery.
*   **Tracing:** Tracing can be enabled using LangSmith (optional).
*   **Pricing:** Model costs are defined in `api/src/utils/finops.py`.

---

## 🧪 Testing & Validation
*   **Integration Tests:** Located in `api/tests/test_finops_integration.py` and `api/tests/test_vector_rag.py`.
*   **Evaluation:** Ragas-based evaluation for RAG quality (Context Precision, Faithfulness) is planned.

---

## 🚀 Infrastructure & Deployment

The infrastructure is managed via **Terraform** in the `/infrastructure` directory. It follows a modular architecture for better maintainability and reusability.

### 1. Modular Architecture
*   **`modules/storage`**: Manages the BigQuery datasets and Google Cloud Storage buckets (Data Lake and Terraform State).
*   **`modules/iam`**: Handles Service Account creation and precise IAM role assignments (BigQuery Viewer/JobUser, Storage ObjectViewer).
*   **`modules/secrets`**: Sets up Secret Manager secrets (e.g., `garmin-tokens`, `aistudio-api-key`).
*   **`modules/billing`**: Configures budget alerts and safety caps to prevent unexpected costs.

### 2. State Management
We use a **GCS Backend** for state management, which enables team collaboration and state versioning. 
*   **Partial Configuration**: Sensitive backend details (bucket name) are stored in `backend.tfvars` (local only).
*   **Security**: All `*.tfvars` files are ignored by git. Use `terraform.tfvars.example` as a template.

### 3. CI/CD (Future)
*   The API can be containerized using the provided `Dockerfile` and deployed to **Google Cloud Run**.
*   Workflows are being established in `.github/workflows/ci.yml` for automated testing.
