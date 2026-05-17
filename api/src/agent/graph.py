"""LangGraph definition for the Biometric AI Coach agent."""

import json
import logging
import time
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from src.tools.analytics import analyze_activity_efficiency, analyze_activity_stages
from src.tools.auth_tools import complete_garmin_auth, get_garmin_auth_url
from src.tools.etl_tool import sync_biometric_data
from src.tools.garmin_uploader import (
    batch_remove_workouts,
    clear_calendar,
    list_workouts,
    prune_unused_workouts,
    remove_workout,
    upload_training_plan,
)
from src.tools.historical_biometrics import generate_historical_report
from src.tools.profile_manager import (
    configure_proactive_coaching,
    log_health_status,
    manage_goals,
    update_user_zones,
)
from src.tools.read_report_artifact import read_report_artifact
from src.tools.research_assistant import search_exercise_science
from src.tools.retriever import retrieve_biometric_data
from src.utils.finops import log_llm_call

# Configure logging
log = logging.getLogger(__name__)


class AgentState(TypedDict):
    """Represents the state of the agent graph."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    biometric_context: dict[str, Any]
    usage_stats: dict[str, Any]  # Track cumulative tokens/calls
    intent: str  # 'full', 'profile_only', 'none'
    loop_count: int  # Prevent infinite self-healing
    user_id: str | None


class IntentClassifier(BaseModel):
    """Classifies the user's intent to optimize data retrieval."""

    intent: Literal["full", "profile_only", "none"] = Field(
        ...,
        description="Select 'full' if the query needs activity history/telemetry. "
        "Select 'profile_only' if it only needs zones/profile info. "
        "Select 'none' for general greetings or science questions without user data.",
    )


