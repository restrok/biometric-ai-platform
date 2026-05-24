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

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from src.agent.graph import graph
from src.agent.proactive import run_proactive_analysis
from src.routers import tools
from src.tools.etl_job import run_etl
from src.tools.profile_manager import ZoneUpdate, update_user_zones
from src.utils.garmin_auth import refresh_garmin_tokens


# --- Background Scheduler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    """
    import asyncio
    import threading

    async def refresh_loop():
        # Initial delay to let the system start up
        await asyncio.sleep(5)
        while True:
            try:
                log.info("🕒 Starting scheduled Garmin token refresh...")
                # Run in executor because it's a sync function doing IO
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(None, refresh_garmin_tokens)
                if success:
                    log.info("✅ Scheduled Garmin token refresh successful.")
                else:
                    log.warning("⚠️ Scheduled Garmin token refresh failed.")
            except Exception as e:
                log.error(f"❌ Error in scheduled token refresh: {e}")

            # Wait for 2 hours between refreshes
            await asyncio.sleep(2 * 3600)

    def run_proactive_scheduler():
        """Background loop to trigger proactive analysis at a specific local hour."""
        while True:
            try:
                interval_hours = int(os.getenv("PROACTIVE_INTERVAL_HOURS", "6"))
                now = datetime.now()

                if interval_hours > 0:
                    # Align to the next interval (e.g., if 6h, run at 00, 06, 12, 18)
                    next_interval_hour = ((now.hour // interval_hours) + 1) * interval_hours
                    if next_interval_hour >= 24:
                        next_run = (now + timedelta(days=1)).replace(
                            hour=next_interval_hour % 24, minute=0, second=0, microsecond=0
                        )
                    else:
                        next_run = now.replace(hour=next_interval_hour, minute=0, second=0, microsecond=0)

                    log.info(f"📅 Proactive auto-sync interval set to {interval_hours} hours (Local Time).")
                else:
                    # Fallback to daily specific hour (default 23:00 Local)
                    target_hour = int(os.getenv("PROACTIVE_HOUR_LOCAL", "23"))
                    next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
                    if next_run <= now:
                        next_run += timedelta(days=1)

                sleep_seconds = (next_run - now).total_seconds()
                log.info(
                    f"📅 Next proactive auto-sync scheduled for {next_run.strftime('%Y-%m-%d %H:%M:%S')} (Local Time, in {sleep_seconds / 3600:.2f} hours)"
                )

                time.sleep(sleep_seconds)

                # --- Execution Phase ---
                from db import get_user_mapping

                mapping = get_user_mapping()
                for _, user_id in mapping.items():
                    log.info(f"🧠 Running proactive analysis for user: {user_id}")
                    try:
                        run_proactive_analysis(user_id)
                    except Exception as e:
                        log.error(f"❌ Failed sync for user {user_id}: {e}")

                log.info("✅ Proactive auto-sync cycle completed.")

            except Exception as e:
                log.error(f"❌ Error in auto-sync loop: {e}")
                time.sleep(300)

    # Start the token refresh loop in the background
    asyncio.create_task(refresh_loop())

    # Start the proactive scheduler in a separate thread
    threading.Thread(target=run_proactive_scheduler, daemon=True).start()

    yield


app = FastAPI(title="Biometric AI API", lifespan=lifespan)
app.include_router(tools.router, prefix="/tools")


# --- OpenAI Compatibility Models ---
class OpenAIChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class OpenAICompletionRequest(BaseModel):
    model: str = "gemma-4-31b-it"
    messages: list[OpenAIChatMessage]
    stream: bool = False
    temperature: float = 0.2


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


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


@app.post("/profile/zones", tags=["User Profile"])
async def update_zones(zones: ZoneUpdate):
    """
    Updates the user's custom heart rate zones.
    """
    try:
        result = update_user_zones.invoke(zones.model_dump())
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sync", tags=["ETL"])
async def trigger_sync(user_id: str = "fsirio", days_back: int = 3):
    """
    Manually triggers a biometric sync for a specific user.
    """
    try:
        new_ids = run_etl(user_id=user_id, days_back=days_back)
        count = len(new_ids) if new_ids is not None else 0
        return {"status": "success", "synced_activities": count, "activity_ids": new_ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/chat/completions")
async def openai_chat_completion(req: OpenAICompletionRequest, x_user_id: str | None = Header(None, alias="X-User-ID")):
    """OpenAI-compatible endpoint for chat completions."""
    user_id = x_user_id or "fsirio"
    log.info(f"📩 Incoming chat completion request for user: {user_id}")

    # Extract user messages for the agent
    user_messages = [msg for msg in req.messages if msg.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message provided.")

    last_query = user_messages[-1].content
    initial_state = {"messages": [HumanMessage(content=last_query)], "user_id": user_id}

    # Add config for checkpointer (required for MemorySaver)
    config: RunnableConfig = {"configurable": {"thread_id": user_id}}

    # 1. Handle Streaming Mode
    if req.stream:

        async def event_generator():
            completion_id = f"chatcmpl-{int(time.time())}"
            created_time = int(time.time())

            async for event in graph.astream_events(cast(Any, initial_state), version="v2", config=config):
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
        result = await graph.ainvoke(cast(Any, initial_state), config=config)
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
