import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery

from src.utils.config import get_config

log = logging.getLogger(__name__)
config = get_config()

# Gemini Pricing (approx. based on 2.5/3.1 Flash expectations)
PRICING = {
    "gemini-2.5-flash": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-2.5-flash-lite": {"input": 0.01 / 1_000_000, "output": 0.03 / 1_000_000},
    "gemini-flash-latest": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-1.5-flash": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-2.5-pro": {"input": 3.50 / 1_000_000, "output": 10.50 / 1_000_000},
    "gemini-3.1-flash-lite": {"input": 0.01 / 1_000_000, "output": 0.03 / 1_000_000},
    "gemini-3.1-flash-lite-preview": {"input": 0.01 / 1_000_000, "output": 0.03 / 1_000_000},
    "gemma-4-31b-it": {"input": 0.0 / 1_000_000, "output": 0.0 / 1_000_000},
    "gemma-4-26b-a4b-it": {"input": 0.0 / 1_000_000, "output": 0.0 / 1_000_000},
    "gemma-4-26b-it": {"input": 0.0 / 1_000_000, "output": 0.0 / 1_000_000},
}

PROJECT_ID = config["project_id"]
DATASET_ID = config["dataset_id"]
TABLE_ID = config["finops_table"]

_bq_client: bigquery.Client | None = None


def _get_finops_bq_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def extract_token_usage(response: Any) -> tuple[int, int]:
    """Extracts (input_tokens, output_tokens) from a LangChain LLM response."""
    in_t = 0
    out_t = 0
    usage_meta = getattr(response, "usage_metadata", None)
    if usage_meta:
        if isinstance(usage_meta, dict):
            in_t = int(usage_meta.get("input_tokens", 0) or 0)
            out_t = int(usage_meta.get("output_tokens", 0) or 0)
        else:
            in_t = int(getattr(usage_meta, "input_tokens", 0) or 0)
            out_t = int(getattr(usage_meta, "output_tokens", 0) or 0)

    if not in_t and not out_t:
        resp_meta = getattr(response, "response_metadata", None)
        if isinstance(resp_meta, dict):
            token_usage = resp_meta.get("token_usage")
            if isinstance(token_usage, dict):
                in_t = int(token_usage.get("prompt_tokens", 0) or 0)
                out_t = int(token_usage.get("completion_tokens", 0) or 0)

    return in_t, out_t


def log_llm_call(
    model: str, input_tokens: int, output_tokens: int, latency_ms: float, node_name: str = "analyzer"
) -> dict[str, Any]:
    """Calculates cost and logs LLM usage to BigQuery."""
    total_tokens = input_tokens + output_tokens

    # Calculate cost
    model_pricing = PRICING.get(model)
    if not model_pricing:
        provider = os.getenv("LLM_PROVIDER", "google").lower()
        if provider == "lmstudio" or "gemma" in model.lower() or "local" in model.lower():
            model_pricing = {"input": 0.0, "output": 0.0}
        elif "lite" in model.lower():
            model_pricing = PRICING["gemini-3.1-flash-lite"]
        else:
            model_pricing = PRICING["gemini-2.5-flash"]

    cost = (input_tokens * model_pricing["input"]) + (output_tokens * model_pricing["output"])

    row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "request_id": str(uuid.uuid4()),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": round(cost, 8),
        "latency_ms": round(latency_ms, 2),
        "node_name": node_name,
    }

    log.info(
        f"💰 FinOps [{node_name}] | Model: {model} | Tokens: {input_tokens}->{output_tokens} | Cost: ${cost:.6f} | Latency: {latency_ms:.0f}ms"
    )

    if os.getenv("PYTEST_CURRENT_TEST"):
        return row

    try:
        client = _get_finops_bq_client()
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
        errors = client.insert_rows_json(table_ref, [row])
        if errors:
            log.error(f"❌ BigQuery FinOps Error: {errors}")
    except Exception as e:
        log.warning(f"⚠️ Could not log to BigQuery FinOps: {e}")

    return row