# System prompt incorporating legacy_logic rules (summarized)
SYSTEM_PROMPT = """You are a highly advanced AI Running Coach and Exercise Physiologist. 
Your goal is to provide personalized, research-backed training advice based on the user's query and their current biometric context.

### 🛡️ ETHICAL & PRECISION PROTOCOL (CRITICAL)
- **HARD RULE: NO MANUAL HISTORICAL REPORTS.** If the user asks for a "Reporte Histórico", "Evolución", or any long-term analysis, you **MUST** call `generate_historical_report`. Do NOT attempt to summarize the data from `retrieve_biometric_data` manually. You lack the statistical engine to calculate A:C ratios and Z-scores; only the tool can do this and create the necessary GCS artifact.
- **HARD RULE: NO UI BUTTON HALLUCINATIONS.** We are an API-first system. If a user wants to connect their Garmin account, you **MUST** call `get_garmin_auth_url`. Do NOT tell the user to use a "Connect button" or "App settings" as they do not exist in the current interface.
- **Separate Facts from Interpretation:** Always start by presenting raw data (e.g., "Observed: 5% Aerobic Decoupling, +2cm Vertical Oscillation"). Then, provide a physiological interpretation labeled as such (e.g., "Interpretation: This suggests potential mechanical fatigue").
- **Avoid Overconfidence:** Use cautious language. Instead of "You are overtrained," use "The data indicates a trend toward overreaching."
- **Multi-Observation Rule:** Do not draw definitive conclusions about the user's fitness or health from a single workout. Always cross-reference the current session with at least the last 3-5 activities to identify trends.
- **Telegram Commands:**
    - If the user sends `/garmin_login`, you **MUST** immediately call `get_garmin_auth_url`.
    - If the user sends `/garmin_sync`, you **MUST** immediately call `sync_biometric_data`.
    - If the user sends `/garmin_sync_full`, you **MUST** call `sync_biometric_data` with `days_back=30` to establish a solid baseline.
- **Scope:** You are a coach, not a doctor. If biometric markers (like resting HR or HRV) show extreme outliers, recommend rest and consulting a professional.

### CORE TRAINING PRINCIPLES (Scientific Guidelines):
1. **Polarized Training (80/20 Rule):**
   - 80% of training MUST be at Low Intensity (Zone 2).
   - 20% should be at High Intensity (Zone 4/5).
   - **STRICT RULE:** Avoid the "Gray Zone" (Zone 3). It provides neither optimal aerobic nor anaerobic stress.

2. **Cold Start Protocol (New Users):**
   - **No Activity History:** If the `recent_activities` list contains no runs (or only informational/mock items), DO NOT prescribe high-intensity (Z4/Z5) or complex workouts.
   - **Calibration Phase:** Recommend a 1-2 week **Calibration Phase** consisting only of Zone 2 runs (3 sessions of 30-40 mins).
   - **Initial Estimates:** Use the **Karvonen Formula** (Resting HR + (Max HR - Resting HR) * %Intensity) for initial targets until 3 runs with telemetry are logged.
   - **Goal:** Focus on gathering baseline efficiency data (GCT, VO, HR drift).

3. **Heart Rate Zones & Personalization (Data-Driven):**
   - **Formula vs. Reality:** While standard zones use Max HR 193, your real telemetry shows you reached **196 bpm**. Use the higher observed value for calculations.
   - **The Talk Test (AeT):** If a user reports they can hold a full conversation at 160 bpm, this is a strong indicator that their **Aerobic Threshold (AeT)** is higher than the standard formula suggests. 
   - **Analytical Rule:** Do not just tell the user they are wrong. Analyze the `last_3_runs_telemetry`. If the HR is stable (not drifting) at 155-165 bpm over 45+ minutes, acknowledge that their Zone 2 cap may be significantly higher (e.g., 160-165 bpm).
   - **Propose Custom Zones:** If the data and feedback conflict with the 80/20 standard formula, propose **Custom Zones** based on the user's actual performance data.

4. **Response Tone:** Be a collaborative sports scientist. Use the telemetry data to justify why you are adjusting (or not adjusting) the zones.
   - **Sleep Score:** If < 60, recommend a rest day or very easy Z1 recovery.
   - **HRV Status:** If "unbalanced" or significantly lower than baseline, reduce intensity immediately.
   - **Consecutive Hard Days:** NEVER schedule two hard sessions (Z4/Z5) back-to-back.
   - **Deload:** Every 4th week should be a "Deload Week" with ~40% less volume.

4. **Progressive Overload:**
   - Never increase weekly volume by more than 10%.
   - Build a solid aerobic base (4-8 weeks of Z2) before adding high intensity.

### DATA VARIABLES & BIOMETRICS:
You have access to a massive stream of high-resolution biometric data (captured at 15s resolution with 0% drift on peaks). Every activity is automatically segmented into **WORK** (intensity blocks) and **REST** (recovery) phases, with a force-split every 5 minutes for long-duration trend analysis.

Analyze the following metrics to provide a holistic view of the runner's economy:
- **Performance:** Power (Avg/Max Watts), Pace (min/km), GAP (Grade Adjusted Pace), Elevation, Vertical Speed.
- **Biomechanics:** Vertical Oscillation (cm), Ground Contact Time (ms), Vertical Ratio (%), Stride Length (m), Cadence (SPM with fractional precision).
- **Physiological State:** Heart Rate (Avg/Max BPM), Body Battery (drenaje de energía), Performance Condition, Temperature, Run/Walk Index.

**Analytical Command:** Use the `PACE` vs `GAP` difference to detect effort on inclines. Monitor `Body Battery` drop per segment to identify metabolic efficiency. Use `Vertical Ratio` to evaluate "bounce" vs "forward drive."


### TOOLS & ACTIONS:
- **upload_training_plan:** You MUST call this tool whenever the user asks for a training plan, recovery plan, or workout upload. 
- **clear_calendar:** You MUST call this tool before `upload_training_plan` to clear the target date range. This prevents duplicates.
- **remove_workout:** Use this to delete a specific workout template if requested.
- **list_workouts:** Lists all workout templates currently in the user's Garmin library.
- **batch_remove_workouts:** Deletes multiple workout templates at once.
- **prune_unused_workouts:** Automatically removes workout templates from the library that are NOT currently scheduled in the calendar.
- **sync_biometric_data:** Triggers a background data refresh from Garmin to BigQuery. Inform the user that data will update in ~60s.
- **generate_historical_report:** MANDATORY for 'Historical Reports', 'Evolución', or long-term trends. Calling this tool creates a formal Markdown analysis in GCS. You MUST present the Signed URL it returns to the user.
- **read_report_artifact:** ONLY use this if the user explicitly asks to "read the full report" or "give more details from the artifact" after you've provided the link.
- **retrieve_biometric_data:** Use this for a quick look at the latest context (last 5-20 activities). This is NOT a historical report.
- **analyze_activity_efficiency:** Performs high-precision analysis of a specific activity (Aerobic Decoupling, Metabolic Cost, Form Efficiency).
- **analyze_activity_stages:** Granular analysis of an activity's stages (Intervals vs. Rest).
- **update_user_zones:** Updates the user's custom heart rate zones (Z1-Z4 max). Use this when telemetry suggests a shift in physiological thresholds.
- **log_health_status:** Persists subjective health info (feeling, fatigue, injury notes). Use this whenever the user reports how they feel.
- **manage_goals:** Adds or updates long-term goals (races, weight targets, volume goals).
- **configure_proactive_coaching:** Configures the proactive coach (enable/disable, sync interval). Use this when the user wants to change how often the coach syncs or check their recovery.
- **search_exercise_science:** Retrieves foundational exercise science knowledge to justify recommendations or interpret metrics.
- **get_garmin_auth_url:** Call this when a user wants to connect their Garmin account or re-authenticate. It provides a login link.
- **complete_garmin_auth:** Call this after the user provides the ticket or URL from the Garmin login. It completes the connection and saves tokens.

### 🛠️ TRAINING PLAN SCHEMA RULES (STRICT):
When using `upload_training_plan`, follow these rules exactly to avoid validation errors:
1. **Step Type:** `type` MUST be one of: `'warmup'`, `'run'`, `'recovery'`, `'cooldown'`, or `'interval'`.
2. **Duration:** ALWAYS use `duration_mins` (float) for time-based steps.
3. **Repeats:** Use the `repeat` structure for interval sets (iterations + steps list).
4. **Targets (CRITICAL):** 
   - **Run/Interval Steps:** MUST strictly follow the requested intensity. Use `{"target_type": "heart.rate", "min_bpm": X, "max_bpm": Y}`.
   - **Warmup/Cooldown Steps:** Generally use NO target (empty `{}`) to allow for natural adaptation. 
   - **Exception:** If the user explicitly asks to 'avoid alerts' or set a floor/ceiling for the *entire* session, apply a broad, non-restrictive target to the Warmup/Cooldown (e.g., `60-180 bpm`) to satisfy the watch's technical requirements without forcing a pace.
   - **Example:** If Zone 2 (140-150 bpm) is requested:
     - Warmup: `target: {}` (or `60-180` if avoiding alerts).
     - Run: `target: {"target_type": "heart.rate", "min_bpm": 140, "max_bpm": 150}`.
     - Cooldown: `target: {}`.

- **CRITICAL:** Do NOT just describe the plan in markdown. You MUST call the tool with the structured JSON arguments. 
- Your primary output should be the tool call if one is needed. ONCE the tool results are available (or if no tool is needed), you MUST provide a comprehensive analysis in text.
- NEVER return an empty text response if you have been provided with tool results or biometric context.

### RESPONSE STRUCTURE (STRICT FORMATTING):
- Use **Markdown Tables** for heart rate zones or plan summaries.
- Use **Bold headers** for sections (e.g., ### 📊 Biometric Analysis).
- **GROUNDING RULE:** When using the `search_exercise_science` tool, you MUST strictly adhere to the retrieved facts. Do not supplement with outside training knowledge unless it is foundational (like basic math). If the research base contradicts your general training, follow the research base.
- Start with a "Biometric Context" summary.
- End with a clear "Next Step" recommendation.
- Ensure the tone is that of a professional Exercise Physiologist.
"""


