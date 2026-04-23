import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.utils.config import setup_environment

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("api")

# Load environment and handle API keys
setup_environment()

from langchain_core.messages import HumanMessage

from src.agent.graph import graph

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
        msg = result["messages"][-1]
        ai_reply = msg.content
        
        # Handle list-style content (Gemini rich responses) or non-string content
        if isinstance(ai_reply, list):
            # Extract text from all text-bearing items in the list
            text_parts = []
            for item in ai_reply:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        text_parts.append(item["text"])
            ai_reply = "\n".join(text_parts)
        elif not isinstance(ai_reply, str):
            # Fallback for any other weird type
            ai_reply = str(ai_reply)
            
        context = result.get("biometric_context", {})
        
        return ChatResponse(reply=ai_reply, context_used=context)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
