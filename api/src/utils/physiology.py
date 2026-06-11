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