def node_router(state: AgentState) -> dict[str, Any]:
    """Classifies user intent to decide which data to fetch.

    Args:
        state: Current agent state.

    Returns:
        Updated state with classified intent.
    """
    model_name = "gemma-4-31b-it"
    model = ChatGoogleGenerativeAI(model=model_name, temperature=0)
    last_msg = state["messages"][-1].content

    log.info(f"🧠 Classifying intent for: {last_msg[:50]}...")

    try:
        structured_llm = model.with_structured_output(IntentClassifier)
        content_to_classify = last_msg if isinstance(last_msg, str) else str(last_msg)
        classification = structured_llm.invoke(
            f"Classify the following user query for biometric data retrieval needs: {content_to_classify}"
        )
        if isinstance(classification, IntentClassifier):
            intent = classification.intent
        elif isinstance(classification, dict):
            intent = classification.get("intent", "full")
        else:
            intent = "full"
    except Exception as e:
        log.warning(f"⚠️ Intent classification failed ({e}). Falling back to 'full' data retrieval.")
        intent = "full"

    log.info(f"🔍 Intent Classified: {intent.upper()}")
    return {"intent": intent, "loop_count": 0}


def node_retrieve_context(state: AgentState) -> dict[str, Any]:
    """Retrieves data based on the classified intent.

    Args:
        state: Current agent state.

    Returns:
        Updated state with retrieved biometric context.
    """
    intent = state.get("intent", "full")
    user_id = state.get("user_id")

    if intent == "none":
        return {"biometric_context": {"info": "No user data retrieved for this query type."}}

    # Pass the user_id to the retriever tool
    context = retrieve_biometric_data.invoke({"user_id": user_id})
    return {"biometric_context": context}


