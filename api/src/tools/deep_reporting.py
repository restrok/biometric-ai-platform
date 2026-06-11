import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from google.cloud import bigquery, storage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config
from src.utils.physiology import (
    UserCalibrationProfile,
    AC_RATIO_HIGH_RISK_LIMIT,
    AC_RATIO_MODERATE_RISK_LIMIT,
    AC_RATIO_ALERT_LIMIT,
    Z_SCORE_ANOMALY_HIGH,
    Z_SCORE_ANOMALY_LOW,
    Z_SCORE_FATIGUE_LIMIT,
)

log = logging.getLogger(__name__)

# Cache clients per project to reduce initialization overhead
_bq_clients: dict[str, bigquery.Client] = {}
_storage_clients: dict[str, storage.Client] = {}


def get_bq_client(project_id: str) -> bigquery.Client:
    """Gets or creates a BigQuery client for the given project ID."""
    global _bq_clients
    if project_id not in _bq_clients:
        _bq_clients[project_id] = bigquery.Client(project=project_id)
    return _bq_clients[project_id]


def get_storage_client(project_id: str) -> storage.Client:
    """Gets or creates a Storage client for the given project ID."""
    global _storage_clients
    if project_id not in _storage_clients:
        _storage_clients[project_id] = storage.Client(project=project_id)
    return _storage_clients[project_id]


async def save_artifact_to_gcs(project_id: str, bucket_name: str, file_name: str, content: str) -> str:
    """Uploads the report artifact to a GCS bucket and generates a Signed URL."""

    def _upload():
        from datetime import timedelta

        client = get_storage_client(project_id)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        # Use text/html for rich visualization
        blob.upload_from_string(content, content_type="text/html")

        # Generate Signed URL valid for 2 hours
        try:
            url = blob.generate_signed_url(version="v4", expiration=timedelta(hours=2), method="GET")
        except Exception as e:
            log.warning(f"Could not generate Signed URL: {e}. Falling back to Authenticated URL.")
            url = f"https://storage.cloud.google.com/{bucket_name}/{file_name}"
        return url

    return await asyncio.to_thread(_upload)


class DeepReportingInput(BaseModel):
    """Input schema for generating a deep historical biometric report."""

    user_id: str = Field(..., description="The internal ID of the user (e.g., 'fsirio').")
    months_back: int = Field(3, description="Number of months to analyze (default 3).")
    project_id: str | None = Field(None, description="GCP Project ID.")
    dataset: str | None = Field(None, description="BigQuery Dataset ID.")


def _generate_svg_chart(
    data: list[float], labels: list[str], title: str, color: str = "#3b82f6", baseline: float | None = None
) -> str:
    """Generates a responsive, zero-dependency SVG trend chart."""
    if not data:
        return ""

    width = 800
    height = 200
    padding = 40

    # Scale data
    min_val = min(data) if data else 0
    max_val = max(data) if data else 1

    # Adjust range for better visualization
    if baseline:
        min_val = min(min_val, baseline * 0.8)
        max_val = max(max_val, baseline * 1.2)

    range_val = (max_val - min_val) if max_val != min_val else 1

    def get_x(i):
        return padding + (i * (width - 2 * padding) / (len(data) - 1)) if len(data) > 1 else width / 2

    def get_y(v):
        return height - padding - ((v - min_val) * (height - 2 * padding) / range_val)

    points = " ".join([f"{get_x(i)},{get_y(v)}" for i, v in enumerate(data)])

    # Baseline line (e.g., A:C 1.0)
    baseline_svg = ""
    if baseline:
        by = get_y(baseline)
        baseline_svg = f'<line x1="{padding}" y1="{by}" x2="{width - padding}" y2="{by}" stroke="var(--text-muted)" stroke-dasharray="4" opacity="0.5" />'

    return f"""
    <div class="chart-container">
        <h3 style="margin-bottom: 10px; font-size: 0.875rem;">{title}</h3>
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" class="trend-chart" aria-label="{title}">
            {baseline_svg}
            <polyline points="{points}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
            <!-- Data points -->
            {" ".join([f'<circle cx="{get_x(i)}" cy="{get_y(v)}" r="4" fill="{color}" />' for i, v in enumerate(data) if i % max(1, len(data) // 15) == 0])}
        </svg>
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); padding: 0 {padding}px;">
            <span>{labels[0]}</span>
            <span>{labels[-1]}</span>
        </div>
    </div>
    """


