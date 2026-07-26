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

    If GCP_TRACE_ENABLED=true, spans are sent to Google Cloud Trace using
    CloudTraceSpanExporter. Otherwise, spans are exported to the console (stdout)
    via ConsoleSpanExporter, making them visible in the structured-log pipeline.
    Set ENABLE_OTEL=false to completely disable this instrumentation.
    """
    if os.getenv("ENABLE_OTEL", "true").lower() == "false":
        log.info("📡 OpenTelemetry: disabled via ENABLE_OTEL=false")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        # 1. Create a TracerProvider with service metadata
        resource = Resource.create(
            {
                "service.name": "biometric-ai-api",
                "service.version": "0.4.2",
                "deployment.environment": os.getenv("ENV", "development"),
            }
        )
        provider = TracerProvider(resource=resource)

        # 2. Select Exporter based on configuration
        gcp_trace_enabled = os.getenv("GCP_TRACE_ENABLED", "false").lower() == "true"
        if gcp_trace_enabled:
            try:
                from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

                # CloudTraceSpanExporter automatically detects credentials and GCP project
                # via GOOGLE_APPLICATION_CREDENTIALS / metadata server.
                project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
                exporter = CloudTraceSpanExporter(project_id=project_id)
                provider.add_span_processor(BatchSpanProcessor(exporter))
                log.info(f"📡 OpenTelemetry: exporting to GCP Cloud Trace (Project: {project_id})")
            except Exception as e:
                log.warning(
                    f"📡 OpenTelemetry: failed to init GCP Cloud Trace exporter ({e}). Falling back to console."
                )
                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        else:
            # Export spans to console (integrate with existing JSON log pipeline)
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            log.info("📡 OpenTelemetry: exporting to console (ConsoleSpanExporter)")

        # 3. Register as the global provider
        trace.set_tracer_provider(provider)

        # 4. Auto-instrument FastAPI (captures every HTTP request/response)
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            excluded_urls="/health",  # skip heartbeat spam
        )

        log.info("📡 OpenTelemetry: FastAPI instrumented ✅")

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
        try:
            from langfuse.callback import CallbackHandler
        except ImportError:
            from langfuse.langchain import CallbackHandler

        host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
        try:
            handler = CallbackHandler(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                session_id=session_id,
                user_id=user_id,
                tags=tags or [],
            )
        except TypeError:
            # Langfuse v4+ CallbackHandler reads keys directly from environment variables
            handler = CallbackHandler()
        log.info(f"🔭 Langfuse: callback handler created (session={session_id}, user={user_id})")
        return handler

    except ImportError as e:
        log.warning(f"🔭 Langfuse: package not installed, skipping – {e}")
        return None
    except Exception as e:
        log.warning(f"🔭 Langfuse: failed to create callback – {e}")
        return None