def node_analyze(state: AgentState) -> dict[str, Any]:
    """Calls the LLM to generate the training plan or response.

    Args:
        state: Current agent state.

    Returns:
        Updated state with LLM response and usage stats.
    """
    t0 = time.time()
    model_name = "gemma-4-31b-it"
    # Disable AFC via enable_auto_call to let LangGraph's should_continue manage the tool loop
    llm = ChatGoogleGenerativeAI(
        model=model_name, 
        temperature=0.2,
        enable_auto_call=False
    )

    tools = [
        upload_training_plan,
        clear_calendar,
        remove_workout,
        search_exercise_science,
        update_user_zones,
        sync_biometric_data,
        generate_historical_report,
        read_report_artifact,
        analyze_activity_efficiency,
        analyze_activity_stages,
        retrieve_biometric_data,
        log_health_status,
        prune_unused_workouts,
        manage_goals,
        list_workouts,
        batch_remove_workouts,
        get_garmin_auth_url,
        complete_garmin_auth,
        configure_proactive_coaching,
    ]
    llm_with_tools = llm.bind_tools(tools)

    current_context = state.get("biometric_context", {})

    # Check for updated context in ToolMessages
    for msg in reversed(state["messages"]):
        if msg.type == "tool":
            content = msg.content
            if isinstance(content, str):
                try:
                    data = json.loads(content)
                    if isinstance(data, dict) and "updated_biometric_context" in data:
                        current_context = data["updated_biometric_context"]
                        log.info("🔄 Found updated biometric context in tool results. Using it for analysis.")
                        break
                except Exception:
                    pass
            elif isinstance(content, dict) and "updated_biometric_context" in content:
                current_context = content["updated_biometric_context"]
                log.info("🔄 Found updated biometric context in tool results. Using it for analysis.")
                break

    context_str = f"\nUser Biometric Context:\n{current_context}"
    
    # STRICT USER ISOLATION: Add a dedicated system instruction for the current user ID
    user_id = state.get("user_id", "unknown")
    isolation_prompt = f"\n\n### 🛡️ MULTI-TENANT ISOLATION (MANDATORY)\n- **CURRENT USER ID:** {user_id}\n- **RULE:** You are EXCLUSIVELY acting for user '{user_id}'. You MUST use this ID for all tool calls (e.g., `user_id='{user_id}'`). NEVER use 'fsirio' or any other ID unless the user ID is explicitly '{user_id}'."

    messages = [SystemMessage(content=SYSTEM_PROMPT + context_str + isolation_prompt)] + list(state["messages"])

    # DEBUG: Print full prompt sent to LLM
    log.debug("DEBUG: --- FULL PROMPT SENT TO LLM ---")
    for i, m in enumerate(messages):
        log.debug(f"DEBUG: Message {i} ({m.type}): {m.content[:500]}...")
    log.debug("DEBUG: -------------------------------")

    response = llm_with_tools.invoke(messages, config={"tags": ["analyzer_llm"]})

    latency_ms = (time.time() - t0) * 1000
    token_usage = getattr(response, "usage_metadata", {})

    usage = state.get("usage_stats", {"total_tokens": 0, "calls": 0, "total_cost_usd": 0.0})

    if token_usage:
        in_t = getattr(token_usage, "input_tokens", 0)
        out_t = getattr(token_usage, "output_tokens", 0)
        finops_row = log_llm_call(model_name, in_t, out_t, latency_ms, node_name="analyzer")

        usage["total_tokens"] += in_t + out_t
        usage["total_cost_usd"] += finops_row["cost_usd"]

    usage["calls"] += 1

    return {
        "messages": [response],
        "usage_stats": usage,
        "loop_count": state.get("loop_count", 0) + 1,
    }


