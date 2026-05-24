# SensorFM Integration & Historical Reporting Architecture Plan

## Background & Motivation
The recent "SensorFM" paper by Google Research demonstrates the immense potential of scaling both data volume and model reasoning capacity for wearable health data. Currently, our platform excels at analyzing recent, surgical windows (e.g., the last 3-5 runs using event-based telemetry aggregation). However, we lack a robust mechanism for **Deep Historical Reporting** (e.g., evaluating 3-6 months of data) and we rely on static, pre-engineered SQL queries for analysis.

This plan outlines how we will implement key SensorFM concepts into our Biometric AI Platform to transition from a responsive coach to a "General Health AI."

## Scope & Key Improvements

### 1. Deep Historical Reporting Engine
Our current `retrieve_biometric_data` is optimized for speed and short-term context. We need a dedicated engine capable of processing massive historical windows without hitting token limits.
*   **Long-Term Trend Analysis:** Evaluate 3 to 6 months of data across the 35 health domains highlighted in SensorFM (e.g., Cardiovascular, Sleep, Neuromuscular).
*   **Statistical Abstraction:** Instead of feeding raw data to the LLM, the engine will compute higher-order statistics:
    *   **Acute:Chronic Workload Ratio (A:C Ratio):** To predict injury risk over a 4-week rolling window.
    *   **Z-Scores & Deviations:** To establish a user's true baseline and flag meaningful deviations in HRV or Resting HR over a 90-day period.
*   **Artifact Generation:** Implement a tool (`generate_deep_historical_report`) that queries BigQuery, performs the statistical math via Pandas/NumPy in a background worker, and generates a rich Markdown/PDF artifact stored in GCS. The agent will read a summary and provide the user with a secure link to the full report.

### 2. The "AgentSearch" Protocol (Classroom of Agents)
Currently, our analytical metrics (like Aerobic Decoupling or GCT Drift) are hardcoded in `analytics.py`. SensorFM uses a "classroom of agents" to autonomously discover optimal downstream predictors.
*   **Dynamic Query Generation:** We will introduce a new tool (e.g., `execute_exploratory_query`) that allows the LLM to write, validate, and execute its own SQL against the BigQuery telemetry tables.
*   **Hypothesis Testing:** If a user asks a novel question ("Does my stride length drop when it's hotter than 25°C?"), the agent won't just say "I don't know." It will use AgentSearch to formulate the SQL, run it against the historical lake, and interpret the results.
*   **Self-Evolving Metrics:** The platform will log successful exploratory queries, effectively "learning" new ways to interpret the user's physiology over time without requiring manual developer updates to Python files.

### 3. Continuous Feedback Loop
Instead of filling missing data gaps (which requires the massive pretraining scale of models like SensorFM), we will implement a transparent feedback loop.
*   **Data Quality Awareness:** If the system detects a significant gap (e.g., missing sleep data), it will not attempt to guess or hallucinate the data.
*   **User Inquiry:** The proactive agent will ping the user via the `log_health_status` tool to manually input a subjective feeling (e.g., "I see you didn't wear your watch last night. How rested do you feel on a scale of 1-10?"), relying on the user's subjective input to bridge the gap safely.

## Proposed Phased Implementation Plan

### Phase 1: The Deep Reporting Engine (Completed ✅)
1.  Create `api/src/tools/deep_reporting.py`.
2.  Implement `generate_long_term_report` tool focusing on SQL aggregations (monthly averages, Z-scores) rather than row-by-row retrieval.
3.  Store outputs as artifacts in Google Cloud Storage and return a signed URL to the user, alongside an Executive Summary for the LLM context.
4.  Update `ROADMAP.md` Phase 4 to include this feature.

### Phase 2: AgentSearch (Dynamic SQL) (Completed ✅)
1.  Implement a safe, sandboxed BigQuery execution tool with read-only permissions.
    *   **Infrastructure Guardrail:** The `execute_exploratory_query` tool MUST use a dedicated Google Cloud Service Account with strictly `roles/bigquery.dataViewer` permissions. This guarantees that even if the LLM hallucinates a destructive query (e.g., DROP, DELETE), BigQuery will reject it at the IAM level.
2.  Add a `DataScientist` sub-agent node in our LangGraph orchestrator specifically trained on our BigQuery schema.
    *   **Prompt Guardrail:** Implement the following strict System Prompt for this sub-agent:
        ```text
        You are an Expert Data Scientist in BigQuery and Exercise Physiology.
        Your sole objective is to translate the analytical questions from the 'Biometric Coach' into precise and efficient SQL queries to extract insights from the user's historical data.
        
        🚨 STRICT SECURITY GUARDRAILS 🚨:
        1. USER ISOLATION (CRITICAL): All your queries MUST include the clause `WHERE user_id = '{current_user_id}'`. You are strictly forbidden from querying or grouping data from other users.
        2. READ-ONLY OPERATIONS (CRITICAL): You are only authorized to read data. NEVER generate queries containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, or `MERGE`. Only use `SELECT`.
        3. COST & EFFICIENCY:
           - The use of `SELECT *` is STRICTLY FORBIDDEN. You must explicitly list the required columns.
           - Always apply logical time limits (e.g., `WHERE date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)`) or use the `LIMIT` clause.
        4. SCHEMA FIDELITY: Do not hallucinate column names. Only build queries using the exact schema provided below:
           [DYNAMIC_SCHEMA_INJECTION]
        ```
3.  When a query requires deep historical correlation not covered by standard tools, the main agent delegates to the `DataScientist` to write and run the custom analysis.

### Phase 3: Continuous Feedback Loop (Current Focus 🚧)
1.  Update the proactive analysis script to detect missing critical data points (e.g., no sleep data recorded).
2.  Implement a trigger to request manual subjective input from the user to augment the missing objective data before scheduling the next workout.

## Verification & Rollback
*   **Verification:** Ensure custom SQL tools are strictly read-only to prevent data corruption. Test deep reporting tools with 1-year data subsets to measure latency and BigQuery costs.
*   **Rollback:** Disable the dynamic SQL tools via environment variables if prompt injection or excessive querying is detected. Revert to hardcoded `analytics.py` endpoints.
