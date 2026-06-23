"""Physiological calculation utilities for load and recovery analysis."""

from typing import Any

import pandas as pd


def calculate_ac_ratio(activities: list[dict[str, Any]], metric_type: str = "work") -> dict[str, Any]:
    """
    Calculates the Acute:Chronic Workload Ratio (ACWR) based on activity history.

    Hierarchy:
    1. 'work': Based on Kilojoules (Power * Duration). Most precise.
    2. 'trimp': Based on normalized heart rate minutes.
    3. 'distance': Based on pure volume (km).
    """
    if not activities:
        return {"acute": 0.0, "chronic": 0.0, "ratio": 1.0, "metric": metric_type}

    df = pd.DataFrame(activities)
    # Convert date to datetime if it's in seconds or string
    if df["date"].dtype == "int64" or df["date"].dtype == "float64":
        df["dt"] = pd.to_datetime(df["date"], unit="s")
    else:
        df["dt"] = pd.to_datetime(df["date"])

    df = df.sort_values("dt")

    # Add derived metrics
    df["work_kj"] = (df["duration_sec"] * df.get("avg_power", 0).fillna(0)) / 1000.0
    # Simplified TRIMP: duration * (avg_hr / 165.0) -> 165 is the identified AeT
    df["trimp"] = (df["duration_sec"] / 60.0) * (df["avg_hr"].fillna(120) / 165.0)
    df["dist_km"] = df["distance_m"].fillna(0) / 1000.0

    # Resample to daily to include zero-load days
    df_daily = df.set_index("dt").resample("D").agg({"work_kj": "sum", "trimp": "sum", "dist_km": "sum"}).fillna(0)

    # CRITICAL: Anchor the window to 'today' to account for rest days since the last activity.
    # We normalize to midnight to avoid partial day issues.
    today = pd.Timestamp.now().normalize()
    start_chronic = today - pd.Timedelta(days=28)

    # Reindex to ensure we have every day from 28 days ago until today.
    # This correctly injects zero-load days if the user hasn't trained recently.
    full_idx = pd.date_range(start=start_chronic, end=today, freq="D")
    df_daily = df_daily.reindex(full_idx, fill_value=0)

    # Choose metric
    col_map = {"work": "work_kj", "trimp": "trimp", "distance": "dist_km"}
    col = col_map.get(metric_type, "work_kj")

    # Check if power is actually available if work is requested
    if metric_type == "work" and df_daily["work_kj"].sum() == 0:
        col = "trimp"  # Fallback to trimp if no power
        metric_type = "trimp"

    # Use the last 7 days for Acute and the last 28 days for Chronic.
    acute = df_daily[col].tail(7).sum()
    chronic = df_daily[col].tail(28).sum() / 4.0

    ratio = acute / chronic if chronic > 0 else 1.0

    return {
        "acute_load": round(float(acute), 2),
        "chronic_load": round(float(chronic), 2),
        "ac_ratio": round(float(ratio), 2),
        "metric_used": metric_type,
    }


from pydantic import BaseModel, Field

# Centralized physiological default thresholds and fallbacks
DEFAULT_AC_RATIO_RED_LINE = 1.3
DEFAULT_HRV_SENSITIVITY = 1.0
DEFAULT_HRV_UNBALANCED_MULTIPLIER = 1.2
DEFAULT_PACE_FALLBACK = 3.0  # m/s
DEFAULT_Z2_MAX_FALLBACK = 165
DEFAULT_POWER_THRESHOLD = 180

# Load risk thresholds
AC_RATIO_HIGH_RISK_LIMIT = 1.3
AC_RATIO_MODERATE_RISK_LIMIT = 1.1
AC_RATIO_ALERT_LIMIT = 1.2

# Z-Score limits for reports
Z_SCORE_ANOMALY_HIGH = 1.5
Z_SCORE_ANOMALY_LOW = -1.5
Z_SCORE_FATIGUE_LIMIT = -1.0


class UserCalibrationProfile(BaseModel):
    """Pydantic model representing a structured physiological calibration profile."""

    ac_ratio_red_line: float = Field(
        DEFAULT_AC_RATIO_RED_LINE,
        description="Personal Acute:Chronic Workload Ratio red line limit.",
    )
    hrv_sensitivity_index: float = Field(
        DEFAULT_HRV_SENSITIVITY,
        description="Sensitivity index for HRV drop risk adjustment.",
    )
    hrv_unbalanced_risk_multiplier: float = Field(
        DEFAULT_HRV_UNBALANCED_MULTIPLIER,
        description="Risk multiplier applied when HRV status is unbalanced.",
    )
    gct_drift_baseline: float = Field(
        30.0,
        description="Average Ground Contact Time (GCT) drift observed in steady Zone 2 runs.",
    )
    aerobic_decoupling_threshold: float = Field(
        0.05,
        description="Aerobic decoupling stability threshold.",
    )

    @classmethod
    def from_db_rows(cls, rows: list[Any]) -> "UserCalibrationProfile":
        """Loads and parses a list of calibration rows/dictionaries into a validated profile."""
        data = {}
        for r in rows:
            m_type = getattr(r, "marker_type", None)
            m_val = getattr(r, "marker_value", None)

            if m_type is None and isinstance(r, dict):
                m_type = r.get("marker_type")
                m_val = r.get("marker_value")

            if m_type and m_val is not None:
                if m_type in cls.model_fields:
                    data[m_type] = float(m_val)
                elif m_type == "ac_ratio_red_line":
                    data["ac_ratio_red_line"] = float(m_val)
                elif m_type == "hrv_sensitivity_index":
                    data["hrv_sensitivity_index"] = float(m_val)
                elif m_type == "hrv_unbalanced_risk_multiplier":
                    data["hrv_unbalanced_risk_multiplier"] = float(m_val)
        return cls(**data)
