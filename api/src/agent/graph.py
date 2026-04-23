from collections.abc import Sequence
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode

from src.tools.garmin_uploader import clear_garmin_calendar, upload_workouts_to_garmin
from src.tools.research_assistant import search_exercise_science
from src.tools.retriever import retrieve_biometric_data
from src.utils.finops import log_llm_call


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    biometric_context: dict
    usage_stats: dict  # Track cumulative tokens/calls
    
# System prompt incorporating legacy_logic rules (summarized)
SYSTEM_PROMPT = """You are a highly advanced AI Running Coach and Exercise Physiologist. 
Your goal is to provide personalized, research-backed training advice based on the user's query and their current biometric context.

### CORE TRAINING PRINCIPLES (Scientific Guidelines):
1. **Polarized Training (80/20 Rule):**
   - 80% of training MUST be at Low Intensity (Zone 2).
   - 20% should be at High Intensity (Zone 4/5).
   - **STRICT RULE:** Avoid the "Gray Zone" (Zone 3). It provides neither optimal aerobic nor anaerobic stress.

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
In addition to heart rate and pace, you have access to advanced Garmin metrics when available:
- **Efficiency:** Power (Watts), Vertical Oscillation, Ground Contact Time, Run Cadence, Stride Length.
- **Environment:** Temperature.
- **Form:** Run/Walk transitions and Elevation.
Analyze these to provide a holistic view of the runner's economy.

### TOOLS & ACTIONS:
- **upload_workouts_to_garmin:** You MUST call this tool whenever the user asks for a training plan, recovery plan, or workout upload. 
- **search_exercise_science:** Use this tool to retrieve foundational knowledge from your vector store when answering theoretical questions, justifying your recommendations with science, or interpreting advanced metrics.
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

def node_retrieve_context(state: AgentState) -> dict:
    """Simulates retrieving data from Vector DB / Data Lake."""
    # In a real scenario, we would parse the user query to determine what to fetch.
    # Here we use a dummy tool.
    context = retrieve_biometric_data()
    return {"biometric_context": context}

import logging
import time

log = logging.getLogger(__name__)

def node_analyze(state: AgentState) -> dict:
    """Calls the LLM to generate the training plan/response."""
    t0 = time.time()
    model_name = "gemini-2.5-flash"
    llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.2)
    
    # Bind tools to the LLM
    tools = [upload_workouts_to_garmin, search_exercise_science]
    llm_with_tools = llm.bind_tools(tools)
    
    # Format the prompt
    context_str = f"\nUser Biometric Context:\n{state.get('biometric_context', {})}"
    messages = [SystemMessage(content=SYSTEM_PROMPT + context_str)] + list(state["messages"])
    
    response = llm_with_tools.invoke(messages)
    
    latency_ms = (time.time() - t0) * 1000
    token_usage = getattr(response, 'usage_metadata', {})
    
    # Update cumulative usage (Agent State Tracking)
    usage = state.get("usage_stats", {"total_tokens": 0, "calls": 0, "total_cost_usd": 0.0})
    
    # Log to BigQuery (FinOps)
    if token_usage:
        in_t = getattr(token_usage, 'input_tokens', 0)
        out_t = getattr(token_usage, 'output_tokens', 0)
        finops_row = log_llm_call(model_name, in_t, out_t, latency_ms, node_name="analyzer")
        
        usage["total_tokens"] += (in_t + out_t)
        usage["total_cost_usd"] += finops_row["cost_usd"]
        
    usage["calls"] += 1
    
    return {"messages": [response], "usage_stats": usage}

# Define Tool Node
tool_node = ToolNode([upload_workouts_to_garmin, clear_garmin_calendar, search_exercise_science])

def should_continue(state: AgentState):
    """Determines if the graph should continue to tools or end."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END

# Build Graph
builder = StateGraph(AgentState)
builder.add_node("retriever", node_retrieve_context)
builder.add_node("analyzer", node_analyze)
builder.add_node("tools", tool_node)

builder.add_edge(START, "retriever")
builder.add_edge("retriever", "analyzer")

# Conditional edge from analyzer to tools or end
builder.add_conditional_edges(
    "analyzer",
    should_continue,
    {
        "tools": "tools",
        END: END
    }
)

# After tools, go back to analyzer to summarize or finish
builder.add_edge("tools", "analyzer")

# Compile
graph = builder.compile()
