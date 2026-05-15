"""Tools for performing physiological analysis on activity telemetry."""

import logging
from typing import Any

import numpy as np
from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

# Configure logging
log = logging.getLogger(__name__)


class ActivityID(BaseModel):
    """Input schema for activity analysis tools."""

    activity_id: str = Field(
        ..., description="The unique ID of the activity to analyze."
    )
    user_id: str | None = Field(None, description="The ID of the user.")


@tool(args_schema=ActivityID)
def analyze_activity_efficiency(
    activity_id: str, user_id: str | None = None
) -> dict[str, Any] | str:
    """Performs high-precision physiological analysis in BigQuery.

    Calculates Aerobic Decoupling, Form Efficiency, and Metabolic Cost (HR per Step).
    Returns all available metrics (HR, Power, Cadence, BB, Vertical Dynamics)
    for trend analysis.

    Args:
        activity_id: The unique ID of the activity to analyze.
        user_id: The ID of the user.

    Returns:
        A dictionary containing the efficiency analysis results, or an error message.
    """
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]

    user_where = f"AND user_id = '{user_id}'" if user_id else ""

    query = f"""
    WITH telemetry_base AS (
        SELECT 
            timestamp_ms,
            hr_bpm, 
            power_w, 
            cadence_spm,
            vertical_oscillation_cm as vo,
            stride_length_mm as sl,
            ground_contact_time_ms as gct,
            vertical_ratio as vr,
            vertical_speed as vs,
            body_battery as bb,
            gap_mps as gap,
            PERCENT_RANK() OVER(ORDER BY timestamp_ms) as total_progress
        FROM `{config["project_id"]}.{dataset}.latest_activity_telemetry`
        WHERE activity_id = '{activity_id}'
        {user_where}
        AND hr_bpm > 0
    ),
    telemetry_stats AS (
        SELECT 
            timestamp_ms, hr_bpm, power_w, cadence_spm, vo, sl, gct, vr, vs, bb, gap,
            PERCENT_RANK() OVER(ORDER BY timestamp_ms) as progress
        FROM telemetry_base
        WHERE total_progress >= 0.15 -- Exclude first 15% (warmup)
    ),
    halves AS (
        SELECT
            AVG(CASE WHEN progress < 0.5 THEN power_w / NULLIF(hr_bpm, 0) END) as eff_first_half,
            AVG(CASE WHEN progress >= 0.5 THEN power_w / NULLIF(hr_bpm, 0) END) as eff_second_half,
            AVG(CASE WHEN progress < 0.5 THEN gct END) as gct_first_half,
            AVG(CASE WHEN progress >= 0.5 THEN gct END) as gct_second_half,
            MAX(bb) - MIN(bb) as total_battery_drain,
            AVG(vr) as avg_vertical_ratio,
            AVG(vs) as avg_vertical_speed,
            AVG(gap) as avg_gap,
            AVG(hr_bpm / NULLIF(cadence_spm, 0)) as hr_per_step,
            AVG(hr_bpm) as avg_hr,
            AVG(power_w) as avg_power,
            AVG(cadence_spm) as avg_cadence,
            AVG(vo) as avg_vo,
            AVG(sl) as avg_sl,
            AVG(gct) as avg_gct
        FROM telemetry_stats
    )
    SELECT 
        eff_first_half, eff_second_half, gct_first_half, gct_second_half, 
        total_battery_drain, avg_vertical_ratio, avg_vertical_speed, avg_gap, 
        hr_per_step, avg_hr, avg_power, avg_cadence, avg_vo, avg_sl, avg_gct 
    FROM halves
    """

    try:
        query_job = client.query(query)
        results = list(query_job.result())
        if not results:
            return "No detailed telemetry found for this activity ID."

        row = results[0]

        summary = {
            "avg_hr": round(row.avg_hr, 1) if row.avg_hr is not None else None,
            "avg_power": round(row.avg_power, 1) if row.avg_power is not None else None,
            "avg_cadence": round(row.avg_cadence, 1)
            if row.avg_cadence is not None
            else None,
            "hr_per_step": round(row.hr_per_step, 3)
            if row.hr_per_step is not None
            else None,
            "body_battery_drain": int(row.total_battery_drain)
            if row.total_battery_drain is not None
            else None,
            "avg_vertical_ratio_pct": round(row.avg_vertical_ratio, 2)
            if row.avg_vertical_ratio is not None
            else None,
            "avg_vertical_speed_mps": round(row.avg_vertical_speed, 3)
            if row.avg_vertical_speed is not None
            else None,
            "efficiency_score": (
                round(row.eff_first_half, 3) if row.eff_first_half is not None else None
            ),
            "gct_first_half": (
                round(row.gct_first_half, 1) if row.gct_first_half is not None else None
            ),
            "gct_second_half": (
                round(row.gct_second_half, 1)
                if row.gct_second_half is not None
                else None
            ),
            "avg_gct_ms": round(row.avg_gct, 1) if row.avg_gct is not None else None,
            "avg_stride_length_mm": round(row.avg_sl, 0)
            if row.avg_sl is not None
            else None,
        }

        if row.eff_first_half and row.eff_second_half:
            dec = ((row.eff_first_half - row.eff_second_half) / row.eff_first_half) * 100
            summary["aerobic_decoupling_pct"] = f"{round(dec, 2)}%"
            summary["interpretation"] = (
                "Stable"
                if dec < 5
                else "Cardiac Drift Detected"
                if dec < 10
                else "Significant Decoupling"
            )

        log.info(f"✅ Full Efficiency analysis complete for {activity_id}")
        return summary
    except Exception as e:
        log.error(f"❌ Analysis failed: {e}")
        return f"Error during analysis: {e}"


