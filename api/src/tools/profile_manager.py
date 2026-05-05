import logging
from typing import Literal

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

log = logging.getLogger(__name__)


class ZoneUpdate(BaseModel):
    z1_max: int = Field(..., description="Max HR for Zone 1")
    z2_max: int = Field(..., description="Max HR for Zone 2")
    z3_max: int = Field(..., description="Max HR for Zone 3")
    z4_max: int = Field(..., description="Max HR for Zone 4")
    user_id: str | None = Field(None, description="The ID of the user.")


@tool(args_schema=ZoneUpdate)
def update_user_zones(z1_max: int, z2_max: int, z3_max: int, z4_max: int, user_id: str | None = None):
    """
    Updates the user's custom heart rate zones in BigQuery.
    Use this tool whenever you analyze telemetry and determine that the user's
    physiological zones have shifted or need correction.
    """
    config = get_config()
    project_id = config["project_id"]
    dataset = config["dataset_id"]

    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.user_profile"

    where_clause = f"WHERE user_id = '{user_id}'" if user_id else "WHERE TRUE"

    query = f"""
        UPDATE `{table_id}`
        SET 
            custom_z1_max = {z1_max},
            custom_z2_max = {z2_max},
            custom_z3_max = {z3_max},
            custom_z4_max = {z4_max},
            updated_at = CURRENT_TIMESTAMP()
        {where_clause}
    """

    try:
        query_job = client.query(query)
        query_job.result()
        log.info(
            f"✅ Successfully updated custom zones in BigQuery for {user_id or 'default'}: Z1:{z1_max}, Z2:{z2_max}, Z3:{z3_max}, Z4:{z4_max}"
        )
        return f"Successfully updated custom zones: Z1:{z1_max}, Z2:{z2_max}, Z3:{z3_max}, Z4:{z4_max}."
    except Exception as e:
        log.error(f"❌ Failed to update custom zones: {e}")
        return f"Error updating custom zones: {e}"


class HealthStatusInput(BaseModel):
    feeling: str = Field(..., description="Overall subjective feeling (e.g., 'Sick', 'Tired', 'Injured', 'Great')")
    notes: str | None = Field(None, description="Detailed notes about the user's condition.")
    fatigue_level: int | None = Field(None, description="General fatigue level on a 1-10 scale.")
    injury_notes: str | None = Field(None, description="Notes about any physical discomfort or injuries.")
    status_date: str | None = Field(None, description="Date of the status (YYYY-MM-DD). Defaults to today.")
    user_id: str | None = Field(None, description="The ID of the user.")


@tool(args_schema=HealthStatusInput)
def log_health_status(
    feeling: str,
    notes: str | None = None,
    fatigue_level: int | None = None,
    injury_notes: str | None = None,
    status_date: str | None = None,
    user_id: str | None = None,
):
    """
    Logs the user's subjective health status and physical feeling into BigQuery.
    Use this tool whenever the user reports feeling unwell, injured, tired, or particularly strong.
    This ensures that the AI coach can persist and retrieve this context in future sessions.
    """
    config = get_config()
    project_id = config["project_id"]
    dataset = config["dataset_id"]

    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.user_health_status"

    from datetime import date

    target_date = status_date if status_date else date.today().isoformat()

    # Merge condition must include user_id if present
    on_clause = "T.date = S.date"
    if user_id:
        on_clause += f" AND T.user_id = '{user_id}'"

    # We use a MERGE (UPSERT) to ensure one entry per day
    query = f"""
        MERGE `{table_id}` T
        USING (SELECT DATE '{target_date}' as date) S
        ON {on_clause}
        WHEN MATCHED THEN
            UPDATE SET 
                feeling = '{feeling}',
                notes = {f"'{notes}'" if notes else "NULL"},
                fatigue_level = {fatigue_level if fatigue_level is not None else "NULL"},
                injury_notes = {f"'{injury_notes}'" if injury_notes else "NULL"},
                updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (date, feeling, notes, fatigue_level, injury_notes, updated_at, user_id)
            VALUES ('{target_date}', '{feeling}', {f"'{notes}'" if notes else "NULL"}, {fatigue_level if fatigue_level is not None else "NULL"}, {f"'{injury_notes}'" if injury_notes else "NULL"}, CURRENT_TIMESTAMP(), {f"'{user_id}'" if user_id else "NULL"})
    """

    try:
        query_job = client.query(query)
        query_job.result()
        log.info(f"✅ Successfully logged health status for {target_date} (user: {user_id}): {feeling}")
        return f"Successfully logged health status for {target_date}: {feeling}."
    except Exception as e:
        log.error(f"❌ Failed to log health status: {e}")
        return f"Error logging health status: {e}"


class GoalInput(BaseModel):
    target_date: str = Field(..., description="Target date for the goal (YYYY-MM-DD).")
    goal_type: str = Field(..., description="Type of goal (e.g., 'race', 'volume', 'weight', 'pace').")
    target_value: str = Field(..., description="Target value (e.g., '50:00', '100km', '75kg', '5:00 min/km').")
    description: str | None = Field(None, description="Detailed description of the goal.")
    status: Literal["active", "completed", "abandoned"] = Field("active", description="Current status of the goal.")
    user_id: str | None = Field(None, description="The ID of the user.")


@tool(args_schema=GoalInput)
def manage_goals(
    target_date: str,
    goal_type: str,
    target_value: str,
    description: str | None = None,
    status: str = "active",
    user_id: str | None = None,
):
    """
    Adds or updates a user goal in BigQuery.
    Use this tool when the user mentions a specific target, like a race date or a weight goal.
    This allows the coach to keep track of long-term objectives.
    """
    config = get_config()
    project_id = config["project_id"]
    dataset = config["dataset_id"]

    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.user_goals"

    import uuid
    from datetime import datetime

    goal_id = str(uuid.uuid4())[:8]
    created_at = datetime.utcnow().isoformat()

    # We use a MERGE to avoid duplicate active goals of the same type for the same date
    on_clause = "T.target_date = S.target_date AND T.goal_type = S.goal_type"
    if user_id:
        on_clause += f" AND T.user_id = '{user_id}'"

    query = f"""
        MERGE `{table_id}` T
        USING (SELECT DATE '{target_date}' as target_date, '{goal_type}' as goal_type) S
        ON {on_clause}
        WHEN MATCHED THEN
            UPDATE SET 
                target_value = '{target_value}',
                description = {f"'{description}'" if description else "NULL"},
                status = '{status}'
        WHEN NOT MATCHED THEN
            INSERT (id, created_at, target_date, goal_type, target_value, description, status, user_id)
            VALUES ('{goal_id}', '{created_at}', '{target_date}', '{goal_type}', '{target_value}', {f"'{description}'" if description else "NULL"}, '{status}', {f"'{user_id}'" if user_id else "NULL"})
    """

    try:
        query_job = client.query(query)
        query_job.result()
        log.info(f"✅ Successfully managed goal: {goal_type} on {target_date} ({status})")
        return f"Successfully saved goal: {goal_type} for {target_date} with target {target_value}."
    except Exception as e:
        log.error(f"❌ Failed to manage goal: {e}")
        return f"Error managing goal: {e}"
