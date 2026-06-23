import json
import logging
from datetime import datetime, timedelta

import pandas as pd
from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config
from src.utils.physiology import (
    AC_RATIO_HIGH_RISK_LIMIT,
    AC_RATIO_MODERATE_RISK_LIMIT,
    DEFAULT_PACE_FALLBACK,
    UserCalibrationProfile,
)

log = logging.getLogger(__name__)


class TrainingImpactInput(BaseModel):
    """Input schema for predicting training impact."""

    duration_mins: float = Field(..., description="Estimated duration of the proposed workout in minutes.")
    avg_hr: float = Field(..., description="Estimated average heart rate for the proposed workout.")
    user_id: str = Field(..., description="The internal ID of the user.")


@tool(args_schema=TrainingImpactInput)
def project_training_impact(duration_mins: float, avg_hr: float, user_id: str) -> str:
    """
    Simulates the physiological impact of a proposed workout on the user's training load.
    Calculates the new Acute:Chronic (A:C) Workload Ratio and compares it against
    personal red lines from the calibration profile.
    """
    config = get_config()
    pid = config["project_id"]
    ds = config["dataset_id"]
    client = bigquery.Client(project=pid)

    try:
        # 1. Fetch historical running distances (last 35 days for buffer)
        start_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")

        # We need daily sums of distance
        query_dist = f"""
            SELECT 
                FORMAT_TIMESTAMP('%Y-%m-%d', TIMESTAMP_SECONDS(CAST(date AS INT64))) as date_str,
                SUM(distance_m)/1000 as distance_km
            FROM `{pid}.{ds}.recent_activities`
            WHERE user_id = '{user_id}' AND type = 'running'
            AND date >= UNIX_SECONDS(TIMESTAMP('{start_date}'))
            GROUP BY 1 ORDER BY 1 ASC
        """
        df_act = client.query(query_dist).to_dataframe()
        # 2. Fetch User Calibration Profile
        query_calib = f"""
            SELECT marker_type, marker_value 
            FROM `{pid}.{ds}.user_calibration_profile`
            WHERE user_id = '{user_id}'
        """
        calib_rows = list(client.query(query_calib).result())
        profile = UserCalibrationProfile.from_db_rows(calib_rows)

        # Check total runs to enforce calibration phase guardrail
        query_count = f"""
            SELECT COUNT(*) as total_runs
            FROM `{pid}.{ds}.recent_activities`
            WHERE user_id = '{user_id}' AND type = 'running'
        """
        run_count_res = list(client.query(query_count).result())
        total_runs = run_count_res[0].total_runs if run_count_res else 0
        calibration_phase_required = total_runs < 3

        # 2.1 Fetch Latest HRV Status
        query_hrv = f"""
            SELECT avg_hrv, baseline_low, status
            FROM `{pid}.{ds}.hrv_history`
            WHERE user_id = '{user_id}'
            ORDER BY date DESC LIMIT 1
        """
        hrv_res = list(client.query(query_hrv).result())
        hrv_multiplier = 1.0
        hrv_context = "HRV is within normal baseline."

        if hrv_res:
            latest_hrv = hrv_res[0].avg_hrv
            baseline_low = hrv_res[0].baseline_low
            hrv_status = hrv_res[0].status

            if latest_hrv and baseline_low and latest_hrv < baseline_low:
                # If HRV is below baseline, increase risk multiplier
                # 10% drop below baseline = 1.1x risk
                hrv_drop_pct = (baseline_low - latest_hrv) / baseline_low
                hrv_multiplier = 1.0 + (hrv_drop_pct * profile.hrv_sensitivity_index)
                hrv_context = f"HRV ({latest_hrv}ms) is below baseline ({baseline_low}ms). Risk multiplier of {round(hrv_multiplier, 2)}x applied."
            elif hrv_status == "UNBALANCED":
                hrv_multiplier = profile.hrv_unbalanced_risk_multiplier
                hrv_context = (
                    f"HRV Status is UNBALANCED. Systemic stress detected. {hrv_multiplier}x risk multiplier applied."
                )

        # 3. Fetch User's Avg Pace in specific HR zones, falling back to overall running average
        query_pace = f"""
            WITH hr_pace AS (
                SELECT AVG(avg_pace) as avg_pace
                FROM `{pid}.{ds}.recent_activities`
                WHERE user_id = '{user_id}' AND type = 'running'
                AND avg_hr BETWEEN {avg_hr - 5} AND {avg_hr + 5}
            ),
            overall_pace AS (
                SELECT AVG(avg_pace) as avg_pace
                FROM `{pid}.{ds}.recent_activities`
                WHERE user_id = '{user_id}' AND type = 'running'
            )
            SELECT 
                COALESCE(hr_pace.avg_pace, overall_pace.avg_pace) as avg_pace
            FROM hr_pace, overall_pace
        """
        pace_res = list(client.query(query_pace).result())
        avg_pace_ms = pace_res[0].avg_pace if pace_res and pace_res[0].avg_pace is not None else DEFAULT_PACE_FALLBACK

        # Calculate proposed distance
        proposed_distance_km = (duration_mins * 60 * avg_pace_ms) / 1000

        # 4. Calculate A:C Ratio
        if df_act.empty:
            current_ac = 1.0
            new_ac = (proposed_distance_km / 7) / (proposed_distance_km / 28)  # Will be 4.0 if no history
        else:
            df_act["date"] = pd.to_datetime(df_act["date_str"])
            df_act = df_act.set_index("date")

            # Resample to ensure all days are present
            df_daily = df_act.resample("D").sum().fillna(0)

            # Current State
            acute_load = df_daily["distance_km"].tail(7).sum()
            chronic_load = df_daily["distance_km"].tail(28).sum() / 4
            current_ac = acute_load / chronic_load if chronic_load > 0 else 1.0

            # Future State (Assuming workout is today)
            df_future = df_daily.copy()
            today_str = datetime.now().strftime("%Y-%m-%d")
            if today_str in df_future.index:
                df_future.at[today_str, "distance_km"] += proposed_distance_km
            else:
                # Add a new row if not present
                new_row = pd.DataFrame({"distance_km": [proposed_distance_km]}, index=[pd.to_datetime(today_str)])
                dfs_to_concat = [d for d in [df_future, new_row] if not d.empty]
                df_future = pd.concat(dfs_to_concat).sort_index() if dfs_to_concat else pd.DataFrame()

            new_acute = df_future["distance_km"].tail(7).sum()
            new_chronic = df_future["distance_km"].tail(28).sum() / 4
            new_ac = new_acute / new_chronic if new_chronic > 0 else 1.0

        # Adjust the effective AC ratio by the HRV multiplier
        effective_ac = new_ac * hrv_multiplier

        risk_level = "Low"
        if effective_ac > profile.ac_ratio_red_line:
            risk_level = "CRITICAL"
        elif effective_ac > AC_RATIO_HIGH_RISK_LIMIT:
            risk_level = "High"
        elif effective_ac > AC_RATIO_MODERATE_RISK_LIMIT:
            risk_level = "Moderate"

        recommendation = "Safe to proceed."
        if calibration_phase_required:
            recommendation = f"CALIBRATION PHASE ACTIVE: You have logged {total_runs}/3 runs. High-intensity workouts are restricted. Suggest Zone 2 recovery/aerobic runs only."
        elif risk_level == "CRITICAL":
            recommendation = f"DO NOT PROCEED. This session will push your effective A:C ratio (adjusted for HRV) to {round(effective_ac, 2)}, exceeding your personal red line of {profile.ac_ratio_red_line}."
        elif risk_level == "High":
            recommendation = "Proceed with caution. Consider reducing duration or intensity. HRV indicates your body's tolerance for load is reduced today."

        # Flag fallback status explicitly so the LLM and user know
        fallbacks_applied = {
            "pace_fallback_used": avg_pace_ms == DEFAULT_PACE_FALLBACK,
            "calibration_defaults_used": len(calib_rows) == 0,
            "calibration_phase_required": calibration_phase_required,
        }

        result = {
            "proposed_workout": {
                "duration_mins": duration_mins,
                "avg_hr": avg_hr,
                "est_distance_km": round(proposed_distance_km, 2),
            },
            "impact_analysis": {
                "current_ac_ratio": round(current_ac, 2),
                "projected_ac_ratio": round(new_ac, 2),
                "hrv_adjustment_multiplier": round(hrv_multiplier, 2),
                "effective_ac_ratio": round(effective_ac, 2),
                "personal_red_line": profile.ac_ratio_red_line,
                "risk_level": risk_level,
                "hrv_context": hrv_context,
            },
            "recommendation": recommendation,
            "fallbacks_applied": fallbacks_applied,
        }

        log.info(f"✅ Training impact projected for {user_id}: New AC {new_ac}")
        return json.dumps(result)

    except Exception as e:
        log.error(f"❌ Failed to project training impact: {e}")
        return json.dumps({"error": str(e)})
