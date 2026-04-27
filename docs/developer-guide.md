# 🛠️ Developer Guide

This guide explains the internal architecture and development workflows for the Biometric AI Platform.

## 🏗️ Core Architecture

The platform is designed as an **Agentic RAG** system, decoupled into several specialized layers.

### 1. Data Layer (BigQuery Lakehouse)
*   **Native Tables:** All biometric data is stored in Native BigQuery tables for sub-second retrieval.
*   **Schema Consistency:** The `etl_job.py` enforces schema rules (e.g., casting `run_walk_index` to float) to prevent load failures.
*   **Vector Database (RAG):** We use BigQuery's native `VECTOR_SEARCH` capabilities for the exercise science knowledge base.
    *   **Implementation:** The knowledge base is stored in the `biometric_data_dev.knowledge_base` table.
    *   **Embeddings:** We use the `models/gemini-embedding-001` model via Google Generative AI to generate 768-dimensional embeddings for Markdown chunks.
    *   **Knowledge Sync (`upload_knowledge.py`):** This script manages the RAG data lifecycle. It uses `DirectoryLoader` to parse Markdown files, `RecursiveCharacterTextSplitter` (chunk size 1000, overlap 100) for chunking, and uploads the results to BigQuery.
    *   **Retrieval:** The agent uses a `search_knowledge_base` tool that performs a `VECTOR_SEARCH` on BigQuery using the user query's embedding.

### 2. SDK Layer (`garmin-toolkit`)
*   Acts as an **Anti-Corruption Layer**.
*   Implements a **Standardized Provider Interface** (Provider Pattern) to support multiple hardware brands.
*   **LLM-Native Models**:
    - **`RepeatGroup`**: Enables concise definition of interval sessions (e.g., 10x400m) in a single JSON block.
    - **Strongly Typed Targets**: Uses `HeartRateTarget`, `PaceTarget`, and `PowerTarget` with explicit fields (e.g., `min_bpm`) to remove ambiguity.
    - **Auto-Conversion**: The SDK handles the heavy lifting of converting high-level LLM intent (minutes, meters) into proprietary brand requirements (seconds, m/s).

### 3. Reasoning Layer (Agent Skills)
The platform's intelligence is modularized into **Skills**.
*   **`biometric-coach` Skill**: A portable set of instructions (`SKILL.md`) that transforms any agentic framework into an Exercise Physiologist.
*   **Ethical & Precision Protocol**: Mandatory rules for separating data facts from physiological interpretation and avoiding overconfidence.
*   **State Graph Nodes (`api/src/agent/graph.py`):**
    - `retriever`: Fetches 6 context domains (Activities, Sleep, HRV, etc.) from BigQuery in parallel.
    - `analyzer`: Uses **Gemini 2.5 Flash** with the coach skill to reason over the retrieved context.
    *   `tools`: Executes external actions. Standard tools include:
        *   `upload_training_plan`: Schedules tailored workouts on the user's device.
        *   `sync_biometric_data`: Triggers the ETL pipeline to refresh BigQuery.
        *   **update_user_zones**: Persists detected physiological thresholds to the user profile.
        *   **search_knowledge_base**: Native BigQuery vector search for exercise science.

        ### 4. Intelligence Implementation (Safety & Stability)
        The agent's reasoning loop is governed by several core logic patterns to ensure reliability:

        *   **Noise Reduction (Windowing):** The `analyzer` node is prompted to look for reproducibility. It must compare multiple telemetry segments from the `retriever` before suggesting a profile update.
        *   **Cold Start Logic:** If `biometric_context['recent_activities']` is empty or only contains info messages, the `analyzer` is programmed to switch to "Calibration Mode." It will refuse to call `upload_training_plan` with high-intensity workouts and instead recommend a 2-week baseline-gathering phase.
        *   **Scientific Grounding:** The system uses the `Karvonen Formula` as a fallback when empirical Aerobic Threshold (AeT) data is unavailable.

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

## 📊 Observability & FinOps
*   **FinOps Logging:** Every LLM call is logged to `biometric_data_dev.finops_logs` in BigQuery.
*   **Tracing:** Tracing can be enabled using LangSmith (optional).
*   **Pricing:** Model costs are defined in `api/src/utils/finops.py`.

---

## 🧪 Testing & Validation
*   **Integration Tests:** Located in `api/tests/test_finops_integration.py` and `api/tests/test_vector_rag.py`.
*   **Evaluation:** Ragas-based evaluation for RAG quality (Context Precision, Faithfulness) is planned.

---

## 🚀 Deployment (Future)
*   The API can be containerized using the provided `Dockerfile` (TBD) and deployed to **Google Cloud Run**.
*   Infrastructure is managed via **Terraform** in the `/infrastructure` directory.
