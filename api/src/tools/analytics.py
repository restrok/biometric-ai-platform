import logging

import numpy as np
from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

log = logging.getLogger(__name__)


class ActivityID(BaseModel):
    activity_id: str = Field(..., description="The unique ID of the activity to analyze.")
    user_id: str | None = Field(None, description="The ID of the user.")


@tool(args_schema=ActivityID)
def analyze_activity_efficiency(activity_id: str, user_id: str | None = None):
    """
    Performs high-precision physiological analysis in BigQuery.
    Calculates Aerobic Decoupling, Form Efficiency, and Metabolic Cost (HR per Step).
    Returns all available metrics (HR, Power, Cadence, etc.) for trend analysis.
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
            PERCENT_RANK() OVER(ORDER BY timestamp_ms) as total_progress
        FROM `{config["project_id"]}.{dataset}.latest_activity_telemetry`
        WHERE activity_id = '{activity_id}'
        {user_where}
        AND hr_bpm > 0
    ),
    telemetry_stats AS (
        SELECT 
            *,
            PERCENT_RANK() OVER(ORDER BY timestamp_ms) as progress
        FROM telemetry_base
        WHERE total_progress >= 0.15 -- Exclude first 15% (dynamic warmup/stabilization)
    ),
    halves AS (
        SELECT
            AVG(CASE WHEN progress < 0.5 THEN power_w / NULLIF(hr_bpm, 0) END) as eff_first_half,
            AVG(CASE WHEN progress >= 0.5 THEN power_w / NULLIF(hr_bpm, 0) END) as eff_second_half,
            AVG(CASE WHEN progress < 0.5 THEN gct END) as gct_first_half,
            AVG(CASE WHEN progress >= 0.5 THEN gct END) as gct_second_half,
            AVG(vo / NULLIF(sl/10.0, 0)) as avg_oscillation_ratio,
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
        eff_first_half, 
        eff_second_half, 
        gct_first_half,
        gct_second_half,
        avg_oscillation_ratio, 
        hr_per_step, 
        avg_hr, 
        avg_power, 
        avg_cadence, 
        avg_vo, 
        avg_sl, 
        avg_gct 
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
            "avg_cadence": round(row.avg_cadence, 1) if row.avg_cadence is not None else None,
            "hr_per_step": round(row.hr_per_step, 3) if row.hr_per_step is not None else None,
            "aerobic_decoupling_pct": (
                f"{round(row.decoupling_pct, 2)}%"
                if hasattr(row, "decoupling_pct") and row.decoupling_pct is not None
                else "N/A"
            ),
            "efficiency_score": (round(row.eff_first_half, 3) if row.eff_first_half is not None else None),
            "gct_first_half": (round(row.gct_first_half, 1) if row.gct_first_half is not None else None),
            "gct_second_half": (round(row.gct_second_half, 1) if row.gct_second_half is not None else None),
            "oscillation_ratio": (
                round(row.avg_oscillation_ratio, 2) if row.avg_oscillation_ratio is not None else None
            ),
            "avg_gct_ms": round(row.avg_gct, 1) if row.avg_gct is not None else None,
            "avg_stride_length_mm": round(row.avg_sl, 0) if row.avg_sl is not None else None,
        }

        # Manual decoupling calc if BQ output name differs or using SELECT *
        if row.eff_first_half and row.eff_second_half:
            dec = ((row.eff_first_half - row.eff_second_half) / row.eff_first_half) * 100
            summary["aerobic_decoupling_pct"] = f"{round(dec, 2)}%"
            summary["interpretation"] = (
                "Stable" if dec < 5 else "Cardiac Drift Detected" if dec < 10 else "Significant Decoupling"
            )
        else:
            summary["interpretation"] = "Insufficient data for drift analysis"

        log.info(f"✅ Full Efficiency analysis complete for {activity_id}")
        return summary
    except Exception as e:
        log.error(f"❌ Analysis failed: {e}")
        return f"Error during analysis: {e}"


@tool(args_schema=ActivityID)
def analyze_activity_stages(activity_id: str, user_id: str | None = None):
    """
    Analyzes telemetry to split an activity into physiological stages (Intervals/Work vs. Rest).
    Returns granular stats for each stage: HR, Power, Cadence, GCT, and HR per Step.
    """
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]

    user_where = f"AND user_id = '{user_id}'" if user_id else ""

    query = f"""
        SELECT 
            timestamp_ms, 
            hr_bpm, 
            power_w, 
            cadence_spm,
            stride_length_mm,
            vertical_oscillation_cm,
            ground_contact_time_ms,
            temperature_c
        FROM `{config["project_id"]}.{dataset}.latest_activity_telemetry` 
        WHERE activity_id = '{activity_id}' 
        {user_where}
        ORDER BY timestamp_ms ASC
    """

    try:
        df = client.query(query).to_dataframe()
        if df.empty:
            return "No telemetry found for stage analysis."

        # Dynamic Thresholding: Use 90% of the session's mean power as the 'work' baseline
        # This adapts to recovery runs vs. interval sessions.
        session_avg_power = df[df["power_w"] > 0]["power_w"].mean()
        threshold = session_avg_power * 0.9 if not np.isnan(session_avg_power) else 220

        log.info(
            f"📊 Activity {activity_id} analysis: Session Avg Power={session_avg_power:.1f}W, Dynamic Threshold={threshold:.1f}W"
        )

        # Smoothing & Thresholding
        df["power_smooth"] = df["power_w"].rolling(window=10, center=True).mean().fillna(df["power_w"])
        df["is_work"] = df["power_smooth"] > threshold
        df["state_change"] = df["is_work"] != df["is_work"].shift(1)
        df["stage_id"] = df["state_change"].cumsum()

        stages = []
        for _, group in df.groupby("stage_id"):
            is_work = group["is_work"].iloc[0]
            duration_sec = (group["timestamp_ms"].max() - group["timestamp_ms"].min()) / 1000

            if duration_sec < 15:
                continue

            hr_step = (group["hr_bpm"] / group["cadence_spm"].replace(0, np.nan)).mean()

            stage_summary = {
                "type": "Work" if is_work else "Rest/Warmup/Cooldown",
                "duration_sec": round(duration_sec, 1),
                "avg_hr": round(group["hr_bpm"].mean(), 1) if not group["hr_bpm"].empty else None,
                "avg_power": round(group["power_w"].mean(), 1) if not group["power_w"].empty else None,
                "avg_cadence": round(group["cadence_spm"].mean(), 1) if not group["cadence_spm"].empty else None,
                "hr_per_step": round(hr_step, 3) if not np.isnan(hr_step) else None,
            }

            # Optional metrics - only include if they have data
            metrics_map = {
                "ground_contact_time_ms": "avg_gct_ms",
                "stride_length_mm": "avg_stride_mm",
                "vertical_oscillation_cm": "avg_oscillation_cm",
                "temperature_c": "avg_temp_c",
            }

            for col, key in metrics_map.items():
                if col in group and not group[col].isnull().all():
                    stage_summary[key] = round(group[col].mean(), 1)

            stages.append(stage_summary)

        log.info(f"✅ Full Stage analysis complete for {activity_id}")
        return stages
    except Exception as e:
        log.error(f"❌ Stage analysis failed: {e}")
        return f"Error during stage analysis: {e}"
