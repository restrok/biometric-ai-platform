import json
import logging
from typing import Any

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

log = logging.getLogger(__name__)

# Cache clients per project to reduce initialization overhead
_bq_clients: dict[str, bigquery.Client] = {}


def get_bq_client(project_id: str) -> bigquery.Client:
    """Gets or creates a BigQuery client for the given project ID."""
    global _bq_clients
    if project_id not in _bq_clients:
        # In a real production setup, this client should use a restricted Service Account
        # with only roles/bigquery.dataViewer on the specific dataset.
        _bq_clients[project_id] = bigquery.Client(project=project_id)
    return _bq_clients[project_id]


class SQLQueryInput(BaseModel):
    """Input schema for executing an exploratory SQL query."""

    sql: str = Field(..., description="The complete BigQuery SQL query to execute. MUST be a SELECT statement.")
    user_id: str = Field(..., description="The internal ID of the user (to verify isolation).")


@tool(args_schema=SQLQueryInput)
def execute_exploratory_query(sql: str, user_id: str) -> str:
    """
    Executes a read-only SQL query against the BigQuery data lake.
    Use this tool ONLY when standard analysis tools are insufficient for
    answering complex, multi-domain correlation questions.

    🚨 SECURITY RULES:
    1. MUST contain 'WHERE user_id = {user_id}'.
    2. MUST NOT contain INSERT, UPDATE, DELETE, DROP, or ALTER.
    3. MUST list explicit columns (no SELECT *).
    """
    config = get_config()
    pid = config.get("project_id")

    # 1. Basic Security Validation (Redundant to IAM but good for LLM feedback)
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "MERGE"]
    if any(word in sql.upper() for word in forbidden):
        return "Error: Only SELECT operations are allowed for exploratory analysis."

    if "SELECT *" in sql.upper():
        return (
            "Error: SELECT * is forbidden. Please list explicit columns to ensure cost efficiency and schema stability."
        )

    # Isolation Check
    if f"user_id = '{user_id}'" not in sql and f"user_id='{user_id}'" not in sql:
        return f"Error: Security violation. Query must include 'WHERE user_id = '{user_id}'' to ensure data isolation."

    # 2. Automated Dataset Qualification
    # The LLM often forgets to prefix tables with project.dataset.
    # We automatically discover tables and inject them for robustness.
    ds = config.get("dataset_id")
    qualified_sql = sql

    try:
        client = get_bq_client(pid)
        # Dynamic Auto-Discovery of tables in the dataset
        dataset_ref = client.dataset(ds)
        available_tables = [t.table_id for t in client.list_tables(dataset_ref)]

        for table in available_tables:
            # Replace unqualified table names with qualified ones
            if f" {table}" in qualified_sql or f"\n{table}" in qualified_sql:
                qualified_sql = qualified_sql.replace(f" {table}", f" `{pid}.{ds}.{table}`")
                qualified_sql = qualified_sql.replace(f"\n{table}", f"\n`{pid}.{ds}.{table}`")

        log.info(f"🧪 Executing exploratory SQL (Qualified): {qualified_sql}")
        query_job = client.query(qualified_sql)
        results = list(query_job.result())

        if not results:
            return "Query executed successfully but returned no results."

        # Convert to list of dicts for the LLM to process
        data = [dict(row) for row in results]
        return json.dumps(data, default=str)

    except Exception as e:
        log.error(f"❌ Exploratory query failed: {e}")
        return f"Error executing query: {e}"


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
        dataset_ref = client.dataset(ds)
        tables = [t.table_id for t in client.list_tables(dataset_ref)]

        for table_name in tables:
            try:
                table = client.get_table(f"{pid}.{ds}.{table_name}")
                schema_info[table_name] = {f.name: f.field_type for f in table.schema}
            except Exception:
                schema_info[table_name] = "Error retrieving schema."
    except Exception as e:
        schema_info["error"] = f"Error discovering tables: {e}"

    return json.dumps(schema_info)
