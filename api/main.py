from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import base64
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("api")

# Load environment variables from .env
load_dotenv()

# Decode GOOGLE_API_KEY if it's base64 encoded
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    try:
        # Check if it looks like base64 (not perfect but helpful)
        # Most base64 strings have a specific length and set of characters
        decoded_bytes = base64.b64decode(api_key, validate=True)
        decoded_str = decoded_bytes.decode("utf-8")
        # If it successfully decodes and looks like a Gemini key (starts with AIza)
        if decoded_str.startswith("AIza"):
            os.environ["GOOGLE_API_KEY"] = decoded_str
    except Exception:
        # If it fails to decode, we assume it's already plain text or invalid
        pass

from src.agent.graph import graph
from langchain_core.messages import HumanMessage

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