def _calculate_deep_stats(context: dict[str, pd.DataFrame], user_id: str) -> tuple[dict[str, Any], str]:
    """
    Core Analytical Engine: Performs cross-domain statistical analysis.
    Inspired by SensorFM's multi-domain health prediction tasks.
    """
    df_act = context.get("activities", pd.DataFrame())
    df_hrv = context.get("hrv", pd.DataFrame())
    df_sleep = context.get("sleep", pd.DataFrame())
    df_health = context.get("health", pd.DataFrame())

    if df_act.empty and df_hrv.empty and df_sleep.empty:
        return {"status": "no_data"}, "Insufficient data for a deep historical report."

    # 1. Cardiovascular & Load (Activities)
    cv_summary = "N/A"
    ac_ratio = 1.0
    z_score_eff = 0.0
    cv_color = "#3498db"
    ac_trend_svg = ""

    config = get_config()
    client = get_bq_client(config["project_id"])
    dataset = config["dataset_id"]

    # Fetch User Calibration Profile
    query_calib = f"""
        SELECT marker_type, marker_value 
        FROM `{config["project_id"]}.{dataset}.user_calibration_profile`
        WHERE user_id = '{user_id}'
    """
    calib_rows = list(client.query(query_calib).result())
    profile = UserCalibrationProfile.from_db_rows(calib_rows)

    if not df_act.empty:
        df_act["date"] = pd.to_datetime(df_act["date_str"])
        df_act = df_act.sort_values("date").set_index("date")

        # Acute:Chronic (A:C) Ratio logic
        df_daily = df_act.resample("D").agg({"distance_km": "sum", "avg_hr": "mean", "avg_power": "mean"}).fillna(0)
        df_daily["acute_load"] = df_daily["distance_km"].rolling(window=7, min_periods=1).sum()
        df_daily["chronic_load"] = df_daily["distance_km"].rolling(window=28, min_periods=1).sum() / 4
        df_daily["ac_ratio"] = (df_daily["acute_load"] / df_daily["chronic_load"]).fillna(1.0)

        ac_ratio = round(df_daily["ac_ratio"].iloc[-1], 2)

        # Chart Data
        ac_data = df_daily["ac_ratio"].tail(30).tolist()
        ac_labels = [d.strftime("%b %d") for d in df_daily.index[-30:]]
        ac_trend_svg = _generate_svg_chart(
            ac_data, ac_labels, "Workload (A:C Ratio) - Last 30 Days", color="var(--accent)", baseline=1.0
        )

        # Color based on A:C ratio
        if ac_ratio <= AC_RATIO_MODERATE_RISK_LIMIT:
            cv_color = "var(--success)"
        elif ac_ratio > profile.ac_ratio_red_line:
            cv_color = "var(--danger)"
        else:
            cv_color = "var(--warning)"

        # Efficiency Z-Score (Power/HR)
        df_act["eff"] = df_act["avg_power"] / df_act["avg_hr"].replace(0, pd.NA)
        valid_eff = df_act["eff"].dropna()
        if len(valid_eff) > 5:
            baseline_eff = valid_eff.mean()
            std_eff = valid_eff.std()
            recent_eff = valid_eff.tail(3).mean()
            z_score_eff = round((recent_eff - baseline_eff) / std_eff, 2) if std_eff > 0 else 0.0

        cv_summary = (
            f"You completed {round(df_act['distance_km'].sum(), 1)} km total. "
            f"Your current Acute:Chronic workload ratio is <strong>{ac_ratio}</strong>. "
            f"Your aerobic efficiency Z-Score is <strong>{z_score_eff}</strong> compared to your baseline."
        )

    # 2. Nervous System (HRV)
    hrv_summary = "N/A"
    hrv_trend = "Stable"
    hrv_color = "#3498db"
    hrv_trend_svg = ""
    if not df_hrv.empty:
        df_hrv["date"] = pd.to_datetime(df_hrv["date"])
        df_hrv = df_hrv.sort_values("date")
        avg_hrv = df_hrv["avg_hrv"].mean()
        recent_hrv = df_hrv["avg_hrv"].tail(7).mean()
        hrv_pct_change = ((recent_hrv - avg_hrv) / avg_hrv) * 100 if avg_hrv > 0 else 0
        hrv_trend = "Improving" if hrv_pct_change > 5 else "Declining" if hrv_pct_change < -5 else "Stable"

        if hrv_trend == "Improving":
            hrv_color = "var(--success)"
        elif hrv_trend == "Declining":
            hrv_color = "var(--danger)"
        else:
            hrv_color = "var(--accent)"

        # Chart Data
        hrv_data = df_hrv["avg_hrv"].tail(30).tolist()
        hrv_labels = [d.strftime("%b %d") for d in df_hrv["date"].tail(30)]
        hrv_trend_svg = _generate_svg_chart(
            hrv_data, hrv_labels, "Autonomic Recovery (HRV) - Last 30 Days", color=hrv_color, baseline=avg_hrv
        )

        hrv_summary = f"Your average HRV is <strong>{int(avg_hrv)} ms</strong>. The 7-day trend is <strong>{hrv_trend}</strong> ({round(hrv_pct_change, 1)}% variance vs baseline)."

    # 3. Recovery (Sleep)
    sleep_summary = "N/A"
    if not df_sleep.empty:
        df_sleep["date"] = pd.to_datetime(df_sleep["date"])
        avg_duration_h = df_sleep["duration_sec"].mean() / 3600
        avg_quality = df_sleep["quality"].mean()
        sleep_summary = f"Average nightly duration is <strong>{round(avg_duration_h, 1)} hours</strong> with an average quality score of <strong>{int(avg_quality)}/100</strong>."

    # 4. Subjective Health Correlation (Health Logs)
    health_summary = "No recent subjective health logs found."
    health_correlation_insight = ""
    high_fatigue_days = 0
    low_feeling_days = 0
    if not df_health.empty:
        df_health["date"] = pd.to_datetime(df_health["date"])
        df_health = df_health.sort_values("date")

        recent_health = df_health.tail(14).copy()
        # Ensure numeric types for comparison
        recent_health["fatigue_level"] = pd.to_numeric(recent_health["fatigue_level"], errors="coerce")
        recent_health["feeling"] = pd.to_numeric(recent_health["feeling"], errors="coerce")

        high_fatigue_days = len(recent_health[recent_health["fatigue_level"] >= 7])
        low_feeling_days = len(recent_health[recent_health["feeling"] <= 4])

        health_summary = f"In the last 14 logged days, you reported high fatigue (>=7/10) on <strong>{high_fatigue_days} days</strong> and poor feeling (<=4/10) on <strong>{low_feeling_days} days</strong>."

        # Simple correlation logic
        if high_fatigue_days >= 3 and ac_ratio > AC_RATIO_ALERT_LIMIT:
            health_correlation_insight = "<strong>Correlation Alert:</strong> Your subjective reports of high fatigue align strongly with your high Acute:Chronic workload ratio. The objective data validates your physical sensations of overreaching."
        elif low_feeling_days >= 3 and z_score_eff < Z_SCORE_FATIGUE_LIMIT:
            health_correlation_insight = "<strong>Correlation Alert:</strong> Your periods of feeling poorly correlate with drops in your aerobic efficiency (Z-Score). This suggests systemic fatigue affecting your running mechanics."
        elif high_fatigue_days == 0 and ac_ratio > profile.ac_ratio_red_line:
            health_correlation_insight = f"<strong>Warning:</strong> You are not reporting high fatigue, but your objective workload (A:C > {profile.ac_ratio_red_line}) is high. Beware of masked cumulative fatigue."
        else:
            health_correlation_insight = (
                "Your subjective feelings are currently tracking normally with your objective training load."
            )

    # 5. Warnings & Anomalies
    warnings = []
    if len(calib_rows) == 0:
        warnings.append(
            (
                "Standard Baseline Used",
                "No personal calibration profile found in the database. Standard physiological baseline limits were applied for load risk calculations.",
                "warning-box",
            )
        )

    if ac_ratio > profile.ac_ratio_red_line:
        warnings.append(
            (
                "High Injury Risk",
                f"A:C Ratio is {ac_ratio} (Personal Red Line: {profile.ac_ratio_red_line}). Consider a deload week.",
                "danger-box",
            )
        )
    elif ac_ratio > AC_RATIO_HIGH_RISK_LIMIT:
        warnings.append(
            (
                "Volume Warning",
                f"A:C Ratio is {ac_ratio} (Safe baseline: {AC_RATIO_HIGH_RISK_LIMIT}). You are pushing close to your personal limits.",
                "warning-box",
            )
        )
    if z_score_eff < Z_SCORE_ANOMALY_LOW:
        warnings.append(
            (
                "Efficiency Drop",
                f"Recent runs show a significant decoupling (Z-Score {z_score_eff}). Possible overreaching.",
                "danger-box",
            )
        )
    if hrv_trend == "Declining":
        warnings.append(
            ("Systemic Stress", "HRV trend is declining. Prioritize sleep and low-intensity sessions.", "warning-box")
        )
    if high_fatigue_days >= 4:
        warnings.append(
            (
                "Chronic Subjective Fatigue",
                f"You reported high fatigue on {high_fatigue_days} recent days. Intervention required.",
                "warning-box",
            )
        )

    # Prepare HTML Components
    icon_check = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>'
    icon_alert = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
    icon_user = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'

    if warnings:
        warnings_html = "".join(
            [
                f'<div class="status-box {cls}">{icon_alert} <span><strong>{title}:</strong> {msg}</span></div>'
                for title, msg, cls in warnings
            ]
        )
    else:
        warnings_html = f'<div class="status-box success-box">{icon_check} <span>All biometric domains are currently balanced and within safe physiological limits.</span></div>'

    # Generate Rich HTML Report
    timestamp = int(time.time())
    report_date = datetime.now().strftime("%b %d, %Y")
    file_name = f"reports/{user_id}/deep_report_{timestamp}.html"

    html_report = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Deep Biometric Evolution Report for {user_id}">
    <title>Deep Biometric Report | {user_id}</title>
    <style>
        :root {{
            --primary: #0f172a;
            --secondary: #475569;
            --accent: #3b82f6;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --bg: #f8fafc;
            --card: #ffffff;
            --border: #e2e8f0;
            --text-main: #1e293b;
            --text-muted: #64748b;
        }}

        @media (prefers-color-scheme: dark) {{
            :root {{
                --primary: #f8fafc;
                --secondary: #94a3b8;
                --accent: #60a5fa;
                --bg: #020617;
                --card: #0f172a;
                --border: #1e293b;
                --text-main: #f1f5f9;
                --text-muted: #94a3b8;
            }}
        }}

        * {{ box-sizing: border-box; }}
        
        body {{
            font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: var(--text-main);
            background-color: var(--bg);
            margin: 0;
            padding: env(safe-area-inset-top) 20px env(safe-area-inset-bottom);
            -webkit-font-smoothing: antialiased;
        }}

        .container {{
            max-width: 800px;
            margin: 40px auto;
            background: var(--card);
            padding: 40px;
            border-radius: 16px;
            border: 1px solid var(--border);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        }}

        header {{
            text-align: center;
            margin-bottom: 48px;
        }}

        h1 {{ 
            margin: 0; 
            font-size: 1.875rem; 
            font-weight: 800; 
            letter-spacing: -0.025em;
            color: var(--primary);
        }}

        .subtitle {{ 
            color: var(--text-muted); 
            font-size: 1rem; 
            margin-top: 8px;
            font-weight: 500;
        }}

        .meta-info {{
            font-size: 0.875rem;
            color: var(--text-muted);
            margin-top: 16px;
            display: flex;
            justify-content: center;
            gap: 16px;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 24px;
            margin-bottom: 48px;
        }}

        .stat-card {{
            background: var(--bg);
            padding: 24px;
            border-radius: 12px;
            border: 1px solid var(--border);
            transition: transform 0.2s ease;
        }}

        .stat-card:hover {{ transform: translateY(-2px); }}

        .stat-value {{ 
            font-size: 2rem; 
            font-weight: 700; 
            display: block; 
            color: var(--primary);
            line-height: 1;
        }}

        .stat-label {{ 
            font-size: 0.75rem; 
            color: var(--text-muted); 
            text-transform: uppercase; 
            letter-spacing: 0.05em; 
            margin-top: 8px; 
            display: block;
            font-weight: 600;
        }}

        section {{ margin-bottom: 48px; }}

        h2 {{ 
            font-size: 1.25rem; 
            font-weight: 700;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 12px;
            color: var(--primary);
        }}

        h2::after {{
            flex: 1;
            height: 1px;
            background: var(--border);
        }}

        article {{
            padding: 20px;
            border-radius: 12px;
            background: var(--bg);
            border: 1px solid var(--border);
            margin-bottom: 20px;
        }}

        h3 {{ 
            font-size: 1rem; 
            font-weight: 600; 
            margin-top: 0;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .insight-text {{
            font-size: 0.9375rem;
            color: var(--text-main);
            margin: 12px 0 0;
        }}

        .status-box {{
            display: flex;
            gap: 12px;
            padding: 16px;
            border-radius: 8px;
            font-size: 0.875rem;
            margin-bottom: 12px;
            align-items: start;
        }}

        .warning-box {{ background: rgba(245, 158, 11, 0.1); border: 1px solid var(--warning); color: var(--warning); }}
        .danger-box {{ background: rgba(239, 68, 68, 0.1); border: 1px solid var(--danger); color: var(--danger); }}
        .success-box {{ background: rgba(16, 185, 129, 0.1); border: 1px solid var(--success); color: var(--success); }}

        .chart-container {{
            margin-top: 24px;
            padding-top: 16px;
            border-top: 1px dashed var(--border);
        }}
        
        .trend-chart {{
            width: 100%;
            height: auto;
            max-height: 200px;
        }}

        footer {{
            text-align: center;
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 64px;
            padding-top: 24px;
            border-top: 1px solid var(--border);
        }}

        @media (max-width: 640px) {{
            .container {{ padding: 24px; margin: 0; border-radius: 0; border: none; }}
            .stat-value {{ font-size: 1.5rem; }}
        }}
    </style>
</head>
<body>
    <main class="container" role="main">
        <header>
            <h1>Biometric Evolution</h1>
            <div class="subtitle" role="doc-subtitle">SensorFM-Inspired Physiological Analysis</div>
            <div class="meta-info">
                <span>User: <strong>{user_id}</strong></span>
                <span>Generated: <time datetime="{datetime.now().isoformat()}">{report_date}</time></span>
            </div>
        </header>

        <section aria-labelledby="vital-markers-title">
            <h2 id="vital-markers-title">📊 Executive Markers</h2>
            <div class="grid">
                <div class="stat-card" style="border-bottom: 3px solid {cv_color}">
                    <span class="stat-value">{ac_ratio}</span>
                    <span class="stat-label">A:C Workload Ratio</span>
                </div>
                <div class="stat-card" style="border-bottom: 3px solid {hrv_color}">
                    <span class="stat-value" style="font-size: 1.25rem;">{hrv_trend}</span>
                    <span class="stat-label">Autonomic Trend</span>
                </div>
                <div class="stat-card">
                    <span class="stat-value">{z_score_eff}</span>
                    <span class="stat-label">Efficiency Z-Score</span>
                </div>
            </div>
        </section>

        <section aria-labelledby="domain-analysis-title">
            <h2 id="domain-analysis-title">🔍 Multi-Domain Analysis</h2>
            
            <article>
                <h3>{icon_check} Cardiovascular & Load</h3>
                <p class="insight-text">{cv_summary}</p>
                <p class="insight-text"><strong>Physiological Insight:</strong> {"Your aerobic efficiency is improving significantly." if z_score_eff > Z_SCORE_ANOMALY_HIGH else "Your load management is optimal." if ac_ratio <= AC_RATIO_HIGH_RISK_LIMIT else "You are increasing volume too rapidly, which may increase injury risk."}</p>
                {ac_trend_svg}
            </article>

            <article>
                <h3>{icon_check} Autonomic Recovery (HRV)</h3>
                <p class="insight-text">{hrv_summary}</p>
                <p class="insight-text"><strong>Interpretation:</strong> {hrv_trend} HRV indicates a {"balanced" if hrv_trend == "Stable" else "stressed" if hrv_trend == "Declining" else "super-compensating"} autonomic nervous system.</p>
                {hrv_trend_svg}
            </article>

            <article>
                <h3>{icon_check} Sleep & Recovery</h3>
                <p class="insight-text">{sleep_summary}</p>
            </article>

            <article>
                <h3>{icon_user} Subjective Wellness & Fatigue</h3>
                <p class="insight-text">{health_summary}</p>
                <p class="insight-text">{health_correlation_insight}</p>
            </article>
        </section>

        <section aria-labelledby="findings-title">
            <h2 id="findings-title">⚠️ Advisory & Findings</h2>
            {warnings_html}
        </section>

        <footer>
            Built with Biometric AI Platform v0.1.0 — Empowering Athlete Performance through Data Science.
        </footer>
    </main>
</body>
</html>"""

    llm_summary = {
        "status": "success",
        "period_months": context.get("months_back", 3),
        "ac_ratio": ac_ratio,
        "hrv_trend": hrv_trend,
        "efficiency_z_score": z_score_eff,
        "warnings_count": len(warnings),
        "artifact_path": file_name,
    }

    return llm_summary, html_report


@tool(args_schema=DeepReportingInput)
async def generate_deep_historical_report(
    user_id: str, months_back: int = 3, project_id: str | None = None, dataset: str | None = None
) -> str:
    """
    Generates a high-precision, multi-domain historical report for the user.
    Analyzes trends across Cardiovascular, Sleep, and Autonomic Nervous System domains.
    Returns a summary for the LLM and a GCS Signed URL for the user.
    MANDATORY for long-term (1-6 months) evolution queries.
    """
    config = get_config()
    pid = project_id or config.get("project_id")
    ds = dataset or config.get("dataset_id")
    bucket_name = os.getenv("DATALAKE_BUCKET") or f"{pid}-biometric-reports"

    if not pid:
        return json.dumps({"error": "GOOGLE_CLOUD_PROJECT not set."})

    def _fetch_all_data():
        client = get_bq_client(pid)
        start_date = (datetime.now() - timedelta(days=30 * months_back)).strftime("%Y-%m-%d")

        # 1. Activities
        q_act = f"""
            SELECT 
                FORMAT_TIMESTAMP('%Y-%m-%d', TIMESTAMP_SECONDS(CAST(date AS INT64))) as date_str,
                SUM(distance_m)/1000 as distance_km,
                AVG(avg_hr) as avg_hr,
                AVG(avg_power) as avg_power
            FROM `{pid}.{ds}.recent_activities`
            WHERE user_id = '{user_id}' AND type = 'running'
            AND date >= UNIX_SECONDS(TIMESTAMP('{start_date}'))
            GROUP BY 1 ORDER BY 1 ASC
        """

        # 2. HRV
        q_hrv = f"SELECT date, avg_hrv FROM `{pid}.{ds}.hrv_history` WHERE user_id = '{user_id}' AND date >= '{start_date}' ORDER BY date ASC"

        # 3. Sleep
        q_sleep = f"SELECT date, duration_sec, quality FROM `{pid}.{ds}.sleep_history` WHERE user_id = '{user_id}' AND date >= '{start_date}' ORDER BY date ASC"

        # 4. Health Logs
        q_health = f"SELECT date, feeling, fatigue_level FROM `{pid}.{ds}.user_health_status` WHERE user_id = '{user_id}' AND date >= '{start_date}' ORDER BY date ASC"

        return {
            "activities": client.query(q_act).to_dataframe(),
            "hrv": client.query(q_hrv).to_dataframe(),
            "sleep": client.query(q_sleep).to_dataframe(),
            "health": client.query(q_health).to_dataframe(),
            "months_back": months_back,
        }

    try:
        context_data = await asyncio.to_thread(_fetch_all_data)

        llm_summary, html_report = _calculate_deep_stats(context_data, user_id)

        if llm_summary.get("status") == "no_data":
            return json.dumps(llm_summary)

        # Save to GCS
        file_path = llm_summary.pop("artifact_path")
        artifact_uri = await save_artifact_to_gcs(pid, bucket_name, file_path, html_report)

        llm_summary["artifact_uri"] = artifact_uri
        log.info(f"✅ Deep report artifact generated for {user_id}: {artifact_uri}")

        return json.dumps(llm_summary)

    except Exception as e:
        log.error(f"❌ Failed to generate deep report: {e}")
        return json.dumps({"status": "error", "message": str(e)})
