# Multi-User Architecture & Secret Management Plan

## Background & Motivation
The Biometric AI Platform currently operates as a single-user system, hardcoded to a specific Garmin account and user profile. The goal is to expand the platform to support multiple users (e.g., family members on the same local network) so they can access their own personalized AI Coach via the existing API.

## Scope & Impact
- **API Layer:** Must intercept a `X-User-ID` header to determine the context of the request.
- **Provider/SDK Layer:** Must dynamically fetch and use the correct Garmin authentication tokens per user.
- **Secret Management:** Tokens currently stored in local files (`garmin_tokens.json`) will be migrated to **Google Secret Manager**, ensuring secure, centralized credential storage.
- **Data Layer (BigQuery):** Existing tables (`user_profile`, `recent_activities`, etc.) need a `user_id` column to partition data per user.

## Proposed Solution
1.  **Identity:** Trust the internal network. Clients will pass `X-User-ID: <username>` (e.g., `fsirio`, `wife_username`) in HTTP headers.
2.  **Secret Management:** 
    - Enable Google Secret Manager API on the GCP project.
    - Store Garmin tokens as secrets named `garmin_tokens_<user_id>`.
    - Update `ProviderFactory` to fetch the secret payload from GCP instead of reading the local filesystem.
3.  **Data Isolation:** Add a `user_id` column to all BigQuery tables. The ETL jobs and Retriever tools will be updated to filter queries by `user_id`.

## Alternatives Considered
-   **Local Encrypted DB:** Considered for token storage to keep credentials local, but Google Secret Manager was chosen for better integration with the existing GCP stack and higher security.
-   **Static API Keys / JWT:** Considered for API authentication, but deemed overly complex for a trusted home network scenario where a simple `X-User-ID` header suffices.

## Phased Implementation Plan

### Phase 1: Database Migration
- Modify `init_profile_tables.py` to add a `user_id` (STRING) column to all tables.
- Create a migration script to backfill the existing single-user data with a default `user_id` (e.g., `fsirio`).

### Phase 2: Secret Manager Integration
- Create a utility script to upload local `garmin_tokens.json` to Google Secret Manager under the user's ID.
- Update `src/utils/provider_factory.py` to accept a `user_id` and fetch the corresponding secret from GCP.
- **Cost Optimization:** Ensure that when the Garmin SDK refreshes tokens and saves back to GCP, the previous secret version is explicitly destroyed to stay within the 6 active versions free-tier limit.

### Phase 3: API & Context Isolation
- Update `main.py` FastAPI app to extract `X-User-ID` from headers or requests.
- Pass `user_id` through the LangGraph state (`AgentState`).
- Update `retriever.py` tools to include `WHERE user_id = '{user_id}'` in all BigQuery queries.
- Update `etl_job.py` to accept a `user_id` and attach it to all uploaded DataFrames.

### Phase 4: Containerization & Deployment
- Create a `Dockerfile` in the `api/` directory using a Python 3.11 base image.
- Install the `uv` package manager.
- Install Playwright and its system dependencies (required for the Garmin SDK auth).
- Configure the entrypoint to run the FastAPI server via `uvicorn`.
- This ensures the API can be easily integrated into the existing `docker-compose` setup on the local server.

## Verification
-   **Unit Tests:** Mock Google Secret Manager to ensure the provider factory fetches correctly.
-   **Integration:** Send API requests with different `X-User-ID` headers and verify the retriever returns distinct user profiles and activities.
-   **ETL Test:** Run the ETL job for the new user and verify data lands in BigQuery tagged with their `user_id`.

## Migration & Rollback
-   **Rollback:** If Secret Manager fails, the system can temporarily revert to `find_token_file()` logic by checking for local files as a fallback. BigQuery schema changes (adding `user_id`) are non-destructive to existing queries if we default to the primary user when `user_id` is missing.