# Plan: Mitigating LLM Tool Hallucination & Flow Laziness

## Status: Pending Implementation

### Problem Statement
Gemini 3.1 Flash Lite, while extremely fast, occasionally hallucinations workflow completion. It provides conversational confirmation (e.g., "I've scheduled your workout") without actually emitting the required tool call (`upload_training_plan`), or it performs a different tool (like `sync_biometric_data`) and assumes the task is done.

### Proposed Solutions

#### 1. "Show, Don't Tell" Prompt Enforcement
Update the `HEAD_COACH_SYSTEM_PROMPT` to explicitly forbid conversational confirmation of actions before the tool has returned a success result.
- **Rule:** If an action tool (upload, sync, delete) is required, the agent must *only* emit the tool call in that turn.
- **Rule:** Success messages can only be generated in a subsequent turn after receiving a valid ToolMessage result (e.g., a Workout ID).

#### 2. Active Validation Guardrail
Enhance `node_validator` in `api/src/agent/graph.py` to detect discrepancies between LLM text and tool calls.
- **Logic:** Scan the LLM response for "completion keywords" (e.g., "agendado", "subido", "scheduled"). 
- **Check:** If keywords are present but the corresponding tool call is missing, trigger an internal retry with a corrective system message.

#### 3. Execution Specialization
If the above fails, implement a dedicated `Scheduler Node` that only receives the finalized plan text and has the sole responsibility of invoking the Garmin API, removing the "conversational choice" from the execution step.

---

### Implementation Tasks (For Tomorrow)
- [ ] Modify `api/src/agent/graph.py` to update the System Prompt.
- [ ] Implement the active check in `node_validator`.
- [ ] Test with a "Schedule a run" query to verify tool emission vs. conversational hallucination.
