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
SYSTEM_PROMPT = """You are a highly advanced AI Running Coach. 
Your goal is to provide training advice based on the user's query and their current biometric context.

STRICT TRAINING RULES (Based on Exercise Science):
1. Training Intensity Distribution (80/20 Rule): 80% at Zone 2 (easy), 20% at high intensity (Zone 4/5).
2. Avoid spending time in Zone 3 (gray zone).
3. Always check Sleep and HRV data. If Sleep Score < 60 or HRV is unbalanced, recommend a rest day or Z1 recovery run.

Always ground your answers in the provided Biometric Context.
"""

def node_retrieve_context(state: AgentState) -> dict:
    """Simulates retrieving data from Vector DB / Data Lake."""
    # In a real scenario, we would parse the user query to determine what to fetch.
    # Here we use a dummy tool.
    context = retrieve_biometric_data()
    return {"biometric_context": context}

def node_analyze(state: AgentState) -> dict:
    """Calls the LLM to generate the training plan/response."""
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)
    
    # Format the prompt
    context_str = f"\nUser Biometric Context:\n{state.get('biometric_context', {})}"
    messages = [SystemMessage(content=SYSTEM_PROMPT + context_str)] + list(state["messages"])
    
    response = llm.invoke(messages)
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
