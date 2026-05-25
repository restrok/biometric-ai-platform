import logging
from typing import Literal

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config
from src.utils.firestore import update_user_profile

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
    Updates the user's custom heart rate zones.
    Source of truth is Firestore for low-latency agent access.
    Also updates BigQuery for historical and analytical consistency.
    """
    config = get_config()
    project_id = config["project_id"]
    dataset = config["dataset_id"]
    user_id = user_id or "fsirio"

    # 1. Update Firestore (OLTP - Source of Truth for Agent)
    try:
        zone_data = {
            "custom_zones": {
                "z1_max": z1_max,
                "z2_max": z2_max,
                "z3_max": z3_max,
                "z4_max": z4_max,
            },
            "updated_at": "auto" # update_user_profile could handle this or we pass it
        }
        update_user_profile(user_id, zone_data)
        log.info(f"✅ Firestore: Updated zones for {user_id}")
    except Exception as e:
        log.warning(f"⚠️ Firestore zone update failed: {e}")

    # 2. Update BigQuery (OLAP - Historical consistency)
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.user_profile"

    query = f"""
        UPDATE `{table_id}`
        SET 
            custom_z1_max = {z1_max},
            custom_z2_max = {z2_max},
            custom_z3_max = {z3_max},
            custom_z4_max = {z4_max},
            updated_at = CURRENT_DATETIME()
        WHERE user_id = '{user_id}'
    """

    try:
        client.query(query).result()
        log.info(f"✅ BigQuery: Updated zones for {user_id}")
        return f"Successfully updated custom zones: Z1:{z1_max}, Z2:{z2_max}, Z3:{z3_max}, Z4:{z4_max}."
    except Exception as e:
        log.error(f"❌ BigQuery zone update failed: {e}")
        return f"Updated zones in Firestore, but BigQuery sync failed: {e}"


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
    Logs the user's subjective health status.
    Source of truth for immediate agent context is Firestore.
    Historical logs are maintained in BigQuery.
    """
    config = get_config()
    project_id = config["project_id"]
    dataset = config["dataset_id"]
    user_id = user_id or "fsirio"

    from datetime import date
    target_date = status_date if status_date else date.today().isoformat()

    # 1. Update Firestore (Immediate State)
    try:
        health_data = {
            "latest_health_status": {
                "date": target_date,
                "feeling": feeling,
                "notes": notes,
                "fatigue_level": fatigue_level,
                "injury_notes": injury_notes,
            }
        }
        update_user_profile(user_id, health_data)
        log.info(f"✅ Firestore: Logged health status for {user_id}")
    except Exception as e:
        log.warning(f"⚠️ Firestore health log failed: {e}")

    # 2. Update BigQuery (Historical Log)
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.user_health_status"

    # Merge condition must include user_id if present
    on_clause = f"T.date = S.date AND T.user_id = '{user_id}'"

    # Escape single quotes
    safe_feeling = feeling.replace("'", "''")
    safe_notes = notes.replace("'", "''") if notes else None
    safe_injury = injury_notes.replace("'", "''") if injury_notes else None

    # We use a MERGE (UPSERT) to ensure one entry per day
    query = f"""
        MERGE `{table_id}` T
        USING (SELECT DATE '{target_date}' as date) S
        ON {on_clause}
        WHEN MATCHED THEN
            UPDATE SET 
                feeling = '{safe_feeling}',
                notes = {f"'{safe_notes}'" if safe_notes else "NULL"},
                fatigue_level = {fatigue_level if fatigue_level is not None else "NULL"},
                injury_notes = {f"'{safe_injury}'" if safe_injury else "NULL"},
                updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (date, feeling, notes, fatigue_level, injury_notes, updated_at, user_id)
            VALUES ('{target_date}', '{safe_feeling}', {f"'{safe_notes}'" if safe_notes else "NULL"}, {fatigue_level if fatigue_level is not None else "NULL"}, {f"'{safe_injury}'" if safe_injury else "NULL"}, CURRENT_TIMESTAMP(), '{user_id}')
    """

    try:
        client.query(query).result()
        log.info(f"✅ BigQuery: Logged health status for {user_id}")
        return f"Successfully logged health status for {target_date}: {feeling}."
    except Exception as e:
        log.error(f"❌ BigQuery health log failed: {e}")
        return f"Logged health status in Firestore, but BigQuery sync failed: {e}"


