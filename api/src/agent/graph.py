"""LangGraph definition for the Biometric AI Coach agent."""

import json
import logging
import time
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

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
from src.tools.historical_biometrics import generate_historical_report
from src.tools.memory_manager import retire_semantic_memory, save_semantic_memory, update_semantic_memory
from src.tools.predictive_modeler import project_training_impact
from scripts.list_models import list_available_models
from src.tools.profile_manager import (
    configure_proactive_coaching,
    log_health_status,
    manage_goals,
    save_calibration_marker,
    update_user_zones,
)

MODEL_NAME = "gemini-3.1-flash-lite"

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

    intent: Literal["none", "full", "activities", "sleep", "hrv", "nutrition"] = Field(
        ...,
        description="The type of biometric data needed to answer the query. "
        "Use 'none' if the query is general chitchat OR if it asks about another user's data (privacy violation).",
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
    model_name = MODEL_NAME
    # Forcefully disable AFC in the SDK to let LangGraph manage tool execution
    model = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
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

    if intent == "none":
        return {"biometric_context": {"info": "No user data retrieved for this query type."}}

    # Pass the user_id to the retriever tool
    context = retrieve_biometric_data.invoke({"user_id": user_id})
    return {"biometric_context": context}


def node_injury_prevention(state: AgentState) -> dict[str, Any]:
    """Specialized node for injury risk analysis."""
    log.info("🛡️ Injury Prevention Agent scanning biometrics...")
    model_name = MODEL_NAME
    model = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
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
    model_name = MODEL_NAME
    model = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
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
    model_name = MODEL_NAME
    model = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
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
    model_name = MODEL_NAME
    # Forcefully disable AFC in the SDK to let LangGraph manage tool execution
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        temperature=0.2,
        model_kwargs={"automatic_function_calling": {"disable": True}},
    )

    tools = [
        upload_training_plan,
        clear_calendar,
        remove_workout,
        search_exercise_science,
        update_user_zones,
        sync_biometric_data,
        generate_historical_report,
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
    isolation_prompt = f"\n\n### 🛡️ MULTI-TENANT ISOLATION (MANDATORY)\n- **CURRENT USER ID:** {user_id}\n- **RULE:** You are EXCLUSIVELY acting for user '{user_id}'. You MUST use this ID for all tool calls (e.g., `user_id='{user_id}'`). NEVER use 'fsirio' or any other ID unless the user ID is explicitly '{user_id}'."

    messages = [SystemMessage(content=HEAD_COACH_SYSTEM_PROMPT + context_str + isolation_prompt)] + list(
        state["messages"]
    )

    # DEBUG: Print full prompt sent to LLM
    log.debug("DEBUG: --- FULL PROMPT SENT TO LLM ---")
    for i, m in enumerate(messages):
        log.debug(f"DEBUG: Message {i} ({m.type}): {m.content[:500]}...")
    log.debug("DEBUG: -------------------------------")

    response = llm_with_tools.invoke(messages, config={"tags": ["analyzer_llm"]})

    latency_ms = (time.time() - t0) * 1000
    token_usage = getattr(response, "usage_metadata", {})

    usage = state.get("usage_stats", {})
    if not isinstance(usage, dict):
        usage = {}

    # Ensure keys exist
    usage.setdefault("total_tokens", 0)
    usage.setdefault("calls", 0)
    usage.setdefault("total_cost_usd", 0.0)

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
    model_name = MODEL_NAME
    user_id = state.get("user_id", "unknown")

    # Instantiate specialized LLM for Data Science
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        temperature=0,
        model_kwargs={"automatic_function_calling": {"disable": True}},
    )

    # Bind DS tools
    ds_tools = [execute_exploratory_query_dry_run, execute_exploratory_query, get_bigquery_schema]
    llm_with_tools = llm.bind_tools(ds_tools)

    # Context preparation
    messages: list[BaseMessage] = [
        SystemMessage(content=DATA_SCIENTIST_PROMPT + f"\n\n### 🛡️ USER SESSION: {user_id}")
    ]

    # Pass the last user interaction and biometric context for hypothesis formulation
    # We serialize the context to JSON to ensure the LLM can parse it easily
    context_str = json.dumps(state.get("biometric_context", {}), default=str)
    messages.append(HumanMessage(content=f"Biometric Context: {context_str}"))
    messages.append(state["messages"][-1])

    # Initial call to formulate hypothesis and potentially call tools
    response = llm_with_tools.invoke(messages)

    # If the DS wants to use tools, we return them to the 'tools' node
    if hasattr(response, "tool_calls") and response.tool_calls:
        log.info(f"🧪 DataScientist calling {len(response.tool_calls)} tools for discovery.")
        # Mark this AI message to identify its tools in the router
        response.additional_kwargs["is_ds_call"] = True
        return {"messages": [response]}

    # Once tools are done (or if no tools needed), force a structured output
    structured_llm = llm.with_structured_output(DataScientistOutput)
    try:
        final_findings = structured_llm.invoke(messages + [response])
        findings_msg = SystemMessage(
            content=f"🧪 DATA SCIENTIST REPORT:\n{json.dumps(final_findings.model_dump(), indent=2)}",
            additional_kwargs={"is_ds_report": True},
        )
        log.info("🧪 DataScientist generated structured report.")
        return {"messages": [findings_msg]}
    except Exception as e:
        log.error(f"❌ DataScientist failed to generate structured report: {e}")
        return {"messages": [SystemMessage(content=f"Data Scientist analysis failed: {e}")]}


