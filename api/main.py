from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.agent.graph import graph
from langchain_core.messages import HumanMessage
import os

app = FastAPI(
    title="Biometric AI Platform API",
    description="Agentic RAG Backend for Biometric Data Analysis",
    version="0.1.0"
)

class HealthCheck(BaseModel):
    status: str
    version: str

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str
    context_used: dict

@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check():
    """
    Returns the current health status of the API.
    """
    return HealthCheck(status="ok", version="0.1.0")

@app.post("/chat", response_model=ChatResponse, tags=["AI Agent"])
async def chat_with_agent(req: ChatRequest):
    """
    Main entrypoint for the Agentic RAG.
    """
    if not os.getenv("GOOGLE_API_KEY"):
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY environment variable is not set.")
        
    try:
        initial_state = {
            "messages": [HumanMessage(content=req.message)]
        }
        
        # Invoke LangGraph
        result = await graph.ainvoke(initial_state)
        
        # Extract the AI message from the end of the messages sequence
        ai_reply = result["messages"][-1].content
        context = result.get("biometric_context", {})
        
        return ChatResponse(reply=ai_reply, context_used=context)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
