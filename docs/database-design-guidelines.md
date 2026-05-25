# Database Design Guidelines: Firestore (OLTP) vs BigQuery (OLAP)

To establish a clear boundary between Firestore and BigQuery, we define these guidelines based on access patterns, mutability frequency, and the data's purpose within the agent ecosystem.

## 1. Choosing the Database

### Firestore (Transactional & State Layer / OLTP)
The source of truth for the real-time operational functioning of the system and agents.
*   **Access Pattern:** Point reads and writes by key (e.g., `user_id`, `session_id`, `memory_id`) with millisecond latency.
*   **Mutability:** High. Data requiring frequent updates, fast insertions, or logical deletes (JSON patches).
*   **Volume per Record:** Small (documents < 1MB).
*   **Lifecycle:** Dynamic. Represents the "now" or immediate context the LLM needs to consume at a glance.
*   **Concrete Examples:**
    *   **Semantic Memory (`user_memories`):** "Golden Nuggets" extracted by the agent that change or retire frequently.
    *   **Orchestration & State Flags (`user_profiles`):** Control states like `full_etl_synced`, session tokens, profile configurations, or notification preferences (e.g., Telegram chat ID).
    *   **Chat Session Context:** Immediate active conversation history before archiving.

### BigQuery (Analytical & Data Lake Layer / OLAP)
The source of truth for massive analysis, historical storage, and data intelligence.
*   **Access Pattern:** Massive queries (column scans), aggregations (SUM, AVG), temporal ordering, and multi-table joins. Not for individual document lookups in critical app flows.
*   **Mutability:** Low to zero (Append-Only). Data is inserted once (via ETL/Streaming) and remains immutable. UPDATE/DELETE operations are expensive and subject to strict quotas.
*   **Volume per Record:** Massive. Millions of rows of telemetry, logs, or time-series data.
*   **Lifecycle:** Permanent / Historical. Raw material for the DataScientist agent to calculate trends.
*   **Concrete Examples:**
    *   **Pure Biometric Telemetry:** Time-series of HRV, RHR, vertical oscillation, ground contact time, and activity metrics.
    *   **Historical Execution Logs:** Traceability of coach responses, token metrics, and performance logs for auditing or future fine-tuning.
    *   **Physiological Aggregation Tables:** Pre-calculated rolling averages (e.g., 21-day HRV baseline for Z-Score calculation).

## 2. Decision Matrix (Cheat Sheet)

| Criterion | Use Firestore? | Use BigQuery? |
| :--- | :--- | :--- |
| **Frequently updated/modified?** | Yes (Millisecond ops) | No (Updates penalize performance) |
| **Needed by LLM in every interaction?** | Yes (Low latency/cost) | No (Too slow/costly for concurrency) |
| **Required for statistical/historical calc?** | No (Breaks free tier scale) | Yes (Optimized for millions of rows) |
| **Control flag for async coordination?** | Yes (Ideal for state/semaphores)| No (Consistency/latency failures) |

## 3. Migration Strategy for Misaligned Components

If a component violates these guidelines (e.g., running `UPDATE` on BigQuery during a user request), follow this refactoring order:
1.  **Identify BQ DMLs:** Search for agent scripts or tools executing `UPDATE`, `MERGE`, or `DELETE` on BigQuery in real-time. These are priority candidates for Firestore.
2.  **Temporal Duplication (If applicable):** For data requiring both high operational availability and historical analysis (e.g., chat logs), write the operational state to Firestore and asynchronously export the immutable history to BigQuery.
3.  **Encapsulate in Tools:** Ensure agent tools (e.g., `save_semantic_memory`, `get_user_state`) hide the underlying DB logic. The agent only knows it is "saving state"; the tool handles the SDK efficiently.
