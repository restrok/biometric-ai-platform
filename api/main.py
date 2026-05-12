import json
import logging
import os
import time
from typing import Any, Literal, cast

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.utils.config import setup_environment

# Load environment and handle API keys (must be before logging setup to get LOG_LEVEL)
setup_environment()

# Configure logging
log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)

log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

# Console Handler
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)

# File Handler
file_handler = logging.FileHandler("api.log")
file_handler.setFormatter(log_formatter)

# Root configuration
root_logger = logging.getLogger()
for h in root_logger.handlers[:]:
    root_logger.removeHandler(h)

root_logger.setLevel(log_level)
root_logger.addHandler(stream_handler)
root_logger.addHandler(file_handler)

log = logging.getLogger("api")
log.info(f"🚀 Logging initialized with level: {log_level_name}")

from contextlib import asynccontextmanager, suppress

from langchain_core.messages import HumanMessage

from src.agent.graph import graph
from src.agent.proactive import run_proactive_analysis
from src.routers import tools
from src.tools.etl_job import run_etl
from src.tools.profile_manager import ZoneUpdate, update_user_zones
from src.utils.garmin_auth import get_all_garmin_user_ids, refresh_garmin_tokens


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    """
    import asyncio

    async def refresh_loop():
        while True:
            # Wait for 2 hours between refreshes
            await asyncio.sleep(2 * 3600)
            try:
                log.info("🕒 Starting scheduled Garmin token refresh...")
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(None, refresh_garmin_tokens)
                if success:
                    log.info("✅ Scheduled Garmin token refresh successful.")
                else:
                    log.warning("⚠️ Scheduled Garmin token refresh failed.")
            except Exception as e:
                log.error(f"❌ Error in scheduled token refresh: {e}")

    async def auto_sync_loop():
        # Initial delay to let the system settle
        await asyncio.sleep(60)
        while True:
            try:
                log.info("🕒 Starting proactive auto-sync ETL...")
                user_ids = get_all_garmin_user_ids()

                if not user_ids:
                    log.warning("No users found to sync.")

                for uid in user_ids:
                    log.info(f"🔄 Syncing data for user: {uid}")
                    loop = asyncio.get_event_loop()
                    # run_etl is synchronous, run in executor
                    await loop.run_in_executor(None, run_etl, uid)

                    log.info(f"🧠 Running proactive analysis for user: {uid}")
                    await loop.run_in_executor(None, run_proactive_analysis, uid)

                log.info("✅ Proactive auto-sync cycle completed.")
            except Exception as e:
                log.error(f"❌ Error in auto-sync loop: {e}")

            # Wait for 6 hours between syncs (Optimization: reduce frequency to save quota)
            await asyncio.sleep(6 * 3600)

    # Start the background tasks
    refresh_task = asyncio.create_task(refresh_loop())
    sync_task = asyncio.create_task(auto_sync_loop())

    yield

    # Clean up on shutdown
    refresh_task.cancel()
    sync_task.cancel()
    with suppress(asyncio.CancelledError):
        await asyncio.gather(refresh_task, sync_task)


app = FastAPI(
    title="Biometric AI Platform API",
    description="Agentic RAG Backend for Biometric Data Analysis",
    version="0.1.0",
    lifespan=lifespan,
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
async def openai_chat_completion(req: OpenAICompletionRequest, x_user_id: str | None = Header(None)):
    """
    OpenAI-compatible endpoint for the Biometric Coach.
    Supports both streaming and non-streaming modes.
    """
    log.info(f"📩 Incoming chat completion request for user: {x_user_id or 'anonymous'}")

    if not os.getenv("GOOGLE_API_KEY"):
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY environment variable is not set.")

    # We take the last user message as the primary query
    user_messages = [m for m in req.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message provided.")

    last_query = user_messages[-1].content
    initial_state = {"messages": [HumanMessage(content=last_query)], "user_id": x_user_id}

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
