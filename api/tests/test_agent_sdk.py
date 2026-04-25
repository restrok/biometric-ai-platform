import pytest
from src.agent.graph import graph
from src.tools.retriever import retrieve_biometric_data
from langchain_core.messages import HumanMessage

def test_retriever_not_empty():
    """Verify that the retriever returns a dictionary (even if mock)."""
    data = retrieve_biometric_data.invoke({})
    assert isinstance(data, dict)
    assert "recent_activities" in data

@pytest.mark.asyncio
async def test_agent_invocation():
    """Verify that the agent can be invoked and returns a message."""
    initial_state = {"messages": [HumanMessage(content="Hello coach, how am I doing?")]}
    result = await graph.ainvoke(initial_state)
    
    assert "messages" in result
    assert len(result["messages"]) > 1
    assert result["messages"][-1].content != ""
