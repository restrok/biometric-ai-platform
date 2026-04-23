import logging
import sys
from pathlib import Path

from src.utils.config import setup_environment

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Load environment
setup_environment()

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.graph import graph


def test_vector_rag_flow():
    """
    Tests the agent's ability to search the vector store for exercise science.
    """
    print("\n🚀 Testing Vector Store (RAG) Flow...")
    print("=" * 60)

    query = "Explain the benefits of polarized 80/20 training according to my internal research base."

    inputs = {"messages": [HumanMessage(content=query)]}

    print(f"User Query: {query}")
    print("\nProcessing...\n")

    # Run the graph
    for output in graph.stream(inputs):
        for node_name, state in output.items():
            print(f"\n--- Node: {node_name} ---")
            if "messages" in state:
                msg = state["messages"][-1]
                if isinstance(msg, AIMessage):
                    if msg.tool_calls:
                        print(f"🛠️ Tool Call: {msg.tool_calls[0]['name']}")
                    if msg.content:
                        print(f"💬 AI: {msg.content[:500]}...")
                elif isinstance(msg, ToolMessage):
                    print(f"✅ Tool Result (truncated): {msg.content[:300]}...")


if __name__ == "__main__":
    test_vector_rag_flow()
