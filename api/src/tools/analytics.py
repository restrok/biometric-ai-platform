import logging

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

log = logging.getLogger(__name__)


class ActivityID(BaseModel):
    activity_id: str = Field(..., description="The unique ID of the activity to analyze.")


@tool(args_schema=ActivityID)
def analyze_activity_efficiency(activity_id: str):
    """
    Performs high-precision physiological analysis in BigQuery.
    Calculates Aerobic Decoupling (drift in efficiency between 1st and 2nd half)
    and Form Efficiency ratios. Use this to determine if a user's Aerobic Threshold
    is stable or if they are experiencing fatigue.
    """
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]

    # Advanced SQL: Uses Window Functions to split the run and calculate ratios
    query = f"""
    WITH telemetry_stats AS (
        SELECT 
            hr_bpm, 
            power_w, 
            vertical_oscillation_cm as vo,
            stride_length_mm as sl,
            PERCENT_RANK() OVER(ORDER BY timestamp_ms) as progress
        FROM `{config["project_id"]}.{dataset}.latest_activity_telemetry`
        WHERE activity_id = '{activity_id}'
        AND hr_bpm > 0
    ),
    halves AS (
        SELECT
            AVG(CASE WHEN progress < 0.5 THEN power_w / NULLIF(hr_bpm, 0) END) as eff_first_half,
            AVG(CASE WHEN progress >= 0.5 THEN power_w / NULLIF(hr_bpm, 0) END) as eff_second_half,
            AVG(vo / NULLIF(sl/10.0, 0)) as avg_oscillation_ratio, -- Vertical Ratio (lower is better)
            AVG(hr_bpm) as avg_hr
        FROM telemetry_stats
    )
    SELECT 
        avg_hr,
        eff_first_half,
        eff_second_half,
        ((eff_first_half - eff_second_half) / NULLIF(eff_first_half, 0)) * 100 as decoupling_pct,
        avg_oscillation_ratio
    FROM halves
    """

    try:
        query_job = client.query(query)
        results = list(query_job.result())
        if not results:
            return "No detailed telemetry found for this activity ID to perform analysis."

        row = results[0]
        summary = {
            "avg_hr": round(row.avg_hr, 1),
            "aerobic_decoupling_pct": f"{round(row.decoupling_pct, 2)}%",
            "efficiency_score": round(row.eff_first_half, 3),
            "oscillation_ratio": round(row.avg_oscillation_ratio, 2),
            "interpretation": (
                "Stable"
                if row.decoupling_pct < 5
                else "Cardiac Drift Detected (Fatigue/Under-fueled)"
                if row.decoupling_pct < 10
                else "Significant Decoupling (High Fatigue/Cardiac Stress)"
            ),
        }
        log.info(f"✅ BigQuery Analysis complete for {activity_id}")
        return summary
    except Exception as e:
        log.error(f"❌ BigQuery Analysis failed: {e}")
        return f"Error during analysis: {e}"