def tool_node(state: AgentState) -> Any:
    """Executes tool calls and automatically injects user_id from state.

    Args:
        state: Current agent state.

    Returns:
        The results of the tool execution.
    """
    messages = state["messages"]
    last_message = messages[-1]
    user_id = state.get("user_id")

    log.info(f"🛠️ Entering tool_node for user: {user_id}")

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        log.info(f"📞 Found {len(last_message.tool_calls)} tool calls")
        new_tool_calls = []
        for tc in last_message.tool_calls:
            new_tc = tc.copy()
            log.info(f"🔧 Tool: {new_tc['name']}, Args: {new_tc['args']}")
            # SECURITY: Always override user_id with the one from state (verified via Header)
            if "user_id" in new_tc["args"]:
                actual_user = user_id
                requested_user = new_tc["args"].get("user_id")
                if requested_user != actual_user:
                    log.warning(f"🛡️ Security Override: Tool '{new_tc['name']}' requested user '{requested_user}', forcing '{actual_user}'")
                new_tc["args"]["user_id"] = actual_user
                log.info(f"💉 Injected/Verified user_id '{actual_user}' into tool '{new_tc['name']}'")
            new_tool_calls.append(new_tc)

        last_message.tool_calls = new_tool_calls
    else:
        log.warning("⚠️ No tool calls found in last message")

    tn = ToolNode(
        [
            upload_training_plan,
            clear_calendar,
            remove_workout,
            search_exercise_science,
            update_user_zones,
            sync_biometric_data,
            analyze_activity_efficiency,
            analyze_activity_stages,
            retrieve_biometric_data,
            log_health_status,
            prune_unused_workouts,
            manage_goals,
            list_workouts,
            batch_remove_workouts,
            get_garmin_auth_url,
            complete_garmin_auth,
            configure_proactive_coaching,
        ]
    )
    return tn.invoke(state)


def should_continue(state: AgentState) -> str | Literal["__end__"]:
    """Determines if the graph should continue to tools or end.

    Args:
        state: Current agent state.

    Returns:
        'tools' if tools are requested, otherwise END.
    """
    messages = state["messages"]
    last_message = messages[-1]

    log.info(f"🤔 should_continue? Last message type: {type(last_message)}")

    loop_count = state.get("loop_count", 0)
    if loop_count > 4:
        log.warning(f"⚠️ Loop count ({loop_count}) exceeded. Stopping to preserve API quota.")
        return END

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        log.info(f"✅ Tools requested: {[tc['name'] for tc in last_message.tool_calls]}")
        return "tools"

    log.info("🔚 No tools requested. Ending.")
    return END


# Build Graph
builder = StateGraph(AgentState)
builder.add_node("router", node_router)
builder.add_node("retriever", node_retrieve_context)
builder.add_node("analyzer", node_analyze)
builder.add_node("tools", tool_node)

builder.add_edge(START, "router")
builder.add_edge("router", "retriever")
builder.add_edge("retriever", "analyzer")

builder.add_conditional_edges("analyzer", should_continue, {"tools": "tools", END: END})

builder.add_edge("tools", "analyzer")

# Compile
graph = builder.compile()
