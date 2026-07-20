"""
Telemetry & Observability module for Biometric AI Platform.

Lab implementation combining:
- OpenTelemetry: FastAPI HTTP request tracing (exports to console/stdout).
- Langfuse:      GenAI/LLM agent tracing for LangGraph (exports to Langfuse Cloud or self-hosted).

Both integrations degrade gracefully if the relevant ENV VARS are not set.
"""

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI
    from langfuse.callback import CallbackHandler

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# OpenTelemetry – FastAPI HTTP Instrumentation
# ─────────────────────────────────────────────────────────────────────────────

def init_otel(app: "FastAPI") -> None:
    """
    Initialises OpenTelemetry SDK and instruments the FastAPI application.

    All spans are exported to the console (stdout) via ConsoleSpanExporter,
    which makes them visible in the existing structured-log pipeline.
    Set ENABLE_OTEL=false to completely disable this instrumentation.
    """
    if os.getenv("ENABLE_OTEL", "true").lower() == "false":
        log.info("📡 OpenTelemetry: disabled via ENABLE_OTEL=false")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # 1. Create a TracerProvider with service metadata
        resource = Resource.create(
            {
                "service.name": "biometric-ai-api",
                "service.version": "0.4.2",
                "deployment.environment": os.getenv("ENV", "development"),
            }
        )
        provider = TracerProvider(resource=resource)

        # 2. Export spans to console (integrate with existing JSON log pipeline)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        # 3. Register as the global provider
        trace.set_tracer_provider(provider)

        # 4. Auto-instrument FastAPI (captures every HTTP request/response)
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            excluded_urls="/health",   # skip heartbeat spam
        )

        log.info("📡 OpenTelemetry: FastAPI instrumented ✅ (ConsoleSpanExporter)")

    except ImportError as e:
        log.warning(f"📡 OpenTelemetry: packages missing, skipping – {e}")
    except Exception as e:
        log.warning(f"📡 OpenTelemetry: failed to initialise – {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Langfuse – LLM / Agent Tracing
# ─────────────────────────────────────────────────────────────────────────────

def get_langfuse_callback(
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
) -> "CallbackHandler | None":
    """
    Returns a Langfuse CallbackHandler for LangGraph/LangChain, or None if
    Langfuse is not configured.

    The handler is passed to `graph.invoke(..., config={"callbacks": [handler]})`
    to capture the full agent trace (nodes, LLM calls, tool invocations,
    token counts, latency) in the Langfuse dashboard.

    Args:
        session_id: Optional session ID to group traces (e.g., thread_id / user_id).
        user_id:    Optional user identifier for multi-tenant filtering in Langfuse.
        tags:       Optional list of tags (e.g., ["proactive", "planner"]).

    Returns:
        A configured CallbackHandler, or None if LANGFUSE_PUBLIC_KEY is missing.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        log.debug("🔭 Langfuse: not configured (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY missing)")
        return None

    try:
        from langfuse.callback import CallbackHandler

        handler = CallbackHandler(
            public_key=public_key,
            secret_key=secret_key,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            session_id=session_id,
            user_id=user_id,
            tags=tags or [],
        )
        log.info(f"🔭 Langfuse: callback handler created (session={session_id}, user={user_id})")
        return handler

    except ImportError as e:
        log.warning(f"🔭 Langfuse: package not installed, skipping – {e}")
        return None
    except Exception as e:
        log.warning(f"🔭 Langfuse: failed to create callback – {e}")
        return None
