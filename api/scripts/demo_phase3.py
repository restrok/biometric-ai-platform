import json
import asyncio
import os
import sys

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.agent.graph import graph
from langchain_core.messages import HumanMessage

async def run_demo():
    print("🚀 Initiating Multi-Agent Biometric Analysis (Phase 3 Demo)...")
    
    # User's real question
    user_message = "Ayer corrí casi 10k y me sentí muy bien. Mi HRV está un poco bajo (37ms) pero me siento con energía. ¿Puedo salir a correr hoy domingo unos 12k en Z2 para seguir sumando hacia mi carrera del 15 de julio?"
    
    inputs = {
        "messages": [HumanMessage(content=user_message)],
        "user_id": "fsirio",
        "intent": "full"
    }
    
    # Run the graph
    async for output in graph.astream(inputs, config={"configurable": {"thread_id": "demo_session"}}):
        for node_name, state in output.items():
            print(f"\n--- Node: {node_name} ---")
            if "messages" in state:
                last_msg = state["messages"][-1]
                # Log internal agent reports with a special prefix
                if "--- INTERNAL" in str(last_msg.content):
                    print(f"🕵️ Internal Expert Report:\n{last_msg.content}")
                else:
                    print(f"💬 Response:\n{last_msg.content}")

if __name__ == "__main__":
    asyncio.run(run_demo())
