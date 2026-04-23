import asyncio
import base64
import os
import sys
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load and decode API Key
load_dotenv(Path(__file__).parent.parent / ".env")
api_key_raw = os.getenv("GOOGLE_API_KEY")
if api_key_raw:
    try:
        decoded_bytes = base64.b64decode(api_key_raw, validate=True)
        decoded_str = decoded_bytes.decode("utf-8")
        if decoded_str.startswith("AIza"):
            os.environ["GOOGLE_API_KEY"] = decoded_str
    except Exception:
        pass

import logging

from langchain_core.messages import HumanMessage

from src.agent.graph import graph

logging.basicConfig(level=logging.INFO)


async def test_finops_integration():
    print("\n🚀 Testing FinOps & Observability Integration...")
    print("=" * 60)

    query = "Explain why my heart rate zones are important for training."
    inputs = {"messages": [HumanMessage(content=query)]}

    print(f"User Query: {query}")
    print("\nInvoking Agent...")

    # Run the graph
    result = await graph.ainvoke(cast(Any, inputs))

    # Verify usage_stats in result
    usage = result.get("usage_stats", {})
    print("\n✅ Session Usage Stats (Agent State):")
    print(f"   - Total Tokens: {usage.get('total_tokens')}")
    print(f"   - Total Calls:  {usage.get('calls')}")
    print(f"   - Total Cost:   ${usage.get('total_cost_usd', 0):.8f}")

    print("\n🔍 Check your BigQuery table 'biometric_data_dev.finops_logs' to see the persistent entry!")


if __name__ == "__main__":
    asyncio.run(test_finops_integration())
