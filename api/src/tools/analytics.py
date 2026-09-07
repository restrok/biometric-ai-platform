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

    activity_id: str = Field(..., description="The unique ID of the activity to analyze.")
    user_id: str | None = Field(None, description="The ID of the user.")


def _analyze_swim_efficiency(
    activity_id: str,
    user_id: str | None,
    client: bigquery.Client,
    project_id: str,
    dataset: str,
) -> dict[str, Any] | str:
    """Specialized physiological and biomechanical efficiency analysis for swimming activities."""
    user_where = f"AND user_id = '{user_id}'" if user_id else ""

    # 1. Fetch activity summary
    query_summary = f"""
        SELECT 
            name, type, distance_m, duration_sec, moving_duration_sec, elapsed_duration_sec,
            avg_hr, max_hr, min_hr, recovery_hr, avg_swim_cadence, active_lengths,
            avg_strokes_per_length, avg_swolf, pool_length_m, total_strokes,
            moderate_intensity_min, vigorous_intensity_min, is_personal_record, swim_stroke, calories
        FROM `{project_id}.{dataset}.recent_activities`
        WHERE CAST(id AS STRING) = '{activity_id}' {user_where}
        LIMIT 1
    """
    summary_rows = list(client.query(query_summary).result())
    summary_data = dict(summary_rows[0]) if summary_rows else {}

    # 2. Fetch length-level telemetry
    query_lengths = f"""
        SELECT 
            length_index, start_time_gmt, distance_m, duration_sec, avg_speed_mps,
            avg_hr, max_hr, total_strokes, avg_swolf, swim_stroke, pace_per_100m_sec, stroke_rate
        FROM `{project_id}.{dataset}.swim_length_telemetry`
        WHERE activity_id = '{activity_id}' {user_where}
        ORDER BY length_index ASC
    """
    length_rows = [dict(r) for r in client.query(query_lengths).result()]

    # 3. Fetch HR zones
    query_zones = f"""
        SELECT zone_number, secs_in_zone, zone_low_boundary_bpm
        FROM `{project_id}.{dataset}.activity_hr_zones`
        WHERE activity_id = '{activity_id}' {user_where}
        ORDER BY zone_number ASC
    """
    zone_rows = [dict(r) for r in client.query(query_zones).result()]

    if not summary_data and not length_rows:
        return f"No swimming data found for activity ID {activity_id}."

    total_dist = summary_data.get("distance_m") or sum(r.get("distance_m", 0) for r in length_rows)
    total_dur = summary_data.get("duration_sec") or sum(r.get("duration_sec", 0) for r in length_rows)
    moving_dur = summary_data.get("moving_duration_sec")
    total_rest = (total_dur - moving_dur) if (total_dur and moving_dur) else None

    # Length analytics
    swolf_vals = [r["avg_swolf"] for r in length_rows if r.get("avg_swolf") is not None and r["avg_swolf"] > 0]
    avg_swolf = round(float(np.mean(swolf_vals)), 1) if swolf_vals else summary_data.get("avg_swolf")
    min_swolf = round(float(np.min(swolf_vals)), 1) if swolf_vals else None
    max_swolf = round(float(np.max(swolf_vals)), 1) if swolf_vals else None

    # SWOLF Drift / Technical Decoupling (First Half vs Second Half)
    swolf_first_half = None
    swolf_second_half = None
    swolf_drift_pts = None
    swolf_drift_interpretation = "Stable"

    if len(swolf_vals) >= 4:
        half_idx = len(swolf_vals) // 2
        swolf_first_half = round(float(np.mean(swolf_vals[:half_idx])), 1)
        swolf_second_half = round(float(np.mean(swolf_vals[half_idx:])), 1)
        swolf_drift_pts = round(swolf_second_half - swolf_first_half, 1)
        if swolf_drift_pts > 3.0:
            swolf_drift_interpretation = "Technical Degradation / Fatigue Drift"
        elif swolf_drift_pts < -2.0:
            swolf_drift_interpretation = "Negative Split / Efficiency Improved"
        else:
            swolf_drift_interpretation = "Technique Consistency Maintained"

    # Style breakdown
    stroke_styles: dict[str, dict[str, Any]] = {}
    for r in length_rows:
        stroke = r.get("swim_stroke") or "UNKNOWN"
        if stroke not in stroke_styles:
            stroke_styles[stroke] = {"lengths_count": 0, "swolf_list": [], "pace_list": [], "hr_list": []}
        stroke_styles[stroke]["lengths_count"] += 1
        if r.get("avg_swolf"):
            stroke_styles[stroke]["swolf_list"].append(r["avg_swolf"])
        if r.get("pace_per_100m_sec"):
            stroke_styles[stroke]["pace_list"].append(r["pace_per_100m_sec"])
        if r.get("avg_hr"):
            stroke_styles[stroke]["hr_list"].append(r["avg_hr"])

    style_summary = {}
    for stroke, data in stroke_styles.items():
        style_summary[stroke] = {
            "lengths_count": data["lengths_count"],
            "avg_swolf": round(float(np.mean(data["swolf_list"])), 1) if data["swolf_list"] else None,
            "avg_pace_100m_sec": round(float(np.mean(data["pace_list"])), 1) if data["pace_list"] else None,
            "avg_hr": round(float(np.mean(data["hr_list"])), 1) if data["hr_list"] else None,
        }

    # HR Zones mapping
    total_zone_secs = sum(z.get("secs_in_zone", 0) for z in zone_rows) or 1.0
    zones_summary = [
        {
            "zone": z.get("zone_number"),
            "seconds": round(z.get("secs_in_zone", 0), 1),
            "pct": f"{round((z.get('secs_in_zone', 0) / total_zone_secs) * 100, 1)}%",
            "low_boundary_bpm": z.get("zone_low_boundary_bpm"),
        }
        for z in zone_rows
    ]

    # 4. Sport-Specific Swimming Heart Rate Zones Evaluation
    from src.utils.firestore import get_user_profile
    from src.utils.physiology import calculate_sport_hr_zones

    swim_zones = None
    swim_intensity_classification = "Standard Endurance"
    if user_id:
        try:
            profile = get_user_profile(user_id)
            sport_zones_dict = profile.get("sport_zones", {})
            if "swimming" in sport_zones_dict:
                swim_zones = sport_zones_dict["swimming"]
            else:
                running_base = sport_zones_dict.get("running") or profile.get("custom_zones")
                max_hr_val = profile.get("max_hr")
                resting_hr_val = profile.get("resting_hr")
                derived_zones = calculate_sport_hr_zones(
                    running_zones=running_base,
                    max_hr=float(max_hr_val) if max_hr_val else None,
                    resting_hr=float(resting_hr_val) if resting_hr_val else None,
                    sport="swimming",
                )
                swim_zones = derived_zones.model_dump()

            if summary_data.get("avg_hr") and swim_zones:
                s_avg_hr = float(summary_data["avg_hr"])
                z2_m = float(swim_zones["z2_max"])
                z4_m = float(swim_zones["z4_max"])
                if s_avg_hr <= z2_m:
                    swim_intensity_classification = (
                        f"Zone 2 Aerobic Base (Avg HR {s_avg_hr} bpm <= Swim AeT {z2_m} bpm)"
                    )
                elif s_avg_hr <= z4_m:
                    swim_intensity_classification = (
                        f"Zone 3-4 Threshold / Tempo (Avg HR {s_avg_hr} bpm between {z2_m}-{z4_m} bpm)"
                    )
                else:
                    swim_intensity_classification = (
                        f"Zone 5 High Intensity / Anaerobic (Avg HR {s_avg_hr} bpm > Swim AnT {z4_m} bpm)"
                    )
        except Exception as e:
            log.warning(f"Could not load swimming zones for {user_id}: {e}")

    paces = [r["pace_per_100m_sec"] for r in length_rows if r.get("pace_per_100m_sec")]
    best_pace = round(float(np.min(paces)), 1) if paces else None
    avg_pace = round(float(np.mean(paces)), 1) if paces else None

    result = {
        "activity_type": summary_data.get("type", "lap_swimming"),
        "total_distance_m": total_dist,
        "active_lengths": summary_data.get("active_lengths") or len(length_rows),
        "pool_length_m": summary_data.get("pool_length_m", 25.0),
        "duration_sec": total_dur,
        "moving_duration_sec": moving_dur,
        "total_rest_sec": round(total_rest, 1) if total_rest is not None else None,
        "avg_hr": summary_data.get("avg_hr"),
        "max_hr": summary_data.get("max_hr"),
        "min_hr": summary_data.get("min_hr"),
        "recovery_hr_bpm": summary_data.get("recovery_hr"),
        "avg_swolf": avg_swolf,
        "best_swolf": min_swolf,
        "max_swolf": max_swolf,
        "swolf_first_half": swolf_first_half,
        "swolf_second_half": swolf_second_half,
        "swolf_drift_pts": swolf_drift_pts,
        "swolf_interpretation": swolf_drift_interpretation,
        "avg_pace_100m_sec": avg_pace,
        "best_pace_100m_sec": best_pace,
        "avg_swim_cadence_spm": summary_data.get("avg_swim_cadence"),
        "total_strokes": summary_data.get("total_strokes"),
        "avg_strokes_per_length": summary_data.get("avg_strokes_per_length"),
        "stroke_styles_breakdown": style_summary,
        "hr_zones_distribution": zones_summary,
        "is_personal_record": summary_data.get("is_personal_record", False),
        "moderate_intensity_min": summary_data.get("moderate_intensity_min"),
        "vigorous_intensity_min": summary_data.get("vigorous_intensity_min"),
        "swimming_hr_zones_profile": swim_zones,
        "swim_intensity_classification": swim_intensity_classification,
    }

    log.info(f"??? Full Swimming Efficiency analysis complete for {activity_id}")
    return result


