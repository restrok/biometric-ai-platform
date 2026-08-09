from src.tools.alerting import check_proactive_alerts
from src.tools.nutrition_modeler import assess_glycogen_readiness

"""LangGraph definition for the Biometric AI Coach agent."""

import json
import logging
import os
import time
from collections.abc import Sequence
from typing import Annotated, Any, Literal, cast

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from scripts.list_models import list_available_models
from src.agent.prompts import (
    DATA_SCIENTIST_PROMPT,
    HEAD_COACH_SYSTEM_PROMPT,
    INJURY_PREVENTION_PROMPT,
    MEMORY_EXTRACTOR_PROMPT,
    METABOLIC_NUTRITION_AGENT_PROMPT,
    SLEEP_CIRCADIAN_PROMPT,
)
from src.tools.analytics import analyze_activity_efficiency, analyze_activity_stages
from src.tools.auth_tools import complete_garmin_auth, get_garmin_auth_url
from src.tools.data_scientist import execute_exploratory_query, execute_exploratory_query_dry_run, get_bigquery_schema
from src.tools.deep_reporting import generate_deep_historical_report
from src.tools.etl_tool import sync_biometric_data
from src.tools.garmin_uploader import (
    batch_remove_workouts,
    clear_calendar,
    list_workouts,
    prune_unused_workouts,
    remove_workout,
    upload_training_plan,
)
from src.tools.historical_biometrics import generate_historical_report, query_macro_load_history
from src.tools.memory_manager import retire_semantic_memory, save_semantic_memory, update_semantic_memory
from src.tools.predictive_modeler import project_training_impact
from src.tools.profile_manager import (
    configure_proactive_coaching,
    log_health_status,
    manage_goals,
    save_calibration_marker,
    update_user_zones,
)
from src.utils.llm_factory import get_chat_model

MODEL_NAME = os.getenv("CORE_MODEL_NAME", "gemini-3.1-flash-lite")
DS_MODEL_NAME = os.getenv("DS_MODEL_NAME", "gemini-pro")

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
    """Classifies the user's intent regarding biometric data needs."""

    intent: Literal[
        "none", "full", "activities", "sleep", "hrv", "nutrition", "sync", "planning", "discovery", "profile"
    ] = Field(
        ...,
        description="The type of biometric data needed to answer the query. "
        "Use 'sync' for commands like /garmin_sync. "
        "Use 'planning' for workout management or training plan uploads. "
        "Use 'discovery' for deep analysis, correlations, or custom SQL queries. "
        "Use 'profile' for settings, goals, or wellness logging. "
        "Use 'none' if the query is general chitchat.",
    )
    rationale: str = Field(..., description="Brief explanation of why this intent was chosen.")


