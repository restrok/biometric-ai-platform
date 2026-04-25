import logging

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


@tool(args_schema=ZoneUpdate)
def update_user_zones(z1_max: int, z2_max: int, z3_max: int, z4_max: int):
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

    # We update the first row found (platform currently supports single user)
    query = f"""
        UPDATE `{table_id}`
        SET 
            custom_z1_max = {z1_max},
            custom_z2_max = {z2_max},
            custom_z3_max = {z3_max},
            custom_z4_max = {z4_max},
            updated_at = CURRENT_TIMESTAMP()
        WHERE TRUE
    """

    try:
        query_job = client.query(query)
        query_job.result()
        log.info(
            f"✅ Successfully updated custom zones in BigQuery: Z1:{z1_max}, Z2:{z2_max}, Z3:{z3_max}, Z4:{z4_max}"
        )
        return f"Successfully updated custom zones: Z1:{z1_max}, Z2:{z2_max}, Z3:{z3_max}, Z4:{z4_max}."
    except Exception as e:
        log.error(f"❌ Failed to update custom zones: {e}")
        return f"Error updating custom zones: {e}"
