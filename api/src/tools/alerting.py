import json
import logging
import statistics

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config
from src.utils.notifications import send_proactive_notification

log = logging.getLogger(__name__)


class ProactiveAlertsInput(BaseModel):
    """Input schema for checking proactive Immune Radar & ACWR alerts."""

    user_id: str = Field(..., description="The internal user ID (mandatory).")


@tool(args_schema=ProactiveAlertsInput)
def check_proactive_alerts(user_id: str) -> str:
    """
    Evaluates physiological telemetry against Proactive Alerting hooks:
    1. Immune Radar: Triggers alert if HRV Z-Score < -1.5 AND RHR Z-Score > 1.5.
    2. Workload ACWR: Triggers alert if Acute:Chronic Workload Ratio > 1.35.
    Dispatches proactive notifications if thresholds are exceeded.
    """
    config = get_config()
    pid = config["project_id"]
    ds = config["dataset_id"]
    client = bigquery.Client(project=pid)

    alerts_triggered = []
    hrv_z = 0.0
    rhr_z = 0.0
    ac_ratio = 1.0

    try:
        # 1. Immune Radar (HRV Z & RHR Z)
        query_hrv = f"""
            SELECT avg_hrv
            FROM `{pid}.{ds}.hrv_history`
            WHERE user_id = '{user_id}' AND avg_hrv IS NOT NULL
            ORDER BY date DESC LIMIT 21
        """
        hrv_rows = [r.avg_hrv for r in client.query(query_hrv).result()]

        query_rhr = f"""
            SELECT resting_heart_rate
            FROM `{pid}.{ds}.daily_physiology`
            WHERE user_id = '{user_id}' AND resting_heart_rate IS NOT NULL
            ORDER BY date DESC LIMIT 21
        """
        rhr_rows = [r.resting_heart_rate for r in client.query(query_rhr).result()]

        if len(hrv_rows) >= 5 and len(rhr_rows) >= 5:
            today_hrv, baseline_hrv = hrv_rows[0], hrv_rows[1:]
            std_hrv = statistics.stdev(baseline_hrv) if len(baseline_hrv) > 1 else 0.0
            hrv_z = round((today_hrv - statistics.mean(baseline_hrv)) / std_hrv, 2) if std_hrv > 0 else 0.0

            today_rhr, baseline_rhr = rhr_rows[0], rhr_rows[1:]
            std_rhr = statistics.stdev(baseline_rhr) if len(baseline_rhr) > 1 else 0.0
            rhr_z = round((today_rhr - statistics.mean(baseline_rhr)) / std_rhr, 2) if std_rhr > 0 else 0.0

            if hrv_z < -1.5 and rhr_z > 1.5:
                immune_msg = (
                    f"⚠️ IMMUNE RADAR ALERT: Systemic stress detected for {user_id}. "
                    f"HRV Z-Score is {hrv_z} (depressed) and Resting HR Z-Score is +{rhr_z} (elevated). "
                    f"Elevated risk of illness or autonomic fatigue. Recommend Zone 1 recovery or rest."
                )
                alerts_triggered.append(immune_msg)
                send_proactive_notification(user_id, immune_msg)

        # 2. ACWR Workload Check
        query_acwr = f"""
            SELECT ac_ratio
            FROM `{pid}.{ds}.view_calculated_training_status`
            WHERE user_id = '{user_id}' AND ac_ratio IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """
        acwr_rows = list(client.query(query_acwr).result())
        if acwr_rows:
            ac_ratio = float(acwr_rows[0].ac_ratio or 1.0)
            if ac_ratio > 1.35:
                acwr_msg = (
                    f"⚠️ WORKLOAD ALERT: Acute:Chronic Workload Ratio reached {ac_ratio} for {user_id} "
                    f"(Danger threshold > 1.35). High risk of mechanical overreaching and injury. "
                    f"Recommend deload or low-intensity session."
                )
                alerts_triggered.append(acwr_msg)
                send_proactive_notification(user_id, acwr_msg)

        result = {
            "user_id": user_id,
            "has_alerts": len(alerts_triggered) > 0,
            "alerts_count": len(alerts_triggered),
            "hrv_z_score": hrv_z,
            "rhr_z_score": rhr_z,
            "acwr_ratio": ac_ratio,
            "alerts_triggered": alerts_triggered,
        }

        log.info(f"✅ Proactive alerts check completed for {user_id}: {len(alerts_triggered)} alerts")
        return json.dumps(result, indent=2)

    except Exception as e:
        log.error(f"❌ Failed checking proactive alerts: {e}")
        return json.dumps({"error": str(e)})
