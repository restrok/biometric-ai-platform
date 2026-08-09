import json
import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config
from src.utils.physiology import (
    AC_RATIO_MODERATE_RISK_LIMIT,
    UserCalibrationProfile,
)

log = logging.getLogger(__name__)


class ProposedSession(BaseModel):
    """Schema for a single proposed workout session."""

    date: str | None = Field(None, description="Proposed date in YYYY-MM-DD format (defaults to today).")
    duration_mins: float = Field(..., description="Duration in minutes.")
    estimated_work_kj: float | None = Field(None, description="Estimated mechanical work in kJ (Power * sec / 1000).")
    estimated_trimp: float | None = Field(None, description="Estimated TRIMP load.")
    target_zone: int | None = Field(None, description="Target HR Zone (1-5).")
    avg_hr: float | None = Field(None, description="Estimated average heart rate.")


class ProjectTrainingImpactInput(BaseModel):
    """Input schema for projecting multi-day or single-session training plan workload impact."""

    user_id: str = Field(..., description="The internal ID of the user (mandatory for multi-tenant isolation).")
    proposed_sessions: list[dict[str, Any]] | None = Field(
        None, description="List of proposed workout sessions for the next 7-14 days."
    )
    duration_mins: float | None = Field(None, description="Single session duration in minutes (legacy/simple mode).")
    avg_hr: float | None = Field(None, description="Single session average heart rate (legacy/simple mode).")
    projection_days: int = Field(14, description="Number of simulation days into the future (default 14).")