def node_validator(state: AgentState) -> dict[str, Any]:
    """Validates the output of the analyzer to ensure physiological accuracy and formatting."""
    last_msg = state["messages"][-1].content
    log.info("🧐 Validator node reviewing response...")

    # Simple validation logic: check if the response is too short or lacks context
    if len(str(last_msg)) < 100 and "artifact_uri" not in str(last_msg):
        log.warning("⚠️ Response seems too brief. Requesting elaboration.")
        # This could trigger a retry or a feedback message

    return {"loop_count": state.get("loop_count", 0)}


def node_memory_extractor(state: AgentState) -> dict[str, Any]:
    """Dedicated node to extract 'Golden Nuggets' from the interaction."""
    log.info("🧠 Semantic Memory Extractor node activated...")
    model_name = MODEL_NAME
    user_id = state.get("user_id", "unknown")

    # Use a standard config for extraction
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
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
        mem_str = "\n".join(
            [f"[ID: {m['id']}] {m['memory_type'].upper()}: {m['memory_text']}" for m in existing_memories]
        )
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
        messages.append(SystemMessage(content=f"COACH RESPONDED: {content}"))

    # Debug log the messages
    log.info(f"🧠 Extractor input messages (Cleaned): {messages}")

    # Invoke extractor
    response = llm_with_tools.invoke(messages, config={"tags": ["memory_extractor"]})
    
    # Tag the message explicitly to break loops in route_after_tools
    response.additional_kwargs["is_memory_extraction"] = True
    
    log.info(f"🧠 Extractor raw response: {response}")
    if hasattr(response, "tool_calls") and response.tool_calls:
        log.info(f"🧠 Extractor found {len(response.tool_calls)} nuggets!")
    else:
        log.info("🧠 No nuggets extracted.")

    # The extractor node returns its tool calls directly to the graph's tools node
    return {"messages": [response]}


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

# Conditional fan-out: Short-circuit if intent is NONE
def route_from_retriever(state: AgentState):
    """Short-circuits specialized agents if no biometric data is needed."""
    intent = state.get("intent", "full")
    if intent == "none":
        log.info("⏭️ Intent is NONE. Short-circuiting specialized agents.")
        return ["analyzer"]
    
    log.info(f"🔀 Intent is {intent.upper()}. Fanning out to specialized agents.")
    return ["injury_prevention", "sleep_recovery", "metabolic_nutrition"]

workflow.add_conditional_edges(
    "retriever", 
    route_from_retriever,
    {
        "analyzer": "analyzer",
        "injury_prevention": "injury_prevention",
        "sleep_recovery": "sleep_recovery",
        "metabolic_nutrition": "metabolic_nutrition"
    }
)

# Fan-in: All specialized agents flow into the analyzer
workflow.add_edge("injury_prevention", "analyzer")
workflow.add_edge("sleep_recovery", "analyzer")
workflow.add_edge("metabolic_nutrition", "analyzer")

workflow.add_conditional_edges(
    "analyzer", route_after_analysis, {"tools": "tools", "data_scientist": "data_scientist", "validator": "validator"}
)

# After validator (the final coaching response is ready), run the memory extractor
workflow.add_edge("validator", "memory_extractor")

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
        log.info("🧪 Tools were from data_scientist. Back-rooting to DS node.")
        return "data_scientist"

    # Otherwise, back to analyzer for recursion
    log.info("🔄 Tools were from analyzer. Back-rooting for recursion.")
    return "analyzer"


workflow.add_conditional_edges("tools", route_after_tools)
workflow.add_edge("data_scientist", "tools")

# Compile
graph = workflow.compile(checkpointer=memory)
