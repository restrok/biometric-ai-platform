# Universal Goals Feature Implementation Plan

## Objective
Implement a "Universal Goals" feature that persists user training goals (e.g., race targets, time objectives, volume targets) natively within the BigQuery Lakehouse. This ensures that any API consumer or AI agent has immediate, structured access to the user's long-term objectives without relying on volatile local memory.

## Key Files & Context
- `api/scripts/init_profile_tables.py`: Needs an update to create the new `user_goals` BigQuery table.
- `api/src/tools/profile_manager.py`: Needs new tools to add, update, and complete goals.
- `api/src/routers/tools.py`: Needs new REST endpoints for goal management.
- `api/src/tools/retriever.py`: Needs an update to fetch active goals and inject them into the LLM context.
- `docs/roadmap.md`: Needs to be updated to reflect this new planned feature.

## Implementation Steps

### 1. Database Schema
Update `api/scripts/init_profile_tables.py` to create a `user_goals` table with the following schema:
- `id` (STRING)
- `created_at` (TIMESTAMP)
- `target_date` (DATE)
- `goal_type` (STRING - e.g., 'race', 'volume', 'weight')
- `target_value` (STRING - e.g., '50:00', '100km', '75kg')
- `description` (STRING)
- `status` (STRING - 'active', 'completed', 'abandoned')

### 2. Tooling (Profile Manager)
Add a new `manage_goals` tool (or split into `add_goal` and `complete_goal`) in `api/src/tools/profile_manager.py` that interacts with the `user_goals` BigQuery table.

### 3. API Endpoints
Expose the new tools via REST in `api/src/routers/tools.py`:
- `POST /api/v1/tools/goals/add`
- `POST /api/v1/tools/goals/update`

### 4. Context Retrieval
Modify `api/src/tools/retriever.py` to query the `user_goals` table for `status = 'active'`. Append this data to the context payload returned to the LangGraph agent, ensuring the LLM always considers these goals when generating plans.

### 5. Roadmap Update
Add the "Universal Goals Feature" to Phase 4 (or Phase 3) in `docs/roadmap.md`.

## Verification & Testing
- Run `init_profile_tables.py` and verify the table creation in BigQuery.
- Call the `add_goal` endpoint/tool and ensure the record is inserted.
- Trigger `retrieve_biometric_data` and verify the active goals are included in the JSON output.
