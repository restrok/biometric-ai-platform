# Database Architecture & Storage Guidelines

The **Biometric AI Platform** utilizes a **Hybrid Lakehouse Architecture**, strictly decoupling low-latency transactional state (**Firestore OLTP**) from high-throughput time-series telemetry analytics & vector search (**BigQuery OLAP + BigQuery Vector Search**).

```
                        ┌──────────────────────────────────────────────┐
                        │             Biometric Data Stream            │
                        └──────────────────────┬───────────────────────┘
                                               │
           ┌───────────────────────────────────┼───────────────────────────────────┐
           ▼                                   ▼                                   ▼
┌───────────────────────────┐     ┌───────────────────────────┐     ┌───────────────────────────┐
│      Firestore (OLTP)     │     │      BigQuery (OLAP)      │     │  BigQuery Vector Store    │
├───────────────────────────┤     ├───────────────────────────┤     ├───────────────────────────┤
│ • User Profiles & HR Zones│     │ • Second-by-Second FIT    │     │ • Exercise Science Base   │
│ • Active Training Goals   │     │ • HRV & RHR Time Series   │     │ • gemini-embedding-001    │
│ • Semantic Memories       │     │ • 21-Day Baseline Rolling │     │ • VECTOR_SEARCH (COSINE)  │
│ • Session Tokens & State  │     │ • LLM FinOps Audit Logs   │     │ • 80/20 Polarized Knowledge│
└───────────────────────────┘     └───────────────────────────┘     └───────────────────────────┘
```

---

## 1. Transactional Storage Layer (Firestore OLTP)

Firestore handles real-time operational state requiring document-level ACID guarantees and fast lookup speeds.

### Key Collections:
- **`user_profiles/{user_id}`**: Stores user biological profiles, physiological HR zones, and latest health status logs.
- **`user_profiles/{user_id}/semantic_memories`**: Stores factual "golden nuggets" extracted by the memory extractor (`memory_type`, `memory_text`, `is_active`).
- **`user_profiles/{user_id}/calibration_markers`**: Stores custom physiological threshold overrides (e.g. `ac_ratio_red_line`, `hrv_sensitivity_index`).

---

## 2. Analytical & Vector Lakehouse Layer (BigQuery OLAP)

BigQuery stores immutable historical telemetry, second-by-second FIT activity streams, system audit logs, and vector embeddings for scientific RAG.

### Key Tables & Views:
- **`recent_activities`**: Aggregated workout telemetry (`duration_sec`, `distance_m`, `avg_hr`, `avg_power`, `user_id`, `date`).
- **`daily_physiology`**: Daily health metrics (`all_day_stress_avg`, `body_battery_end_of_day`, `resting_heart_rate`).
- **`hrv_history`**: Nightly HRV time series metrics.
- **`view_calculated_training_status`**: SQL-native analytical view computing rolling 7-day Acute and 28-day Chronic workload ratios (ACWR) dynamically via window functions.
- **`exercise_science_knowledge_base`**: Vector table queried by `search_exercise_science` tool using `VECTOR_SEARCH(..., distance_type => 'COSINE')` and `models/gemini-embedding-001`.
- **`finops_logs`**: Token consumption, latency, and USD cost tracking per agent execution.

---

## 3. Data Ingestion & ETL Resiliency

- **Incremental Delta Sync (`etl_job.py`)**: Fetches latest Garmin telemetry by querying `MAX(date)` in BigQuery to ingest only new activities.
- **Leak-Proof Staging Pipeline**: Temporary staging tables (`*_staging_*`) are managed inside a strict `try...finally` block to ensure immediate drop upon completion or failure.
- **Eventual Consistency**: Operates asynchronously with outbox pattern patterns, ensuring operational stability without distributed lock overhead.
