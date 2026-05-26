import asyncio
import os
import sys

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import HumanMessage

from src.agent.graph import AgentState, graph
from src.utils.config import setup_environment


async def run_audit():
    setup_environment()
    print("🚀 Initiating 'First Look' Onboarding Audit for Mercedes...")

    user_id = "mercedes"
    user_message = (
        "Haz un 'First Look' audit de mi perfil. Analiza mi historial de actividades "
        "(especially 'Tigre Carrera') to identify my Aerobic Threshold (AeT) and my "
        "actual Max Heart Rate. Save these values as calibration markers "
        "y actualiza mis zonas si es necesario."
    )

    inputs: AgentState = {
        "messages": [HumanMessage(content=user_message)],
        "user_id": user_id,
        "intent": "full",
        "biometric_context": {},
        "usage_stats": {},
        "loop_count": 0,
    }

    # Run the graph
    async for output in graph.astream(inputs, config={"configurable": {"thread_id": f"audit_{user_id}"}}):
        for node_name, state in output.items():
            print(f"\n--- Node: {node_name} ---")
            if "messages" in state:
                last_msg = state["messages"][-1]
                print(f"💬 Response:\n{last_msg.content}")

if __name__ == "__main__":
    asyncio.run(run_audit())