@tool(args_schema=ProjectTrainingImpactInput)
def project_training_impact(
    user_id: str,
    proposed_sessions: list[dict[str, Any]] | None = None,
    duration_mins: float | None = None,
    avg_hr: float | None = None,
    projection_days: int = 14,
) -> str:
    """
    Simulates and projects the physiological workload impact (Acute, Chronic Load & ACWR trajectory)
    of a proposed 7-14 day training plan or a single workout session.
    Compares projected peak ACWR against the user's personal calibration red lines.
    """
    config = get_config()
    pid = config["project_id"]
    ds = config["dataset_id"]
    client = bigquery.Client(project=pid)

    try:
        # Normalize proposed sessions
        sessions: list[dict[str, Any]] = []
        if proposed_sessions:
            sessions = proposed_sessions
        elif duration_mins is not None:
            sessions = [
                {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "duration_mins": duration_mins,
                    "avg_hr": avg_hr or 145.0,
                }
            ]

        # 1. Fetch historical workload for the last 35 days to form baseline
        start_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        query_history = f"""
            SELECT 
                DATE(TIMESTAMP_SECONDS(CAST(date AS INT64))) as dt,
                SUM((duration_sec * COALESCE(avg_power, 0)) / 1000.0) AS work_kj,
                SUM((duration_sec / 60.0) * (COALESCE(avg_hr, 120) / 165.0)) AS trimp
            FROM `{pid}.{ds}.recent_activities`
            WHERE user_id = '{user_id}'
            AND date >= UNIX_SECONDS(TIMESTAMP('{start_date}'))
            GROUP BY dt ORDER BY dt ASC
        """
        hist_rows = list(client.query(query_history).result())

        # 2. Fetch User Calibration Profile
        query_calib = f"""
            SELECT marker_type, marker_value 
            FROM `{pid}.{ds}.user_calibration_profile`
            WHERE user_id = '{user_id}'
        """
        calib_rows = list(client.query(query_calib).result())
        profile = UserCalibrationProfile.from_db_rows(calib_rows)

        # Build daily timeseries DataFrame
        today = datetime.now().date()
        hist_start = today - timedelta(days=35)
        sim_end = today + timedelta(days=max(1, projection_days))

        full_date_idx = pd.date_range(start=hist_start, end=sim_end, freq="D")
        df_sim = pd.DataFrame(index=full_date_idx)
        df_sim["work_kj"] = 0.0
        df_sim["trimp"] = 0.0

        for r in hist_rows:
            if r.dt and pd.to_datetime(r.dt) in df_sim.index:
                df_sim.loc[pd.to_datetime(r.dt), "work_kj"] += float(r.work_kj or 0.0)
                df_sim.loc[pd.to_datetime(r.dt), "trimp"] += float(r.trimp or 0.0)

        # 3. Inject proposed sessions into future simulation timeline
        for s in sessions:
            s_date_str = s.get("date") or today.strftime("%Y-%m-%d")
            try:
                s_dt = pd.to_datetime(s_date_str)
            except Exception:
                s_dt = pd.to_datetime(today)

            dur = float(s.get("duration_mins", 30))
            hr = float(s.get("avg_hr", 145))
            w_kj = s.get("estimated_work_kj")
            t_trimp = s.get("estimated_trimp")

            if w_kj is None:
                # Estimate work kj assuming ~150W power proxy
                w_kj = (dur * 60.0 * 150.0) / 1000.0
            if t_trimp is None:
                t_trimp = (dur / 60.0) * (hr / 165.0) * 60.0

            if s_dt in df_sim.index:
                df_sim.loc[s_dt, "work_kj"] += float(w_kj)
                df_sim.loc[s_dt, "trimp"] += float(t_trimp)

        # Select metric column: prefer work_kj if power data present, else fallback to trimp
        metric_col = "work_kj" if df_sim["work_kj"].sum() > 0 else "trimp"

        # Compute rolling Acute (7d sum) and Chronic (28d sum / 4.0)
        df_sim["acute"] = df_sim[metric_col].rolling(window=7, min_periods=1).sum()
        df_sim["chronic"] = df_sim[metric_col].rolling(window=28, min_periods=1).sum() / 4.0
        df_sim["acwr"] = df_sim.apply(
            lambda row: round(row["acute"] / row["chronic"], 2) if row["chronic"] > 0 else 1.0, axis=1
        )

        # Filter simulation period from today onwards
        sim_df = df_sim[df_sim.index >= pd.to_datetime(today)]

        timeline = []
        peak_acwr = 0.0
        peak_acwr_date = today.strftime("%Y-%m-%d")
        red_line = profile.ac_ratio_red_line or 1.30

        for idx, row in sim_df.iterrows():
            dt_str = idx.strftime("%Y-%m-%d")
            acwr_val = float(row["acwr"])
            is_danger = acwr_val > red_line

            if acwr_val > peak_acwr:
                peak_acwr = acwr_val
                peak_acwr_date = dt_str

            timeline.append(
                {
                    "date": dt_str,
                    "acute_load": round(float(row["acute"]), 2),
                    "chronic_load": round(float(row["chronic"]), 2),
                    "acwr": acwr_val,
                    "danger": is_danger,
                }
            )

        is_danger_zone = peak_acwr > red_line
        if is_danger_zone:
            recommendation = (
                f"DANGER: Proposed plan pushes peak ACWR to {peak_acwr} on {peak_acwr_date}, "
                f"exceeding personal red line limit ({red_line}). Reduce proposed duration or intensity."
            )
        elif peak_acwr > AC_RATIO_MODERATE_RISK_LIMIT:
            recommendation = (
                f"HIGH LOAD: Proposed plan reaches peak ACWR of {peak_acwr} on {peak_acwr_date}. "
                f"Ensure adequate Zone 1/2 recovery active days."
            )
        else:
            recommendation = f"SAFE: Proposed plan maintains optimal ACWR (Peak: {peak_acwr} on {peak_acwr_date})."

        result = {
            "user_id": user_id,
            "metric_used": metric_col,
            "projection_period": f"{today.strftime('%Y-%m-%d')} to {sim_end.strftime('%Y-%m-%d')}",
            "peak_acwr": peak_acwr,
            "peak_acwr_date": peak_acwr_date,
            "red_line_threshold": red_line,
            "is_danger_zone": is_danger_zone,
            "recommendation": recommendation,
            "simulation_timeline": timeline,
        }

        log.info(f"✅ Training impact projected for {user_id}: Peak ACWR {peak_acwr}")
        return json.dumps(result, indent=2)

    except Exception as e:
        log.error(f"❌ Failed to project training impact: {e}")
        return json.dumps({"error": str(e)})
