import asyncio
import os
import sys
import uuid

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import HumanMessage

from src.agent.graph import graph
from src.utils.config import setup_environment


async def run_test_cycle(user_id: str, thread_id: str, message: str, description: str):
    print(f"\n🚀 {description}")
    print(f"💬 User: {message}")

    inputs = {
        "messages": [HumanMessage(content=message)],
        "user_id": user_id,
        "intent": "full",
        "biometric_context": {},
        "usage_stats": {},
        "loop_count": 0,
    }

    config = {"configurable": {"thread_id": thread_id}}

    async for output in graph.astream(inputs, config=config):
        for node_name, state in output.items():
            if node_name == "memory_extractor":
                print(f"🧠 [Node: {node_name}] analyzing for Golden Nuggets...")
            elif node_name == "tools":
                last_msg = state["messages"][-1]
                if hasattr(last_msg, "tool_calls"):
                    for tc in last_msg.tool_calls:
                        print(f"🔧 [Tool Call] {tc['name']}({tc['args']})")
            elif node_name == "analyzer":
                last_msg = state["messages"][-1]
                print(f"🏃 [Node: {node_name}] responding...")
                print(f"💬 Coach: {last_msg.content[:200]}...")


async def main():
    setup_environment()
    user_id = "test_user_" + str(uuid.uuid4())[:4]

    # --- TEST 1: Extraction ---
    await run_test_cycle(
        user_id,
        f"session_1_{user_id}",
        "Hola coach, soy nuevo. Me encanta correr por la montaña, pero odio las cintas de correr.",
        "TEST 1: New Fact Extraction",
    )

    # Give some time for Firestore writes if async (though here it's sequential)
    await asyncio.sleep(2)

    # --- TEST 2: Retrieval ---
    await run_test_cycle(
        user_id,
        f"session_2_{user_id}",
        "¿Qué sabes sobre mis preferencias de terreno y equipamiento?",
        "TEST 2: Retrieval in New Session",
    )

    # --- TEST 3: Conflict Resolution ---
    await run_test_cycle(
        user_id,
        f"session_3_{user_id}",
        "He cambiado de opinión. Ahora tengo una cinta de correr Pro en casa y voy a empezar a usarla los días de lluvia.",
        "TEST 3: Conflict Resolution (Updating 'hate treadmills')",
    )

    await asyncio.sleep(2)

    # --- TEST 4: Final Check ---
    await run_test_cycle(
        user_id, f"session_4_{user_id}", "Resúmeme qué sabes de mí ahora.", "TEST 4: Final State Verification"
    )


if __name__ == "__main__":
    asyncio.run(main())
