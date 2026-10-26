import json
import logging
import re
from typing import Any

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

log = logging.getLogger(__name__)

# Cache clients per project to reduce initialization overhead
_bq_clients: dict[str, bigquery.Client] = {}
_tables_cache: dict[str, list[str]] = {}


def get_bq_client(project_id: str) -> bigquery.Client:
    """Gets or creates a BigQuery client for the given project ID."""
    global _bq_clients
    if project_id not in _bq_clients:
        _bq_clients[project_id] = bigquery.Client(project=project_id)
    return _bq_clients[project_id]


def _get_available_tables(client: bigquery.Client, project_id: str, dataset_id: str) -> list[str]:
    cache_key = f"{project_id}.{dataset_id}"
    if cache_key not in _tables_cache:
        dataset_ref = client.dataset(dataset_id)
        _tables_cache[cache_key] = [t.table_id for t in client.list_tables(dataset_ref)]
    return _tables_cache[cache_key]


def _qualify_and_isolate_sql(sql: str, user_id: str, project_id: str, dataset_id: str, tables: list[str]) -> str:
    """Normalizes user_id filter and qualifies unqualified table names safely."""
    # 1. Replace any single-quoted user_id literal in `user_id = '...'` with the verified user_id
    normalized_sql = re.sub(
        r"(?i)(\buser_id\s*=\s*)'[^']*'",
        lambda m: f"{m.group(1)}'{user_id}'",
        sql,
    )

    # 2. Qualify table names that are not already preceded by `.` or `` ` ``
    qualified_sql = normalized_sql
    for table in sorted(tables, key=len, reverse=True):
        pattern = rf"(?<![.`\w])\b{re.escape(table)}\b(?![`])"
        qualified_sql = re.sub(pattern, f"`{project_id}.{dataset_id}.{table}`", qualified_sql)

    return qualified_sql


def _format_bytes(size: float) -> str:
    """Formats bytes into human readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


class SQLQueryInput(BaseModel):
    """Input schema for executing an exploratory SQL query."""

    sql: str = Field(..., description="The complete BigQuery SQL query to execute. MUST be a SELECT statement.")
    user_id: str = Field(..., description="The internal ID of the user (to verify isolation).")


@tool(args_schema=SQLQueryInput)
def execute_exploratory_query(sql: str, user_id: str) -> str:
    """
    Executes a read-only SQL query against the BigQuery data lake with an automatic SRE cost dry-run check.
    Use this tool ONLY when standard analysis tools are insufficient for
    answering complex, multi-domain correlation questions.

    🚨 SECURITY RULES:
    1. MUST contain 'WHERE user_id = {user_id}'.
    2. MUST NOT contain INSERT, UPDATE, DELETE, DROP, or ALTER.
    3. MUST list explicit columns (no SELECT *).
    """
    config = get_config()
    pid = config.get("project_id")
    ds = config.get("dataset_id")

    # 1. Basic Security Validation (Redundant to IAM but good for LLM feedback)
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "MERGE"]
    if any(re.search(rf"\b{word}\b", sql.upper()) for word in forbidden):
        return "Error: Only SELECT operations are allowed for exploratory analysis."

    if "SELECT *" in sql.upper():
        return (
            "Error: SELECT * is forbidden. Please list explicit columns to ensure cost efficiency and schema stability."
        )

    try:
        client = get_bq_client(pid)
        available_tables = _get_available_tables(client, pid, ds)
        qualified_sql = _qualify_and_isolate_sql(sql, user_id, pid, ds, available_tables)

        # Isolation Check after normalization
        if f"user_id = '{user_id}'" not in qualified_sql and f"user_id='{user_id}'" not in qualified_sql:
            return (
                f"Error: Security violation. Query must include 'WHERE user_id = '{user_id}'' to ensure data isolation."
            )

        # 2. Automatic Dry Run Guardrail (< 500 MB)
        dry_run_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        dry_job = client.query(qualified_sql, job_config=dry_run_config)
        bytes_processed = dry_job.total_bytes_processed or 0
        readable_size = _format_bytes(float(bytes_processed))
        if bytes_processed > 500 * 1024 * 1024:
            return (
                f"Error: Query aborted by SRE Dry-Run guardrail. Estimated scan ({readable_size}) exceeds 500 MB limit. "
                "Please add date filter predicates and select fewer columns."
            )

        log.info(f"🧪 Executing exploratory SQL (Dry-run: {readable_size}): {qualified_sql}")
        query_job = client.query(qualified_sql)
        results = list(query_job.result())

        if not results:
            return "Query executed successfully but returned no results."

        # Convert to list of dicts for the LLM to process (cap at 100 rows to protect context window)
        data = [dict(row) for row in results[:100]]
        return json.dumps(data, default=str)

    except Exception as e:
        log.error(f"❌ Exploratory query failed: {e}")
        return f"Error executing query: {e}"


@tool(args_schema=SQLQueryInput)
def execute_exploratory_query_dry_run(sql: str, user_id: str) -> str:
    """
    Performs a BigQuery 'Dry Run' to estimate the cost/bytes scanned by a query.
    Returns the estimated total bytes processed.
    """
    config = get_config()
    pid = config.get("project_id")
    ds = config.get("dataset_id")

    try:
        client = get_bq_client(pid)
        available_tables = _get_available_tables(client, pid, ds)
        qualified_sql = _qualify_and_isolate_sql(sql, user_id, pid, ds, available_tables)

        if f"user_id = '{user_id}'" not in qualified_sql and f"user_id='{user_id}'" not in qualified_sql:
            return f"Error: Security violation. Query must include 'WHERE user_id = '{user_id}''."

        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        query_job = client.query(qualified_sql, job_config=job_config)

        bytes_processed = query_job.total_bytes_processed or 0
        readable_size = _format_bytes(float(bytes_processed))

        log.info(f"🧪 Dry Run successful: {readable_size} estimated for query.")
        return json.dumps(
            {
                "estimated_bytes_processed": bytes_processed,
                "human_readable_estimate": readable_size,
                "is_efficient": bytes_processed < 100 * 1024 * 1024,
            }
        )
    except Exception as e:
        return f"Dry run failed: {e}"


@tool
def get_bigquery_schema() -> str:
    """
    Returns the table schemas for the Biometric Data Lake.
    Use this to understand available columns before writing a custom SQL query.
    """
    config = get_config()
    pid = config.get("project_id")
    ds = config.get("dataset_id")

    schema_info: dict[str, Any] = {"dataset_id": ds}
    client = get_bq_client(pid)

    try:
        tables = _get_available_tables(client, pid, ds)

        for table_name in tables:
            try:
                table = client.get_table(f"{pid}.{ds}.{table_name}")
                schema_info[table_name] = {f.name: f.field_type for f in table.schema}
            except Exception:
                schema_info[table_name] = "Error retrieving schema."
    except Exception as e:
        schema_info["error"] = f"Error discovering tables: {e}"

    return json.dumps(schema_info)
