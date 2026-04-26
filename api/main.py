import json
import logging
import os
import time
from typing import Any, Literal, cast

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.utils.config import setup_environment

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("api")

# Load environment and handle API keys
setup_environment()

from langchain_core.messages import HumanMessage

from src.agent.graph import graph
from src.routers import tools
from src.tools.etl_job import run_etl
from src.tools.profile_manager import ZoneUpdate, update_user_zones

app = FastAPI(
    title="Biometric AI Platform API", description="Agentic RAG Backend for Biometric Data Analysis", version="0.1.0"
)

app.include_router(tools.router)


class HealthCheck(BaseModel):
    status: str
    version: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    context_used: dict


# --- OpenAI Compatibility Models ---


class OpenAIChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class OpenAICompletionRequest(BaseModel):
    model: str = "biometric-coach"
    messages: list[OpenAIChatMessage]
    stream: bool = False
    temperature: float | None = 0.7


class OpenAICompletionResponseChoice(BaseModel):
    index: int
    message: OpenAIChatMessage
    finish_reason: str | None = "stop"


class OpenAICompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{int(time.time())}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[OpenAICompletionResponseChoice]


@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check():
    """
    Returns the current health status of the API.
    """
    return HealthCheck(status="ok", version="0.1.0")


@app.post("/sync", tags=["System"])
async def trigger_sync():
    """
    Manually triggers the Garmin-to-BigQuery ETL process.
    """
    try:
        # In a production environment, this should be a background task
        run_etl()
        return {"status": "success", "message": "Biometric data sync completed."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/profile/zones", tags=["User Profile"])
async def update_zones(zones: ZoneUpdate):
    """
    Updates the user's custom heart rate zones.
    """
    try:
        # tool names are internal but for clarity we use the new one
        result = update_user_zones.invoke(zones.model_dump())
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/chat/completions", tags=["AI Agent"])
async def openai_chat_completion(req: OpenAICompletionRequest):
    """
    OpenAI-compatible endpoint for the Biometric Coach.
    Supports both streaming and non-streaming modes.
    """
    if not os.getenv("GOOGLE_API_KEY"):
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY environment variable is not set.")

    # We take the last user message as the primary query
    # In a multi-turn scenario, LangGraph handles the message history
    user_messages = [m for m in req.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message provided.")

    last_query = user_messages[-1].content
    initial_state = {"messages": [HumanMessage(content=last_query)]}

    # 1. Handle Streaming Mode
    if req.stream:

        async def event_generator():
            completion_id = f"chatcmpl-{int(time.time())}"
            created_time = int(time.time())

            async for event in graph.astream_events(initial_state, version="v2"):
                kind = event["event"]
                tags = event.get("tags", [])

                # Only stream tokens from the analyzer LLM
                if kind == "on_chat_model_stream" and "analyzer_llm" in tags:
                    content = event["data"]["chunk"].content
                    if isinstance(content, str) and content:
                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": req.model,
                            "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"

            # Final "stop" chunk
            yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created_time, 'model': req.model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # 2. Handle Non-Streaming Mode
    try:
        result = await graph.ainvoke(cast(Any, initial_state))
        ai_msg = result["messages"][-1]
        ai_reply = ai_msg.content

        # Handle Gemini rich response formats (lists/dicts)
        if isinstance(ai_reply, list):
            text_parts = [item if isinstance(item, str) else item.get("text", "") for item in ai_reply]
            ai_reply = "\n".join(filter(None, text_parts))
        elif not isinstance(ai_reply, str):
            ai_reply = str(ai_reply)

        return OpenAICompletionResponse(
            model=req.model,
            choices=[
                OpenAICompletionResponseChoice(
                    index=0, message=OpenAIChatMessage(role="assistant", content=ai_reply), finish_reason="stop"
                )
            ],
        )
    except Exception as e:
        log.error(f"❌ LangGraph invocation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
