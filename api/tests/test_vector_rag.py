import sys
from pathlib import Path
import os
import base64
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env
load_dotenv(Path(__file__).parent.parent / ".env")

# Decode GOOGLE_API_KEY
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    try:
        decoded_bytes = base64.b64decode(api_key, validate=True)
        decoded_str = decoded_bytes.decode("utf-8")
        if decoded_str.startswith("AIza"):
            os.environ["GOOGLE_API_KEY"] = decoded_str
    except Exception:
        pass

from src.agent.graph import graph
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def test_vector_rag_flow():
    """
    Tests the agent's ability to search the vector store for exercise science.
    """
    print("\n🚀 Testing Vector Store (RAG) Flow...")
    print("="*60)
    
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