@tool(args_schema=ActivityID)
def analyze_activity_efficiency(activity_id: str, user_id: str | None = None) -> dict[str, Any] | str:
    """Performs high-precision physiological analysis in BigQuery.

    Automatically detects activity sport type (Running vs. Swimming vs. Other).
    For Running: Calculates Aerobic Decoupling, Form Efficiency, and Metabolic Cost (HR per Step).
    For Swimming: Calculates SWOLF efficiency, SWOLF drift/decoupling, stroke styles breakdown,
    pace per 100m, rest durations, and HR zone distribution.

    Args:
        activity_id: The unique ID of the activity to analyze.
        user_id: The ID of the user.

    Returns:
        A dictionary containing the efficiency analysis results, or an error message.
    """
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    dataset = config["dataset_id"]
    user_where_act = f"AND user_id = '{user_id}'" if user_id else ""

    # 0. Check activity type from recent_activities
    try:
        query_type = f"""
            SELECT type FROM `{config["project_id"]}.{dataset}.recent_activities`
            WHERE CAST(id AS STRING) = '{activity_id}' {user_where_act}
            LIMIT 1
        """
        act_type_row = list(client.query(query_type).result())
        activity_type = act_type_row[0].type if act_type_row else None

        if activity_type in ("lap_swimming", "open_water_swimming"):
            return _analyze_swim_efficiency(activity_id, user_id, client, config["project_id"], dataset)
    except Exception as e:
        log.warning(f"Failed to check activity type for {activity_id}: {e}")

    user_where = f"AND t.user_id = '{user_id}'" if user_id else ""

    query = f"""
    WITH session_stats AS (
        SELECT 
            AVG(CASE WHEN power_w > 0 THEN power_w END) as avg_power,
            AVG(CASE WHEN cadence_spm > 0 THEN cadence_spm END) as avg_cadence
        FROM `{config["project_id"]}.{dataset}.latest_activity_telemetry` t
        WHERE t.activity_id = '{activity_id}'
        {user_where}
    ),
    telemetry_base AS (
        SELECT 
            t.timestamp_ms,
            t.hr_bpm, 
            t.power_w, 
            t.cadence_spm,
            t.vertical_oscillation_cm as vo,
            t.stride_length_mm as sl,
            t.ground_contact_time_ms as gct,
            t.vertical_ratio as vr,
            t.vertical_speed as vs,
            t.body_battery as bb,
            t.gap_mps as gap,
            PERCENT_RANK() OVER(ORDER BY t.timestamp_ms) as total_progress
        FROM `{config["project_id"]}.{dataset}.latest_activity_telemetry` t
        CROSS JOIN session_stats s
        WHERE t.activity_id = '{activity_id}'
        {user_where}
        AND t.hr_bpm > 0
        -- Dynamically filter only active WORK phases based on the session's own average metrics (no hardcoded constants)
        AND (
            (s.avg_power IS NOT NULL AND t.power_w >= s.avg_power)
            OR 
            (s.avg_power IS NULL AND s.avg_cadence IS NOT NULL AND t.cadence_spm >= s.avg_cadence)
            OR
            (s.avg_power IS NULL AND s.avg_cadence IS NULL)
        )
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
            "avg_cadence": round(row.avg_cadence, 1) if row.avg_cadence is not None else None,
            "hr_per_step": round(row.hr_per_step, 3) if row.hr_per_step is not None else None,
            "body_battery_drain": int(row.total_battery_drain) if row.total_battery_drain is not None else None,
            "avg_vertical_ratio_pct": round(row.avg_vertical_ratio, 2) if row.avg_vertical_ratio is not None else None,
            "avg_vertical_speed_mps": round(row.avg_vertical_speed, 3) if row.avg_vertical_speed is not None else None,
            "efficiency_score": (round(row.eff_first_half, 3) if row.eff_first_half is not None else None),
            "gct_first_half": (round(row.gct_first_half, 1) if row.gct_first_half is not None else None),
            "gct_second_half": (round(row.gct_second_half, 1) if row.gct_second_half is not None else None),
            "avg_gct_ms": round(row.avg_gct, 1) if row.avg_gct is not None else None,
            "avg_stride_length_mm": round(row.avg_sl, 0) if row.avg_sl is not None else None,
        }

        if row.eff_first_half and row.eff_second_half:
            dec = ((row.eff_first_half - row.eff_second_half) / row.eff_first_half) * 100
            summary["aerobic_decoupling_pct"] = f"{round(dec, 2)}%"
            summary["interpretation"] = (
                "Stable" if dec < 5 else "Cardiac Drift Detected" if dec < 10 else "Significant Decoupling"
            )

        log.info(f"??? Full Efficiency analysis complete for {activity_id}")
        return summary
    except Exception as e:
        log.error(f"??? Analysis failed: {e}")
        return f"Error during analysis: {e}"


@tool(args_schema=ActivityID)
def analyze_activity_stages(activity_id: str, user_id: str | None = None) -> list[dict[str, Any]] | str:
    """Analyzes telemetry to split an activity into physiological stages.

    For Running: Splits by Intervals/Work vs. Rest.
    For Swimming: Splits by individual pool lengths and rest intervals with SWOLF, style, and pace.

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

    # Check if swimming
    try:
        query_type = f"""
            SELECT type FROM `{config["project_id"]}.{dataset}.recent_activities`
            WHERE CAST(id AS STRING) = '{activity_id}' {user_where}
            LIMIT 1
        """
        act_type_row = list(client.query(query_type).result())
        activity_type = act_type_row[0].type if act_type_row else None

        if activity_type in ("lap_swimming", "open_water_swimming"):
            query_lengths = f"""
                SELECT 
                    length_index, distance_m, duration_sec, avg_speed_mps,
                    avg_hr, max_hr, total_strokes, avg_swolf, swim_stroke, pace_per_100m_sec
                FROM `{config["project_id"]}.{dataset}.swim_length_telemetry`
                WHERE activity_id = '{activity_id}' {user_where}
                ORDER BY length_index ASC
            """
            l_rows = [dict(r) for r in client.query(query_lengths).result()]
            if l_rows:
                return [
                    {
                        "stage_id": r["length_index"],
                        "type": f"Swim ({r.get('swim_stroke') or 'Lap'})",
                        "distance_m": r.get("distance_m"),
                        "duration_sec": r.get("duration_sec"),
                        "avg_hr": r.get("avg_hr"),
                        "max_hr": r.get("max_hr"),
                        "avg_swolf": r.get("avg_swolf"),
                        "strokes": r.get("total_strokes"),
                        "pace_100m_sec": r.get("pace_per_100m_sec"),
                    }
                    for r in l_rows
                ]
    except Exception as e:
        log.warning(f"Swim stage check fallback: {e}")

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
        df["power_smooth"] = df["power_w"].rolling(window=10, center=True).mean().fillna(df["power_w"])
        df["is_work"] = df["power_smooth"] > threshold
        df["state_change"] = df["is_work"] != df["is_work"].shift(1)
        df["stage_id"] = df["state_change"].cumsum()

        stages = []
        for _, group in df.groupby("stage_id"):
            is_work = group["is_work"].iloc[0]
            duration_sec = (group["timestamp_ms"].max() - group["timestamp_ms"].min()) / 1000

            if duration_sec < 10:
                continue

            cadence_clean = group["cadence_spm"].replace(0, np.nan)
            hr_step = (group["hr_bpm"] / cadence_clean).mean() if not cadence_clean.isnull().all() else None
            bb_drop = group["body_battery"].max() - group["body_battery"].min()

            stage_summary = {
                "type": "Work" if is_work else "Rest/Warmup/Cooldown",
                "duration_sec": round(duration_sec, 1),
                "avg_hr": round(group["hr_bpm"].mean(), 1),
                "max_hr": int(group["hr_bpm"].max()),
                "avg_power": round(group["power_w"].mean(), 1),
                "max_power": int(group["power_w"].max()),
                "avg_cadence": round(group["cadence_spm"].mean(), 1)
                if not group["cadence_spm"].isnull().all()
                else None,
                "hr_per_step": round(hr_step, 3) if hr_step is not None and not np.isnan(hr_step) else None,
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
                    val = group[col].mean()
                    if not np.isnan(val):
                        stage_summary[key] = round(val, 2)

            stages.append(stage_summary)

        return stages
    except Exception as e:
        log.error(f"??? Stage analysis failed: {e}")
        return f"Error during stage analysis: {e}"
