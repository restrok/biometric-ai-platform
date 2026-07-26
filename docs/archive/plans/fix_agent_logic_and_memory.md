# 🛠️ Fix Plan: Agent Robustness & Systemic Data Integrity

> **Status:** 🚧 TO DO (Priority)

## 1. Problem: Sync Short-Circuiting
**Issue:** The `node_analyze` function in `api/src/agent/graph.py` checks the entire message history for a `sync_biometric_data` call. If found anywhere in the history, it returns a static "Sync already triggered" message, preventing users from syncing again in new turns.

**Solution:** Update the check to only count syncs since the *last human message*.

```python
# In api/src/agent/graph.py -> node_analyze
messages_since_human = []
for m in reversed(state["messages"]):
    if m.type == "human":
        break
    messages_since_human.append(m)

sync_triggered_this_turn = any(
    (msg.type == "tool" and msg.name == "sync_biometric_data")
    or (hasattr(msg, "tool_calls") and any(tc["name"] == "sync_biometric_data" for tc in msg.tool_calls))
    for msg in messages_since_human
)
```

## 2. Problem: Redundant Memory Extraction
**Issue:** The `memory_extractor` extracts useless facts like "Uses a Garmin device" from automated system responses.

**Solution:**
1. Update `MEMORY_EXTRACTOR_PROMPT` in `api/src/agent/prompts.py` to exclude sync/auth status.
2. Filter out automated AI responses in `node_memory_extractor`.

## 3. Problem: Stale Data & Cache Pollution
**Issue:** `retrieve_biometric_data` uses a 5-minute TTL cache. If a sync finishes in 30 seconds, the retriever still shows old data for the remaining 4.5 minutes.

**Solution:** 
- Add a `force_reload: bool = False` argument to `retrieve_biometric_data`.
- If `force_reload` is True, bypass `lru_cache`.
- The agent should automatically set `force_reload=True` if a sync was detected in the last 2 turns.

## 4. Problem: Discrepancy in A:C Ratio Calculations
**Issue:** The `Retriever` fetches a static table (often NULL), while the `Historical Report` calculates it on-the-fly from raw activities. This leads to the coach seeing "NULL" and hallucinating a value based on the "Red Line" limit.

**Solution:**
- **Unification:** Create `api/src/utils/physiology.py` to house the rolling A:C calculation.
- **Retriever Update:** Both `retrieve_biometric_data` and `generate_historical_report` must import and use this shared function to ensure 100% consistency.

## 5. Problem: Confusion between Calibration (Limits) and Metrics (Current)
**Issue:** The agent incorrectly reported the `ac_ratio_red_line` (1.45) as the *current* workload because the actual metric was missing.

**Solution:**
- **Schema Separation:** Update the prompt to strictly distinguish between `personal_calibration_profile` (Fixed Physiological Truths/Limits) and `training_status` (Live Volatile Metrics).
- **Validation Rule:** Add a system instruction: *"If a metric is NULL, state it is unknown. NEVER substitute a Calibration Marker value for a live metric."*

---
**Status:** Expanded Plan Drafted. Ready for implementation.
