from typing import TypedDict, Annotated, Sequence
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from src.tools.retriever import retrieve_biometric_data
import os

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], "The conversation history"]
    biometric_context: dict
    
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

### RESPONSE STRUCTURE (STRICT FORMATTING):
- Use **Markdown Tables** for heart rate zones or plan summaries.
- Use **Bold headers** for sections (e.g., ### 📊 Biometric Analysis).
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

import time
import logging

log = logging.getLogger(__name__)

def node_analyze(state: AgentState) -> dict:
    """Calls the LLM to generate the training plan/response."""
    t0 = time.time()
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)
    
    # Format the prompt
    context_str = f"\nUser Biometric Context:\n{state.get('biometric_context', {})}"
    messages = [SystemMessage(content=SYSTEM_PROMPT + context_str)] + list(state["messages"])
    
    response = llm.invoke(messages)
    
    duration = time.time() - t0
    token_usage = getattr(response, 'usage_metadata', 'N/A')
    log.info(f"🧠 LLM Response generated in {duration:.2f}s")
    log.info(f"🎫 Token Usage: {token_usage}")
    
    return {"messages": [response]}

# Build Graph
builder = StateGraph(AgentState)
builder.add_node("retriever", node_retrieve_context)
builder.add_node("analyzer", node_analyze)

builder.add_edge(START, "retriever")
builder.add_edge("retriever", "analyzer")
builder.add_edge("analyzer", END)

# Compile
graph = builder.compile()