class ProactiveConfigInput(BaseModel):
    enabled: bool | None = Field(None, description="Whether to enable proactive coaching alerts and auto-sync.")
    interval_hours: int | None = Field(
        None, description="Frequency of auto-sync in hours (e.g., 6). Set to 0 to use a specific daily hour."
    )
    target_hour: int | None = Field(None, description="Specific daily hour (0-23) for sync if interval_hours is 0.")
    user_id: str | None = Field(None, description="The ID of the user.")


@tool(args_schema=ProactiveConfigInput)
def configure_proactive_coaching(
    enabled: bool | None = None,
    interval_hours: int | None = None,
    target_hour: int | None = None,
    user_id: str | None = None,
):
    """
    Configures the proactive coaching engine settings.
    Use this tool when the user wants to enable/disable the proactive coach,
    change how often it syncs (interval), or set a specific time for the daily sync.
    """
    # Note: In a production multi-tenant environment, these would be in a DB per user.
    # For now, we update the environment/env file which affects the global background loop.
    env_path = ".env"
    try:
        with open(env_path) as f:
            lines = f.readlines()

        new_lines = []
        updates = {}
        if enabled is not None:
            updates["ENABLE_PROACTIVE"] = str(enabled).lower()
        if interval_hours is not None:
            updates["PROACTIVE_INTERVAL_HOURS"] = str(interval_hours)
        if target_hour is not None:
            updates["PROACTIVE_HOUR"] = str(target_hour)

        found_keys = set()
        for line in lines:
            key_found = False
            for k, v in updates.items():
                if line.startswith(f"{k}="):
                    new_lines.append(f"{k}={v}\n")
                    found_keys.add(k)
                    key_found = True
                    break
            if not key_found:
                new_lines.append(line)

        for k, v in updates.items():
            if k not in found_keys:
                new_lines.append(f"{k}={v}\n")

        with open(env_path, "w") as f:
            f.writelines(new_lines)

        # Also update os.environ for immediate effect in the current process
        for k, v in updates.items():
            import os

            os.environ[k] = v

        log.info(f"✅ Proactive configuration updated: {updates}")
        return f"Successfully updated proactive coaching configuration: {updates}. The changes will take effect in the next sync cycle."
    except Exception as e:
        log.error(f"❌ Failed to update proactive configuration: {e}")
        return f"Error updating proactive configuration: {e}"


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
    Adds or updates a user goal.
    Source of truth for agent context is Firestore.
    Analytical history is maintained in BigQuery.
    """
    config = get_config()
    project_id = config["project_id"]
    dataset = config["dataset_id"]
    user_id = user_id or "fsirio"

    import uuid
    from datetime import datetime

    goal_id = str(uuid.uuid4())[:8]
    created_at = datetime.utcnow().isoformat()

    # 1. Update Firestore (Current Goals)
    try:
        # We store goals in a sub-collection or a list in the profile. 
        # For simplicity in retrieval, a list 'active_goals' in the profile works well for small counts.
        profile = get_user_profile(user_id)
        current_goals = profile.get("active_goals", [])
        
        new_goal = {
            "id": goal_id,
            "target_date": target_date,
            "goal_type": goal_type,
            "target_value": target_value,
            "description": description,
            "status": status
        }
        
        # Replace if same type/date exists
        updated_goals = [g for m in [new_goal] for g in current_goals if not (g["target_date"] == m["target_date"] and g["goal_type"] == m["goal_type"])]
        updated_goals.append(new_goal)
        
        update_user_profile(user_id, {"active_goals": updated_goals})
        log.info(f"✅ Firestore: Managed goal {goal_type} for {user_id}")
    except Exception as e:
        log.warning(f"⚠️ Firestore goal management failed: {e}")

    # 2. Update BigQuery (Historical/OLAP)
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.user_goals"

    # Escape single quotes
    safe_desc = description.replace("'", "''") if description else None
    safe_val = target_value.replace("'", "''")

    on_clause = f"T.target_date = S.target_date AND T.goal_type = S.goal_type AND T.user_id = '{user_id}'"

    query = f"""
        MERGE `{table_id}` T
        USING (SELECT DATE '{target_date}' as target_date, '{goal_type}' as goal_type) S
        ON {on_clause}
        WHEN MATCHED THEN
            UPDATE SET 
                target_value = '{safe_val}',
                description = {f"'{safe_desc}'" if safe_desc else "NULL"},
                status = '{status}'
        WHEN NOT MATCHED THEN
            INSERT (id, created_at, target_date, goal_type, target_value, description, status, user_id)
            VALUES ('{goal_id}', '{created_at}', '{target_date}', '{goal_type}', '{safe_val}', {f"'{safe_desc}'" if safe_desc else "NULL"}, '{status}', '{user_id}')
    """

    try:
        client.query(query).result()
        log.info(f"✅ BigQuery: Managed goal {goal_type} for {user_id}")
        return f"Successfully saved goal: {goal_type} for {target_date} with target {target_value}."
    except Exception as e:
        log.error(f"❌ BigQuery goal management failed: {e}")
        return f"Saved goal in Firestore, but BigQuery sync failed: {e}"


class CalibrationMarkerInput(BaseModel):
    marker_type: str = Field(..., description="Type of marker (e.g., 'ac_ratio_red_line', 'adaptation_peak').")
    marker_value: float = Field(..., description="Numerical value of the marker.")
    context: str | None = Field(None, description="Context or reason for this marker.")
    user_id: str | None = Field(None, description="The ID of the user.")


@tool(args_schema=CalibrationMarkerInput)
def save_calibration_marker(
    marker_type: str,
    marker_value: float,
    context: str | None = None,
    user_id: str | None = None,
):
    """
    Saves a Personal Calibration Profile (PCP) marker.
    Source of truth for agent context is Firestore.
    Analytical history is maintained in BigQuery.
    """
    config = get_config()
    project_id = config["project_id"]
    dataset = config["dataset_id"]
    user_id = user_id or "fsirio"

    # 1. Update Firestore (PCP Markers)
    try:
        profile = get_user_profile(user_id)
        current_pcp = profile.get("personal_calibration_profile", {})
        current_pcp[marker_type] = {
            "value": marker_value,
            "context": context,
            "updated_at": datetime.utcnow().isoformat()
        }
        update_user_profile(user_id, {"personal_calibration_profile": current_pcp})
        log.info(f"✅ Firestore: Saved calibration marker {marker_type} for {user_id}")
    except Exception as e:
        log.warning(f"⚠️ Firestore calibration marker save failed: {e}")

    # 2. Update BigQuery (Analytical Lake)
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.user_calibration_profile"

    # Merge on marker_type and user_id to update existing markers
    on_clause = f"T.marker_type = S.marker_type AND T.user_id = '{user_id}'"

    # Escape single quotes in context to avoid SQL errors
    safe_context = context.replace("'", "''") if context else None

    query = f"""
        MERGE `{table_id}` T
        USING (SELECT '{marker_type}' as marker_type) S
        ON {on_clause}
        WHEN MATCHED THEN
            UPDATE SET 
                marker_value = {marker_value},
                context = {f"'{safe_context}'" if safe_context else "NULL"},
                updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (user_id, marker_type, marker_value, context, created_at, updated_at)
            VALUES ('{user_id}', '{marker_type}', {marker_value}, {f"'{safe_context}'" if safe_context else "NULL"}, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
    """

    try:
        client.query(query).result()
        log.info(f"✅ BigQuery: Saved calibration marker {marker_type} for {user_id}")
        return f"Successfully saved calibration marker: {marker_type}={marker_value}."
    except Exception as e:
        log.error(f"❌ BigQuery calibration marker save failed: {e}")
        return f"Saved marker in Firestore, but BigQuery sync failed: {e}"