@tool(args_schema=ActivityID)
def analyze_activity_stages(
    activity_id: str, user_id: str | None = None
) -> list[dict[str, Any]] | str:
    """Analyzes telemetry to split an activity into physiological stages.

    Splits by Intervals/Work vs. Rest. Returns granular stats for each stage
    including HR, Power, Cadence, GCT, Vertical Dynamics, and Body Battery.

    Args:
        activity_id: The unique ID of the activity to analyze.
        user_id: The ID of the user.

    Returns:
        A list of dictionaries containing the stage analysis results,
        or an error message.
    """
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]

    user_where = f"AND user_id = '{user_id}'" if user_id else ""

    query = f"""
        SELECT 
            timestamp_ms, hr_bpm, power_w, cadence_spm,
            stride_length_mm, vertical_oscillation_cm, ground_contact_time_ms,
            vertical_ratio, vertical_speed, body_battery, temperature_c, gap_mps
        FROM `{config["project_id"]}.{dataset}.latest_activity_telemetry` 
        WHERE activity_id = '{activity_id}' 
        {user_where}
        ORDER BY timestamp_ms ASC
    """

    try:
        df = client.query(query).to_dataframe()
        if df.empty:
            return "No telemetry found for stage analysis."

        session_avg_power = df[df["power_w"] > 0]["power_w"].mean()
        threshold = session_avg_power * 0.9 if not np.isnan(session_avg_power) else 180

        # Smoothing & Thresholding
        df["power_smooth"] = (
            df["power_w"].rolling(window=10, center=True).mean().fillna(df["power_w"])
        )
        df["is_work"] = df["power_smooth"] > threshold
        df["state_change"] = df["is_work"] != df["is_work"].shift(1)
        df["stage_id"] = df["state_change"].cumsum()

        stages = []
        for _, group in df.groupby("stage_id"):
            is_work = group["is_work"].iloc[0]
            duration_sec = (
                group["timestamp_ms"].max() - group["timestamp_ms"].min()
            ) / 1000

            if duration_sec < 10:
                continue

            bb_drop = group["body_battery"].max() - group["body_battery"].min()

            stage_summary = {
                "type": "Work" if is_work else "Rest/Warmup/Cooldown",
                "duration_sec": round(duration_sec, 1),
                "avg_hr": round(group["hr_bpm"].mean(), 1),
                "max_hr": int(group["hr_bpm"].max()),
                "avg_power": round(group["power_w"].mean(), 1),
                "max_power": int(group["power_w"].max()),
                "avg_cadence": round(group["cadence_spm"].mean(), 1),
                "bb_drop": int(bb_drop) if not np.isnan(bb_drop) else 0,
            }

            metrics_map = {
                "ground_contact_time_ms": "avg_gct_ms",
                "stride_length_mm": "avg_stride_mm",
                "vertical_oscillation_cm": "avg_vosc_cm",
                "vertical_ratio": "avg_vratio_pct",
                "temperature_c": "avg_temp_c",
                "gap_mps": "avg_gap_mps",
            }

            for col, key in metrics_map.items():
                if col in group and not group[col].isnull().all():
                    stage_summary[key] = round(group[col].mean(), 2)

            stages.append(stage_summary)

        return stages
    except Exception as e:
        log.error(f"❌ Stage analysis failed: {e}")
        return f"Error during stage analysis: {e}"