# System prompt incorporating legacy_logic rules (summarized)
SYSTEM_PROMPT = """You are a highly advanced AI Running Coach and Exercise Physiologist, inspired by the latest research in Large Sensor Foundation Models (SensorFM).
Your goal is to provide personalized, research-backed training advice based on the user's query and their current biometric context.

### 🛡️ MANDATORY PRE-FLIGHT HEALTH SCAN (CRITICAL)
Before you prescribe ANY training plan or specific workout (using `upload_training_plan`), you MUST perform a holistic scan of the user's current physiological state:
1. **Objective Workload:** Check the current **Acute:Chronic (A:C) Ratio**. 
   - If A:C Ratio > 1.3: You are FORBIDDEN from prescribing high intensity. Suggest Zone 1/2 or rest.
   - If A:C Ratio > 1.5: You MUST recommend immediate deload or total rest.
2. **Nervous System Status:** Evaluate the latest **HRV Trend**. 
   - If HRV is "Declining" or "Unbalanced": Prioritize recovery sessions only.
3. **Subjective Wellness:** Check the latest **Health Logs** (Fatigue/Feeling).
   - If fatigue >= 7 or feeling <= 4: Override high-intensity requests with easy recovery.
4. **Data Recency:** If your biometric context is older than 24h or missing these markers, you MUST call `retrieve_biometric_data` or `generate_historical_report` BEFORE drafting the plan.

### 🛡️ ETHICAL & PRECISION PROTOCOL
- **HARD RULE: DEEP HISTORICAL ANALYSIS.** If the user asks for a "Reporte Histórico", "Evolución", or any analysis spanning 1-6 months, you **MUST** call `generate_deep_historical_report`. Do NOT attempt to summarize raw telemetry or multiple months of data manually. You lack the statistical engine to calculate rolling A:C ratios and Z-scores efficiently; only the tool can generate the high-fidelity GCS artifact required for deep insights.
- **HARD RULE: EXPLORATORY DATA SCIENCE.** If a user asks a novel physiological question that isn't covered by standard tools (e.g., "Does my sleep quality correlate with my running pace?"), use `get_bigquery_schema` to understand the data lake and then `execute_exploratory_query` to find the answer. You are a "Data Scientist" as much as a coach.
    - **DRY RUN MANDATE (SRE):** You MUST call `execute_exploratory_query_dry_run` before any actual execution. Review the `estimated_bytes_processed`. If the scan is high (e.g., >100MB), you MUST optimize the query using partitions (e.g., `_PARTITIONTIME` or `date` filters) before running the real query.
    - **PCP AUDIT:** Periodically audit historical data to find "Failure Events" (injuries/exhaustion) vs "Adaptation Peaks". Use `save_calibration_marker` to persist these personal limits (e.g., "Personal Red Line: 1.55 AC Ratio").
    - **HOLISTIC VIEW:** Always cross-reference training load with `daily_physiology` (all-day stress, RHR). If a user has high life stress but low training load, recommend recovery anyway.
- **HARD RULE: SUBJECTIVE HEALTH PRIORITY.** If the user asks about symptoms (e.g., headaches, migraines, pain), you MUST prioritize analyzing `latest_health_status` and `semantic_memories` (like MRI reports or nutritional logs) BEFORE discussing running mechanics. Your mission is to bridge the gap between technical metrics (HRV/GCT) and physical wellbeing.
- **HARD RULE: NO UI BUTTON HALLUCINATIONS.**
 We are an API-first system. If a user wants to connect their Garmin account, you **MUST** call `get_garmin_auth_url`. Do NOT tell the user to use a "Connect button" or "App settings" as they do not exist in the current interface.
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
- **Physiological State:** Heart Rate (Avg/Max BPM), Body Battery (energy drain), Performance Condition, Temperature, Run/Walk Index.

**Analytical Command:** Use the `PACE` vs `GAP` difference to detect effort on inclines. Monitor `Body Battery` drop per segment to identify metabolic efficiency. Use `Vertical Ratio` to evaluate "bounce" vs "forward drive."


### 🌍 LANGUAGE ### RESPONSE STRUCTURE (STRICT FORMATTING): RESPONSE PROTOCOL (CRITICAL)
- **ADAPTIVE RESPONSE:** You MUST always respond in the same language the user is speaking. If the user speaks Spanish, respond in Spanish. If the user switches to English, you MUST switch to English immediately.
- **TECHNICAL STANDARD:** While your responses adapt to the user, all internal thought processes, tool logs, and repository-bound metadata must remain in English.

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
    # HARDCODED OVERRIDES: Ensure critical commands never fail due to model confusion or bad memory
    last_message = state["messages"][-1].content
    last_msg_str = last_message.lower() if isinstance(last_message, str) else str(last_message).lower()

    sync_commands = ["/garmin_sync", "/garmin_sync_full", "/garmin_login", "sync garmin"]
    if any(cmd in last_msg_str for cmd in sync_commands):
        log.info(f"🎯 Hardcoded Override: SYNC intent detected for command: {last_msg_str}")
        return {
            "intent": "sync",
            "loop_count": 0,
            "usage_stats": {"router_rationale": f"Hardcoded override for {last_msg_str}"},
        }

    # Forcefully disable AFC in the SDK to let LangGraph manage tool execution
    model = get_chat_model(
        model_name=MODEL_NAME,
        temperature=0,
        model_kwargs={"automatic_function_calling": {"disable": True}},
    )
    last_msg = state["messages"][-1].content
    current_user_id = state.get("user_id", "unknown")

    log.info(f"🧠 Classifying intent for: {last_msg[:50]}...")

    try:
        structured_llm = model.with_structured_output(IntentClassifier)
        content_to_classify = last_msg if isinstance(last_msg, str) else str(last_msg)

        # Enhanced prompt to detect cross-user queries and out-of-scope requests
        prompt = (
            f"Current User Session: {current_user_id}\n\n"
            f"Analyze this query: '{content_to_classify}'\n"
            "1. Determine what biometric data is needed.\n"
            f"2. SECURITY CHECK: Is the user asking about anyone OTHER than '{current_user_id}'? "
            "If they mention other names (e.g., 'Mercedes', 'John', 'another user'), classify intent as 'none' "
            "and state 'Security: Cross-user query detected' in the rationale.\n"
            "3. SCOPE CHECK: Is the query related to running, exercise physiology, health, or biometric data? "
            "If it's about coding (e.g., Python, Javascript), general world knowledge, math, or anything unrelated "
            "to being a professional running coach, classify intent as 'none' and state 'Scope: Out-of-scope request' in the rationale."
        )

        classification = structured_llm.invoke(prompt)

        if isinstance(classification, IntentClassifier):
            intent = classification.intent
            rationale = classification.rationale
        elif isinstance(classification, dict):
            intent = classification.get("intent", "full")
            rationale = classification.get("rationale", "No rationale provided")
        else:
            intent = "full"
            rationale = "Fallback to full"

        # Explicit override if the LLM missed it but the rationale mentions it
        if "cross-user" in rationale.lower() or "security" in rationale.lower():
            intent = "none"

    except Exception as e:
        log.warning(f"⚠️ Intent classification failed ({e}). Falling back to 'full' data retrieval.")
        intent = "full"
        rationale = f"Error during classification: {e}"

    log.info(f"🔍 Intent Classified: {intent.upper()} | Rationale: {rationale}")

    # Store the rationale in metadata for the analyzer
    return {"intent": intent, "loop_count": 0, "usage_stats": {"router_rationale": rationale}}


def node_retrieve_context(state: AgentState) -> dict[str, Any]:
    """Retrieves data based on the classified intent.

    Args:
        state: Current agent state.

    Returns:
        Updated state with retrieved biometric context.
    """
    intent = state.get("intent", "full")
    user_id = state.get("user_id")

    if not user_id:
        log.error("❌ No user_id found in state. Context retrieval aborted.")
        return {"biometric_context": {"error": "Authentication required."}}

    # OPTIMIZATION: For sync, profile, and planning, we don't need BigQuery history.
    # For SYNC, we provide NO context to prevent the model from getting chatty/analytical.
    if intent == "sync":
        log.info("⚡ Zero-context retrieval for SYNC intent.")
        return {"biometric_context": {"info": "Sync in progress. No analysis needed."}}

    if intent in ["profile", "planning"]:
        log.info(f"⚡ Lightweight retrieval for intent: {intent.upper()}")
        from src.utils.firestore import get_user_profile

        try:
            profile = get_user_profile(user_id)
            context = {
                "user_profile": profile,
                "latest_health_status": profile.get("latest_health_status"),
                "active_goals": profile.get("active_goals", []),
                "info": f"Lightweight context retrieved for {intent} intent.",
            }
            return {"biometric_context": context}
        except Exception as e:
            log.warning(f"❌ Lightweight retrieval failed: {e}. Falling back to full.")

    # Force reload logic: if a sync was triggered in the last 2 turns, bypass cache
    force_reload = False
    for msg in reversed(state["messages"]):
        if (msg.type == "tool" and msg.name == "sync_biometric_data") or (
            hasattr(msg, "tool_calls") and any(tc["name"] == "sync_biometric_data" for tc in msg.tool_calls)
        ):
            log.info("🔄 Recent sync detected in message history. Forcing reload of biometric context.")
            force_reload = True
            break

    # Pass the user_id, force_reload, limit=5, and on-demand telemetry to the retriever tool for context
    include_telemetry = intent in ["activities", "discovery"]
    context = retrieve_biometric_data.invoke(
        {
            "user_id": user_id,
            "force_reload": force_reload,
            "limit": 5,
            "include_telemetry": include_telemetry,
        }
    )
    return {"biometric_context": context}


def node_injury_prevention(state: AgentState) -> dict[str, Any]:
    """Specialized node for injury risk analysis."""
    log.info("🛡️ Injury Prevention Agent scanning biometrics...")
    model = get_chat_model(
        model_name=MODEL_NAME,
        temperature=0,
        model_kwargs={"automatic_function_calling": {"disable": True}},
    )

    context = state.get("biometric_context", {})
    context_str = f"User Biometric Context:\n{json.dumps(context, indent=2)}"

    # Filter state messages to include only standard types that the model supports
    # and strictly pass them as standard LangChain messages
    input_messages: list[BaseMessage] = [
        SystemMessage(content=INJURY_PREVENTION_PROMPT),
        SystemMessage(content=context_str),
    ]

    # Only pass the last Human message to avoid polluting with previous agent reports
    for m in reversed(state["messages"]):
        if m.type == "human":
            input_messages.append(HumanMessage(content=m.content))
            break

    response = model.invoke(input_messages)
    # Wrap the response as a hidden internal report
    report_msg = SystemMessage(
        content=f"--- INTERNAL INJURY RISK REPORT ---\n{response.content}\n----------------------------------"
    )

    return {"messages": [report_msg]}


def node_sleep_recovery(state: AgentState) -> dict[str, Any]:
    """Specialized node for sleep and recovery analysis."""
    log.info("🧬 Sleep & Circadian Agent analyzing recovery...")
    model = get_chat_model(
        model_name=MODEL_NAME,
        temperature=0,
        model_kwargs={"automatic_function_calling": {"disable": True}},
    )

    context = state.get("biometric_context", {})
    context_str = f"User Biometric Context:\n{json.dumps(context, indent=2)}"

    input_messages: list[BaseMessage] = [
        SystemMessage(content=SLEEP_CIRCADIAN_PROMPT),
        SystemMessage(content=context_str),
    ]

    # Include the latest reports from other agents if available
    for m in state["messages"]:
        if "--- INTERNAL INJURY RISK REPORT ---" in str(m.content):
            input_messages.append(SystemMessage(content=str(m.content)))

    # Only pass the last Human message
    for m in reversed(state["messages"]):
        if m.type == "human":
            input_messages.append(HumanMessage(content=m.content))
            break

    response = model.invoke(input_messages)
    report_msg = SystemMessage(
        content=f"--- INTERNAL SLEEP & RECOVERY REPORT ---\n{response.content}\n----------------------------------"
    )

    return {"messages": [report_msg]}


def node_metabolic_nutrition(state: AgentState) -> dict[str, Any]:
    """Specialized node for metabolic nutrition analysis."""
    log.info("⚖️ Metabolic Nutrition Agent calculating fueling needs...")
    model = get_chat_model(
        model_name=MODEL_NAME,
        temperature=0,
        model_kwargs={"automatic_function_calling": {"disable": True}},
    )

    context = state.get("biometric_context", {})
    context_str = f"User Biometric Context:\n{json.dumps(context, indent=2)}"

    input_messages: list[BaseMessage] = [
        SystemMessage(content=METABOLIC_NUTRITION_AGENT_PROMPT),
        SystemMessage(content=context_str),
    ]

    # Include reports from other agents for full context
    for m in state["messages"]:
        if any(
            marker in str(m.content)
            for marker in [
                "--- INTERNAL INJURY RISK REPORT ---",
                "--- INTERNAL SLEEP & RECOVERY REPORT ---",
            ]
        ):
            input_messages.append(SystemMessage(content=str(m.content)))

    # Pass the last Human message
    for m in reversed(state["messages"]):
        if m.type == "human":
            input_messages.append(HumanMessage(content=m.content))
            break

    response = model.invoke(input_messages)
    report_msg = SystemMessage(
        content=f"--- INTERNAL METABOLIC & FUELING REPORT ---\n{response.content}\n----------------------------------"
    )

    return {"messages": [report_msg]}


def node_analyze(state: AgentState) -> dict[str, Any]:
    """Calls the LLM to generate the training plan or response.

    Args:
        state: Current agent state.

    Returns:
        Updated state with LLM response and usage stats.
    """
    t0 = time.time()
    # Forcefully disable AFC in the SDK to let LangGraph manage tool execution
    llm = get_chat_model(
        model_name=MODEL_NAME,
        temperature=0.2,
        model_kwargs={"automatic_function_calling": {"disable": True}},
    )

    intent = state.get("intent", "full")

    # SYNC OPTIMIZATION: Short-circuit or restrict tools for the sync intent
    if intent == "sync":
        last_message = state["messages"][-1].content
        last_msg_str = last_message.lower() if isinstance(last_message, str) else str(last_message).lower()

        # 1. Check for Login Command
        if "/garmin_login" in last_msg_str:
            log.info("🔑 Login command detected. Restricting tools to Auth.")
            tools = [get_garmin_auth_url, complete_garmin_auth]
        else:
            messages_since_human = []
            for msg in reversed(state["messages"]):
                if msg.type == "human":
                    break
                messages_since_human.append(msg)

            sync_triggered = any(
                (msg.type == "tool" and msg.name == "sync_biometric_data")
                or (hasattr(msg, "tool_calls") and any(tc["name"] == "sync_biometric_data" for tc in msg.tool_calls))
                for msg in messages_since_human
            )
            if sync_triggered:
                log.info("🏁 Sync already triggered. Returning static confirmation.")
                from langchain_core.messages import AIMessage

                confirm_text = "🔄 Tu Garmin Sync ha comenzado en segundo plano. "
                if "/garmin_sync_full" in last_msg_str:
                    confirm_text = "🔄 Tu Sincronización COMPLETA (30 días) ha comenzado. "

                return {
                    "messages": [
                        AIMessage(
                            content=confirm_text
                            + "Los datos actualizados estarán listos en unos 30-60 segundos. Mientras tanto, ¿en qué más puedo ayudarte?"
                        )
                    ],
                    "usage_stats": state.get("usage_stats", {}),
                    "loop_count": state.get("loop_count", 0) + 1,
                }

            # 3. First pass for sync (Normal or Full)
            log.info("🔄 Sync command detected. Restricting tools to Sync.")
            tools = [sync_biometric_data]
    else:
        tools = [
            upload_training_plan,
            clear_calendar,
            remove_workout,
            search_exercise_science,
            update_user_zones,
            sync_biometric_data,
            generate_historical_report,
            query_macro_load_history,
            check_proactive_alerts,
            assess_glycogen_readiness,
            generate_deep_historical_report,
            execute_exploratory_query,
            execute_exploratory_query_dry_run,
            get_bigquery_schema,
            read_report_artifact,
            analyze_activity_efficiency,
            analyze_activity_stages,
            retrieve_biometric_data,
            log_health_status,
            prune_unused_workouts,
            manage_goals,
            save_calibration_marker,
            project_training_impact,
            list_workouts,
            batch_remove_workouts,
            get_garmin_auth_url,
            complete_garmin_auth,
            configure_proactive_coaching,
            list_available_models,
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
    intent = state.get("intent", "full")
    isolation_prompt = f"\n\n### 🛡️ MULTI-TENANT ISOLATION (MANDATORY)\n- **CURRENT USER ID:** {user_id}\n- **RULE:** You are EXCLUSIVELY acting for user '{user_id}'. You MUST use this ID for all tool calls (e.g., `user_id='{user_id}'`). NEVER use 'fsirio' or any other ID unless the user ID is explicitly '{user_id}'."

    # SYNC OPTIMIZATION: If intent is sync, add a high-priority instruction
    sync_instruction = ""
    if intent == "sync":
        last_message = state["messages"][-1].content
        last_msg_str = last_message.lower() if isinstance(last_message, str) else str(last_message).lower()

        if "/garmin_login" in last_msg_str:
            sync_instruction = "\n\n### 🔑 LOGIN COMMAND DETECTED\n- **REQUIRED ACTION:** Call `get_garmin_auth_url` immediately with user_id. Do NOT ask for credentials or provide analysis."
        elif "/garmin_sync_full" in last_msg_str:
            sync_instruction = "\n\n### 🔄 FULL SYNC COMMAND DETECTED\n- **REQUIRED ACTION:** Call `sync_biometric_data` with `days_back=30` and user_id.\n- **REQUIRED RESPONSE:** Inform the user that a FULL 30-day sync has been triggered in the background. It will take ~60 seconds."
            messages_since_human = []
            for msg in reversed(state["messages"]):
                if msg.type == "human":
                    break
                messages_since_human.append(msg)

            sync_triggered = any(
                (msg.type == "tool" and msg.name == "sync_biometric_data")
                or (hasattr(msg, "tool_calls") and any(tc["name"] == "sync_biometric_data" for tc in msg.tool_calls))
                for msg in messages_since_human
            )
            if not sync_triggered:
                sync_instruction = "\n\n### 🔄 SYNC COMMAND DETECTED\n- **REQUIRED ACTION:** Call `sync_biometric_data` immediately with user_id.\n- **REQUIRED RESPONSE:** Inform the user that the Garmin sync has been triggered."
            else:
                sync_instruction = "\n\n### ✅ SYNC ALREADY TRIGGERED\n- **INSTRUCTION:** You have already triggered the sync. Provide the final confirmation message now."

    # Filter out system error messages and automated memory extraction messages from history
    history = [
        m
        for m in state["messages"]
        if "CRITICAL SYSTEM ERROR" not in str(m.content)
        and not getattr(m, "additional_kwargs", {}).get("is_memory_extraction")
    ]

    # Keep at most last 8 messages in conversational history to prevent context explosion
    if len(history) > 8:
        history = history[-8:]

    messages = [
        SystemMessage(content=HEAD_COACH_SYSTEM_PROMPT + context_str + isolation_prompt + sync_instruction)
    ] + history

    # DEBUG: Print full prompt sent to LLM
    log.debug("DEBUG: --- FULL PROMPT SENT TO LLM ---")
    for i, m in enumerate(messages):
        log.debug(f"DEBUG: Message {i} ({m.type}): {m.content[:500]}...")
    log.debug("DEBUG: -------------------------------")

    response = llm_with_tools.invoke(messages, config={"tags": ["analyzer_llm"]})

    latency_ms = (time.time() - t0) * 1000
    # Robust token extraction from response metadata
    in_t = 0
    out_t = 0
    usage_meta = getattr(response, "usage_metadata", None)
    if usage_meta:
        if isinstance(usage_meta, dict):
            in_t = usage_meta.get("input_tokens", 0)
            out_t = usage_meta.get("output_tokens", 0)
        else:
            in_t = getattr(usage_meta, "input_tokens", 0)
            out_t = getattr(usage_meta, "output_tokens", 0)

    # Fallback to response_metadata (OpenAI-compatible)
    if not in_t and not out_t:
        resp_meta = getattr(response, "response_metadata", None)
        if isinstance(resp_meta, dict):
            token_usage = resp_meta.get("token_usage")
            if isinstance(token_usage, dict):
                in_t = token_usage.get("prompt_tokens", 0)
                out_t = token_usage.get("completion_tokens", 0)

    usage = state.get("usage_stats", {})
    if not isinstance(usage, dict):
        usage = {}

    # Ensure keys exist
    usage.setdefault("total_tokens", 0)
    usage.setdefault("calls", 0)
    usage.setdefault("total_cost_usd", 0.0)

    if in_t or out_t:
        finops_row = log_llm_call(MODEL_NAME, in_t, out_t, latency_ms, node_name="analyzer")

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
                    log.warning(
                        f"🛡️ Security Override: Tool '{new_tc['name']}' requested user '{requested_user}', forcing '{actual_user}'"
                    )
                new_tc["args"]["user_id"] = actual_user
                log.info(f"💉 Injected/Verified user_id '{actual_user}' into tool '{new_tc['name']}'")
            new_tool_calls.append(new_tc)

        last_message.tool_calls = new_tool_calls
    else:
        log.warning("⚠️ No tool calls found in last message")

    return ToolNode(
        [
            upload_training_plan,
            clear_calendar,
            remove_workout,
            search_exercise_science,
            update_user_zones,
            sync_biometric_data,
            generate_historical_report,
            query_macro_load_history,
            check_proactive_alerts,
            assess_glycogen_readiness,
            generate_deep_historical_report,
            execute_exploratory_query,
            execute_exploratory_query_dry_run,
            get_bigquery_schema,
            analyze_activity_efficiency,
            analyze_activity_stages,
            retrieve_biometric_data,
            log_health_status,
            save_calibration_marker,
            project_training_impact,
            prune_unused_workouts,
            manage_goals,
            list_workouts,
            batch_remove_workouts,
            get_garmin_auth_url,
            complete_garmin_auth,
            configure_proactive_coaching,
            save_semantic_memory,
            update_semantic_memory,
            retire_semantic_memory,
            list_available_models,
        ]
    )


class DataScientistOutput(BaseModel):
    hypothesis: str = Field(..., description="The physiological or statistical hypothesis investigated.")
    query_executed: str = Field(..., description="The final optimized SQL string that passed the Dry Run.")
    pattern_detected: bool = Field(..., description="True if data validated the hypothesis; False otherwise.")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Statistical confidence level.")
    raw_findings: str = Field(..., description="Technical summary of the resulting data.")
    recommended_action: str = Field(..., description="Direct recommendation for the Head Coach.")
    metric_type: Literal["hrv_stress", "aerobic_decoupling", "rhr_trend", "workload_anomaly", "other"]


def node_data_scientist(state: AgentState) -> dict[str, Any]:
    """Specialized node for autonomous physiological hypothesis testing."""
    log.info("🧪 DataScientist node activated for autonomous discovery...")
    user_id = state.get("user_id", "unknown")

    # Instantiate specialized LLM for Data Science
    llm = get_chat_model(
        model_name=DS_MODEL_NAME,
        temperature=0,
        model_kwargs={"automatic_function_calling": {"disable": True}},
    )

    # PRE-FETCH SCHEMA: Inject schema immediately to save one iteration
    bq_schema = ""
    try:
        bq_schema = get_bigquery_schema.invoke({})
        schema_info = f"\n\n### 🗺️ BIGQUERY DATABASE SCHEMA\n{bq_schema}"
    except Exception as e:
        log.warning(f"⚠️ Failed to pre-fetch BQ schema: {e}")
        schema_info = ""

    # Bind DS tools - Optimization: remove get_bigquery_schema if we already have it
    active_ds_tools = [execute_exploratory_query_dry_run, execute_exploratory_query]
    if not bq_schema:
        active_ds_tools.append(get_bigquery_schema)

    llm_with_tools = llm.bind_tools(active_ds_tools)

    # Context preparation
    loop_count = state.get("loop_count", 0)
    strict_instruction = ""
    if loop_count > 1:
        strict_instruction = "\n\n### ⚠️ STRICT LOOP CONTROL\nYou have already attempted discovery. You MUST NOT call any more tools. You MUST synthesize your final findings and provide the DataScientistOutput now."
    elif bq_schema:
        strict_instruction = "\n\n### 🛡️ SCHEMA ALREADY PROVIDED\nThe BigQuery schema is included below. DO NOT call `get_bigquery_schema`. Proceed directly to formulating your hypothesis and then use the dry-run tool."

    # Context preparation - LEAN CONTEXT for Data Scientist
    raw_context = state.get("biometric_context", {})

    lean_context = {
        "latest_health_status": raw_context.get("latest_health_status"),
        "user_profile": raw_context.get("user_profile"),
        "daily_physiology_7d": raw_context.get("daily_physiology_7d"),  # Essential Stress/Battery trends
        "training_status": raw_context.get("training_status"),
        "semantic_memories": raw_context.get("semantic_memories"),
        "info": "Lean context provided for hypothesis formulation. Full telemetry available via BigQuery tools.",
    }

    context_str = json.dumps(lean_context, default=str)
    messages: list[BaseMessage] = [
        SystemMessage(
            content=DATA_SCIENTIST_PROMPT + f"\n\n### 🛡️ USER SESSION: {user_id}" + strict_instruction + schema_info
        )
    ]
    messages.append(HumanMessage(content=f"Biometric Context (Filtered): {context_str}"))
    messages.append(state["messages"][-1])

    # Initial call to formulate hypothesis and potentially call tools
    # LOOP BREAKER: If we are already at the limit, do not allow more tool calls
    if loop_count >= 2:
        log.warning("⚠️ Loop limit reached in node_data_scientist. Forcing structured output pass.")
        response = HumanMessage(content="Loop limit reached. Synthesize findings now.")
    else:
        response = llm_with_tools.invoke(messages)

    # If the DS wants to use tools, we return them to the 'tools' node
    if hasattr(response, "tool_calls") and response.tool_calls:
        log.info(f"🧪 DataScientist calling {len(response.tool_calls)} tools for discovery.")
        # Mark this AI message to identify its tools in the router
        response.additional_kwargs["is_ds_call"] = True
        return {"messages": [response], "loop_count": loop_count + 1}

    # Once tools are done (or if no tools needed), force a structured output
    structured_llm = llm.with_structured_output(DataScientistOutput)
    try:
        raw_output = structured_llm.invoke(messages + [response])
        if not raw_output:
            raise ValueError("No output from Data Scientist LLM")

        final_findings = cast(DataScientistOutput, raw_output)
        findings_msg = SystemMessage(
            content=f"🧪 DATA SCIENTIST REPORT:\n{json.dumps(final_findings.model_dump(), indent=2)}",
            additional_kwargs={"is_ds_report": True},
        )
        log.info("🧪 DataScientist generated structured report.")
        return {"messages": [findings_msg], "loop_count": loop_count + 1}
    except Exception as e:
        log.error(f"❌ DataScientist failed to generate structured report: {e}")
        return {"messages": [response], "loop_count": loop_count + 1}


def node_validator(state: AgentState) -> dict[str, Any]:
    """Validates the output of the analyzer to ensure physiological accuracy and formatting."""
    last_msg = state["messages"][-1]
    text = str(last_msg.content).lower()
    log.info("🧐 Validator node reviewing response...")

    # --- 1. Discrepancy Detection (Hallucination Guardrail) ---
    action_keywords = ["agendado", "subido", "scheduled", "sincronizado", "synced", "borrado", "deleted"]
    has_action_text = any(kw in text for kw in action_keywords)
    has_tool_calls = hasattr(last_msg, "tool_calls") and bool(last_msg.tool_calls)

    if has_action_text and not has_tool_calls:
        log.warning("🚫 DISCREPANCY DETECTED: Agent claimed an action but didn't emit a tool call.")
        error_msg = SystemMessage(
            content="CRITICAL SYSTEM ERROR: You claimed to have performed an action (scheduled/synced/deleted) in your text response, but you DID NOT emit the required tool call. This is a hallucination. You MUST emit the tool call (e.g., upload_training_plan) and DO NOT confirm the action in text until the tool has executed. Please try again."
        )
        return {"messages": [error_msg], "loop_count": state.get("loop_count", 0) + 1}

    # --- 2. Brevity Check ---
    if len(text) < 100 and "artifact_uri" not in text:
        log.warning("⚠️ Response seems too brief. Requesting elaboration.")

    return {"loop_count": state.get("loop_count", 0)}


def node_memory_extractor(state: AgentState) -> dict[str, Any]:
    """Dedicated node to extract 'Golden Nuggets' from the interaction."""
    log.info("🧠 Semantic Memory Extractor node activated...")
    user_id = state.get("user_id", "unknown")

    # Use a standard config for extraction
    llm = get_chat_model(
        model_name=MODEL_NAME,
        temperature=0,
        model_kwargs={
            "automatic_function_calling": {"disable": True},
        },
    )

    # Bind memory tools
    llm_with_tools = llm.bind_tools([save_semantic_memory, update_semantic_memory, retire_semantic_memory])

    # Construct messages: extractor prompt + last user message + last coach response
    extractor_prompt = (
        MEMORY_EXTRACTOR_PROMPT
        + f"\n\n### 🛡️ USER CONTEXT (MANDATORY)\n- **CURRENT USER ID:** {user_id}\n- **RULE:** All `save_semantic_memory` calls MUST use this user_id."
    )

    messages: list[BaseMessage] = [SystemMessage(content=extractor_prompt)]

    # Add existing memories from context if available for conflict resolution
    context = state.get("biometric_context", {})
    existing_memories = context.get("semantic_memories", [])
    if existing_memories:
        mem_lines = []
        for m in existing_memories:
            if isinstance(m, dict):
                mem_lines.append(
                    f"[ID: {m.get('id', '')}] {str(m.get('memory_type', '')).upper()}: {m.get('memory_text', '')}"
                )
            else:
                mem_lines.append(str(m))
        mem_str = "\n".join(mem_lines)
        messages.append(SystemMessage(content=f"Existing Semantic Memories:\n{mem_str}"))

    # Include ONLY the last Human message and the last AI response (the interaction to analyze)
    # This reduces noise and helps Gemma focus on the dialogue
    human_msg = next((m for m in reversed(state["messages"]) if m.type == "human"), None)
    ai_msg = next((m for m in reversed(state["messages"]) if m.type == "ai" and m.content), None)

    if human_msg:
        messages.append(HumanMessage(content=f"USER SAID: {human_msg.content}"))
    if ai_msg:
        # Join list content if necessary
        content = ai_msg.content
        if isinstance(content, list):
            content = "\n".join([str(p.get("text", "")) for p in content if isinstance(p, dict)])

        # Filter automated responses
        automated_keywords = [
            "sincronización ha comenzado",
            "garmin sync ha comenzado",
            "confirmación de sincronización",
            "enlace de autorización",
            "iniciar sesión",
            "critical system error",
            "no nuggets found",
        ]
        content_lower = str(content).lower()
        if any(kw in content_lower for kw in automated_keywords):
            log.info("🧠 Skipping memory extraction for automated system response.")
            return {
                "messages": [
                    SystemMessage(
                        content="Skipped memory extraction for automated response.",
                        additional_kwargs={"is_memory_extraction": True},
                    )
                ]
            }

        messages.append(SystemMessage(content=f"COACH RESPONDED: {content}"))

    # Debug log the messages
    log.info(f"🧠 Extractor input messages (Cleaned): {messages}")

    # Invoke extractor
    response = llm_with_tools.invoke(messages, config={"tags": ["memory_extractor"]})

    log.info(f"🧠 Extractor raw response: {response}")
    if hasattr(response, "tool_calls") and response.tool_calls:
        log.info(f"🧠 Extractor found {len(response.tool_calls)} nuggets!")
        # Tag the message explicitly to break loops in route_after_tools
        response.additional_kwargs["is_memory_extraction"] = True
        return {"messages": [response]}
    log.info("🧠 No nuggets extracted.")
    # Return as SystemMessage so main.py ignores it as a final assistant reply
    return {"messages": [SystemMessage(content="No nuggets found.", additional_kwargs={"is_memory_extraction": True})]}


# Conditional edges from analyzer
def route_after_analysis(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # Check if any tool call is for exploratory data science
        exploratory_tools = ["execute_exploratory_query", "get_bigquery_schema", "execute_exploratory_query_dry_run"]
        if any(tc["name"] in exploratory_tools for tc in last_message.tool_calls):
            log.info("🧪 Routing to Data Scientist node...")
            return "data_scientist"
        return "tools"

    # If no tools, go to validator before finishing
    return "validator"


def route_after_validation(state: AgentState):
    """Routes to memory_extractor or back to analyzer if validation failed."""
    last_msg = state["messages"][-1]
    if isinstance(last_msg, SystemMessage) and "CRITICAL SYSTEM ERROR" in str(last_msg.content):
        log.info("🔄 Validation failed. Routing back to analyzer for correction.")
        return "analyzer"
    return "memory_extractor"


memory = MemorySaver()

workflow = StateGraph(AgentState)
workflow.add_node("router", node_router)
workflow.add_node("retriever", node_retrieve_context)
workflow.add_node("injury_prevention", node_injury_prevention)
workflow.add_node("sleep_recovery", node_sleep_recovery)
workflow.add_node("metabolic_nutrition", node_metabolic_nutrition)
workflow.add_node("analyzer", node_analyze)
workflow.add_node("data_scientist", node_data_scientist)
workflow.add_node("validator", node_validator)
workflow.add_node("memory_extractor", node_memory_extractor)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "router")
workflow.add_edge("router", "retriever")


# Conditional fan-out: Short-circuit if intent is NONE, SYNC, PLANNING or PROFILE
def route_from_retriever(state: AgentState):
    """Short-circuits specialized agents if no biometric data is needed."""
    intent = state.get("intent", "full")

    if intent == "discovery":
        log.info("🧪 Intent is DISCOVERY. Routing to Data Scientist node.")
        return "data_scientist"

    if intent in ["none", "sync", "planning", "profile"]:
        log.info(f"⏭️ Intent is {intent.upper()}. Short-circuiting specialized agents.")
        return "analyzer"

    log.info(f"🔀 Intent is {intent.upper()}. Fanning out to specialized agents.")
    return ["injury_prevention", "sleep_recovery", "metabolic_nutrition"]


workflow.add_conditional_edges(
    "retriever",
    route_from_retriever,
    {
        "analyzer": "analyzer",
        "data_scientist": "data_scientist",
        "injury_prevention": "injury_prevention",
        "sleep_recovery": "sleep_recovery",
        "metabolic_nutrition": "metabolic_nutrition",
    },
)

# Fan-in: All specialized agents flow into the analyzer
workflow.add_edge("injury_prevention", "analyzer")
workflow.add_edge("sleep_recovery", "analyzer")
workflow.add_edge("metabolic_nutrition", "analyzer")

workflow.add_conditional_edges(
    "analyzer", route_after_analysis, {"tools": "tools", "data_scientist": "data_scientist", "validator": "validator"}
)

# After validator (the final coaching response is ready), run the memory extractor
workflow.add_conditional_edges(
    "validator", route_after_validation, {"analyzer": "analyzer", "memory_extractor": "memory_extractor"}
)

# The memory extractor calls tools directly if it finds nuggets
workflow.add_conditional_edges(
    "memory_extractor",
    lambda state: "tools" if hasattr(state["messages"][-1], "tool_calls") and state["messages"][-1].tool_calls else END,
)


# Tool results go back to the analyzer OR if they come from memory_extractor, they finish
def route_after_tools(state: AgentState):
    """Routes back to analyzer for recursion or ends if coming from memory_extractor."""
    # Find the AI message that triggered these tools
    trigger_msg = None
    for msg in reversed(state["messages"]):
        if msg.type == "ai":
            trigger_msg = msg
            break

    if not trigger_msg:
        log.warning("⚠️ Could not find triggering AI message after tools. Ending flow.")
        return END

    # If the tools were triggered by memory_extractor, we are done
    # We check both tags and the new explicit flag
    tags = getattr(trigger_msg, "response_metadata", {}).get("tags", [])
    if "memory_extractor" in str(tags) or trigger_msg.additional_kwargs.get("is_memory_extraction"):
        log.info("🏁 Tools were from memory_extractor. Ending flow.")
        return END

    # If the tools were triggered by data_scientist, go back to it to synthesize results
    if trigger_msg.additional_kwargs.get("is_ds_call"):
        # LOOP BREAKER: Prevent infinite DS tool loops
        loop_count = state.get("loop_count", 0)
        if loop_count >= 2:
            log.warning(f"⚠️ DataScientist loop limit reached ({loop_count}). Forcing to analyzer.")
            return "analyzer"
        log.info(f"🧪 Tools were from data_scientist (Iteration {loop_count}). Back-rooting to DS node.")
        return "data_scientist"

    # Otherwise, back to analyzer for recursion
    log.info("🔄 Tools were from analyzer. Back-rooting for recursion.")
    return "analyzer"


workflow.add_conditional_edges("tools", route_after_tools)
workflow.add_edge("data_scientist", "tools")

# Compile
graph = workflow.compile(checkpointer=memory)
