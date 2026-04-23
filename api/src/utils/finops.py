import logging
import uuid
from datetime import datetime

from google.cloud import bigquery

from src.utils.config import get_config

log = logging.getLogger(__name__)
config = get_config()

# Gemini Pricing (approx. based on 2.5 Flash expectations)
PRICING = {
    "gemini-2.5-flash": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-2.5-flash-lite": {"input": 0.01 / 1_000_000, "output": 0.03 / 1_000_000},
    "gemini-flash-latest": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-1.5-flash": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-2.5-pro": {"input": 3.50 / 1_000_000, "output": 10.50 / 1_000_000},
}

PROJECT_ID = config["project_id"]
DATASET_ID = config["dataset_id"]
TABLE_ID = config["finops_table"]


def log_llm_call(model: str, input_tokens: int, output_tokens: int, latency_ms: float, node_name: str = "analyzer"):
    """
    Calculates cost and logs LLM usage to BigQuery.
    """
    total_tokens = input_tokens + output_tokens

    # Calculate cost
    model_pricing = PRICING.get(model, PRICING["gemini-2.5-flash"])
    cost = (input_tokens * model_pricing["input"]) + (output_tokens * model_pricing["output"])

    row = {
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": str(uuid.uuid4()),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": round(cost, 8),
        "latency_ms": round(latency_ms, 2),
        "node_name": node_name,
    }

    # Log to console
    log.info(f"💰 FinOps | Model: {model} | Cost: ${cost:.6f} | Latency: {latency_ms:.0f}ms")

    # Asynchronously stream to BigQuery (best effort)
    try:
        client = bigquery.Client(project=PROJECT_ID)
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
        errors = client.insert_rows_json(table_ref, [row])
        if errors:
            log.error(f"❌ BigQuery FinOps Error: {errors}")
    except Exception as e:
        log.warning(f"⚠️ Could not log to BigQuery FinOps: {e}")

    return row
