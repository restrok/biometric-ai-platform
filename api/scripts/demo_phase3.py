import asyncio
import os
import sys

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import HumanMessage

from src.agent.graph import AgentState, graph


async def run_demo():
    print("🚀 Initiating Multi-Agent Biometric Analysis (Phase 3 Demo)...")

    # User's real question
    user_message = "Yesterday I ran almost 10k and felt great. My HRV is a bit low (37ms) but I feel energetic. Can I go for a 12k Z2 run today (Sunday) to keep building toward my race on July 15th?"

    inputs: AgentState = {
        "messages": [HumanMessage(content=user_message)],
        "user_id": "fsirio",
        "intent": "full",
        "biometric_context": {},
        "usage_stats": {},
        "loop_count": 0,
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
