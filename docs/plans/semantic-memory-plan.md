# Semantic Conversation Memory Implementation Plan

## Background & Motivation
Currently, the agent operates as a "goldfish" regarding conversational context. While it retains hard metrics (zones, goals, telemetry), it forgets subjective user preferences, lifestyle constraints, and recurring conversational facts across sessions. Simply injecting raw chat history leads to context poisoning, high token costs, and hallucinations. We need a targeted, semantic memory system to build a long-term "Coach-Athlete" relationship.

## Scope & Impact
This plan outlines the architecture for a "Semantic Memory Engine" that extracts and persists high-level facts (Golden Nuggets) rather than conversational transcripts. This will impact the data storage layer (introducing Firestore), the LangGraph topology, and the context retrieval pipeline.

## Proposed Solution
We will implement an explicit extraction and retrieval loop using an OLTP database for low-latency state management:
1.  **Storage (Firestore):** Use Google Cloud Firestore (instead of BigQuery) to store `user_memories`. Firestore is an OLTP database, making it far superior for transactional, low-latency DML operations required for chat memory, avoiding BigQuery's quotas and streaming limitations.
2.  **Extraction (Decoupled Node):** Implement a dedicated `node_memory_extractor` in LangGraph. This node runs asynchronously or at the end of a cycle, analyzing the final user-assistant exchange to extract facts. This removes the cognitive load from the `analyzer` (Head Coach), preventing prompt dilution.
3.  **Retrieval & Conflict Resolution:** The retriever will fetch active memories and inject them into the system prompt *with their IDs* (e.g., `[ID: 123] Preference: Dislikes treadmills`). If the `node_memory_extractor` detects a change (e.g., "I run on treadmills now"), it uses the ID to issue an update or `retire_semantic_memory(123)` call.

### Firestore Schema (`user_memories` Collection)
*   `id` (Document ID)
*   `user_id` (String)
*   `memory_type` (String): e.g., 'preference', 'constraint', 'health_quirk', 'coaching_style'
*   `memory_text` (String): The actual fact.
*   `created_at` (Timestamp)
*   `updated_at` (Timestamp)
*   `is_active` (Boolean): Allows soft-deleting memories.
*   `source_session_id` (String): Traceability to the exact chat session/thread that generated the fact.
*   `confidence_score` (Float): To filter weak deductions or hallucinations if the extraction LLM changes in the future.

## Alternatives & Future Risks
*   **BigQuery (Rejected):** Initially considered, but BQ is an OLAP system. Frequent small inserts/updates for chat memory will lead to latency and quota issues.
*   **Context Window Saturation (Future Risk):** Currently, injecting all active memories is feasible. However, as the user interacts over months, injecting 100+ memories will eventually saturate the context window and dilute the prompt. *Future Mitigation:* We will eventually need semantic routing (e.g., using embeddings to inject only equipment preferences if the user asks about shoes).

## Phased Implementation Plan

### Phase 1: Infrastructure
*   Add `google-cloud-firestore` to `pyproject.toml`.
*   Create `api/src/utils/firestore.py` for client initialization and collection references.

### Phase 2: Tooling & Logic
*   Create `api/src/tools/memory_manager.py` containing tools for the extractor node:
    *   `save_semantic_memory(user_id, memory_type, memory_text, source_session_id, confidence_score)`
    *   `update_semantic_memory(memory_id, new_text)`
    *   `retire_semantic_memory(memory_id)`
*   Update `api/src/tools/retriever.py` to fetch active memories from Firestore and append them to the `biometric_context` dictionary, ensuring IDs are included.

### Phase 3: Agent Integration (LangGraph)
*   Create `node_memory_extractor` in `api/src/agent/graph.py`.
*   Draft a specialized system prompt for the extractor node focusing solely on identifying 'Golden Nuggets' and resolving conflicts with existing injected memories.
*   Add the extractor node to the LangGraph workflow, executing after the main `analyzer` or as a parallel branch, ensuring it has access to the memory management tools.

## Verification & Testing
1.  Run the API and trigger an interaction where a user states a new preference.
2.  Verify the `node_memory_extractor` runs, calls `save_semantic_memory`, and the document appears in Firestore.
3.  Trigger a subsequent interaction contradicting the preference. Verify the extractor uses the injected ID to call `update_semantic_memory` or `retire_semantic_memory`.