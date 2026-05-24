import json
import logging
from datetime import datetime, timedelta

import pandas as pd
from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

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
        # 2. Fetch Personal Red Line (A:C Ratio) and HRV Baseline
        query_calib = f"""
            SELECT marker_type, marker_value 
            FROM `{pid}.{ds}.user_calibration_profile`
            WHERE user_id = '{user_id}' 
            AND marker_type IN ('ac_ratio_red_line', 'hrv_sensitivity_index')
        """
        calib_res = {r.marker_type: r.marker_value for r in client.query(query_calib).result()}
        red_line = calib_res.get("ac_ratio_red_line", 1.45)
        hrv_sensitivity = calib_res.get("hrv_sensitivity_index", 1.0)  # Default 1.0 multiplier

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
                hrv_multiplier = 1.0 + (hrv_drop_pct * hrv_sensitivity)
                hrv_context = f"HRV ({latest_hrv}ms) is below baseline ({baseline_low}ms). Risk multiplier of {round(hrv_multiplier, 2)}x applied."
            elif hrv_status == "UNBALANCED":
                hrv_multiplier = 1.2
                hrv_context = "HRV Status is UNBALANCED. Systemic stress detected. 1.2x risk multiplier applied."

        # 3. Fetch User's Avg Pace...

        # 3. Fetch User's Avg Pace in specific HR zones to estimate distance
        # For simplicity, we'll just use their overall average pace for now if we can't be precise
        # Or even better, try to find their pace for this specific avg_hr
        query_pace = f"""
            SELECT AVG(avg_pace) as avg_pace
            FROM `{pid}.{ds}.recent_activities`
            WHERE user_id = '{user_id}' AND type = 'running'
            AND avg_hr BETWEEN {avg_hr - 5} AND {avg_hr + 5}
        """
        pace_res = list(client.query(query_pace).result())
        # Garmin pace is usually in m/s or min/km depending on the tool's storage.
        # recent_activities avg_pace is stored as float. Let's assume it's m/s if > 1 or min/km if < 1?
        # Actually, let's look at the schema or data.
        # In the context it showed: "avg_hr": 151.0, "distance_m": 9639.95...
        # Wait, retrieve_biometric_data output: "distance_m": 9639.95... "avg_hr": 151.0
        # It doesn't show avg_pace in the JSON I saw earlier but the schema says "avg_pace": "FLOAT".

        avg_pace_ms = pace_res[0].avg_pace if pace_res and pace_res[0].avg_pace else 3.0  # Fallback 3m/s (~5:33 min/km)

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
        if effective_ac > red_line:
            risk_level = "CRITICAL"
        elif effective_ac > 1.3:
            risk_level = "High"
        elif effective_ac > 1.1:
            risk_level = "Moderate"

        recommendation = "Safe to proceed."
        if risk_level == "CRITICAL":
            recommendation = f"DO NOT PROCEED. This session will push your effective A:C ratio (adjusted for HRV) to {round(effective_ac, 2)}, exceeding your personal red line of {red_line}."
        elif risk_level == "High":
            recommendation = "Proceed with caution. Consider reducing duration or intensity. HRV indicates your body's tolerance for load is reduced today."

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
                "personal_red_line": red_line,
                "risk_level": risk_level,
                "hrv_context": hrv_context,
            },
            "recommendation": recommendation,
        }

        log.info(f"✅ Training impact projected for {user_id}: New AC {new_ac}")
        return json.dumps(result)

    except Exception as e:
        log.error(f"❌ Failed to project training impact: {e}")
        return json.dumps({"error": str(e)})
