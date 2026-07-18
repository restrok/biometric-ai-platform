# Biometric AI Platform: Engineering Standards

## 🌍 Language Standards
- **Source Code & Documentation:** All code, comments, documentation, and metadata MUST be in English.
- **Adaptive UX:** The AI Coach MUST adapt its response language to match the user's input. If the user speaks Spanish, respond in Spanish. If they speak English, respond in English.

## 🛡️ Security & Integrity
- **User Isolation:** Always verify `user_id` against the authenticated session. Never leak data between users.
- **Secret Management:** Never hardcode credentials. Use GCP Secret Manager (`src.utils.config`).
- **Action-over-Word Mandate:** Never assume or claim a task is complete based on text generation alone. Actions (uploads, syncs, deletes) MUST be verified by a tool response. Hallucinating success without emitting a tool call is a critical failure.

## 🧪 Engineering Excellence
- **Precision Analysis:** Use specific tools for deep historical analysis (`generate_deep_historical_report`) instead of manual summaries.
- **Data Scientist Loop:** For novel physiological questions, use the Data Scientist node to explore BigQuery directly.
- **Structured Outputs:** Prefer Pydantic schemas for agent-to-agent communication to minimize context bloat.
