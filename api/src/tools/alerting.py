import hashlib
import json
import logging
import os
import statistics
from datetime import date

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.storage.factory import get_storage_engine
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
    Dispatches proactive notifications if thresholds are exceeded (with idempotency dedup).
    """
    if os.getenv("STORAGE_MODE") == "local":
        try:
            engine = get_storage_engine(mode="local")
            physio = engine.get_daily_physiology(user_id=user_id, days=21)
            hrv_vals = [p["hrv_rmssd"] for p in physio if p.get("hrv_rmssd")]
            rhr_vals = [p["resting_heart_rate"] for p in physio if p.get("resting_heart_rate")]
            alerts_triggered = []
            hrv_z = 0.0
            rhr_z = 0.0
            if len(hrv_vals) >= 5 and len(rhr_vals) >= 5:
                today_hrv, base_hrv = hrv_vals[0], hrv_vals[1:]
                std_hrv = statistics.stdev(base_hrv) if len(base_hrv) > 1 else 0.0
                hrv_z = round((today_hrv - statistics.mean(base_hrv)) / std_hrv, 2) if std_hrv > 0 else 0.0

                today_rhr, base_rhr = rhr_vals[0], rhr_vals[1:]
                std_rhr = statistics.stdev(base_rhr) if len(base_rhr) > 1 else 0.0
                rhr_z = round((today_rhr - statistics.mean(base_rhr)) / std_rhr, 2) if std_rhr > 0 else 0.0

                if hrv_z < -1.5 and rhr_z > 1.5:
                    immune_msg = f"⚠️ Alerta radar inmune para {user_id}: HRV Z {hrv_z}, RHR Z +{rhr_z}."
                    alerts_triggered.append(immune_msg)

                    data_date = str(physio[0].get("date") or date.today())[:10]
                    alert_type = "immune_radar"
                    payload_hash = hashlib.sha256(f"{user_id}:{hrv_z}:{rhr_z}".encode()).hexdigest()
                    alert_key = hashlib.sha256(
                        f"{user_id}|{alert_type}|{data_date}|{payload_hash}".encode()
                    ).hexdigest()

                    if not engine.is_alert_dispatched(alert_key, data_date=data_date):
                        if send_proactive_notification(user_id, immune_msg):
                            engine.record_alert_dispatch(
                                alert_key=alert_key,
                                alert_type=alert_type,
                                data_date=data_date,
                                payload_hash=payload_hash,
                                channel="telegram",
                                user_id=user_id,
                            )
                    else:
                        log.info(f"Skipping dispatch: {alert_type} for {user_id} on {data_date} already dispatched.")

            return json.dumps(
                {
                    "user_id": user_id,
                    "has_alerts": len(alerts_triggered) > 0,
                    "alerts_count": len(alerts_triggered),
                    "hrv_z_score": hrv_z,
                    "rhr_z_score": rhr_z,
                    "acwr_ratio": 1.0,
                    "alerts_triggered": alerts_triggered,
                },
                indent=2,
            )
        except Exception as e:
            log.warning(f"Local proactive alerts fallback: {e}")
            return json.dumps({"user_id": user_id, "has_alerts": False, "alerts_count": 0, "alerts_triggered": []})

    config = get_config()
    pid = config["project_id"]
    ds = config["dataset_id"]
    storage_engine = get_storage_engine()
    alerts_triggered = []
    hrv_z = 0.0
    rhr_z = 0.0
    ac_ratio = 1.0

    try:
        client = bigquery.Client(project=pid)
        # 1. Immune Radar (HRV Z & RHR Z)
        query_hrv = f"""
            SELECT date, avg_hrv
            FROM `{pid}.{ds}.hrv_history`
            WHERE user_id = '{user_id}' AND avg_hrv IS NOT NULL
            ORDER BY date DESC LIMIT 21
        """
        hrv_res = list(client.query(query_hrv).result())
        hrv_rows: list[float] = [float(r.avg_hrv) for r in hrv_res if getattr(r, "avg_hrv", None) is not None]

        query_rhr = f"""
            SELECT date, resting_heart_rate
            FROM `{pid}.{ds}.daily_physiology`
            WHERE user_id = '{user_id}' AND resting_heart_rate IS NOT NULL
            ORDER BY date DESC LIMIT 21
        """
        rhr_res = list(client.query(query_rhr).result())
        rhr_rows: list[float] = [
            float(r.resting_heart_rate) for r in rhr_res if getattr(r, "resting_heart_rate", None) is not None
        ]

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

                raw_date = getattr(hrv_res[0], "date", None)
                data_date = str(raw_date)[:10] if raw_date else str(date.today())[:10]
                alert_type = "immune_radar"
                payload_hash = hashlib.sha256(f"{user_id}:{hrv_z}:{rhr_z}".encode()).hexdigest()
                alert_key = hashlib.sha256(f"{user_id}|{alert_type}|{data_date}|{payload_hash}".encode()).hexdigest()

                if not storage_engine.is_alert_dispatched(alert_key, data_date=data_date):
                    if send_proactive_notification(user_id, immune_msg):
                        storage_engine.record_alert_dispatch(
                            alert_key=alert_key,
                            alert_type=alert_type,
                            data_date=data_date,
                            payload_hash=payload_hash,
                            channel="telegram",
                            user_id=user_id,
                        )
                else:
                    log.info(f"Skipping dispatch: {alert_type} for {user_id} on {data_date} already dispatched.")

        # 2. ACWR Workload Check
        query_acwr = f"""
            SELECT date, ac_ratio
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

                raw_acwr_date = getattr(acwr_rows[0], "date", None)
                acwr_date_str = str(raw_acwr_date)[:10] if raw_acwr_date else str(date.today())[:10]
                alert_type = "acwr_workload"
                payload_hash = hashlib.sha256(f"{user_id}:{ac_ratio}".encode()).hexdigest()
                alert_key = hashlib.sha256(
                    f"{user_id}|{alert_type}|{acwr_date_str}|{payload_hash}".encode()
                ).hexdigest()

                if not storage_engine.is_alert_dispatched(alert_key, data_date=acwr_date_str):
                    if send_proactive_notification(user_id, acwr_msg):
                        storage_engine.record_alert_dispatch(
                            alert_key=alert_key,
                            alert_type=alert_type,
                            data_date=acwr_date_str,
                            payload_hash=payload_hash,
                            channel="telegram",
                            user_id=user_id,
                        )
                else:
                    log.info(f"Skipping dispatch: {alert_type} for {user_id} on {acwr_date_str} already dispatched.")

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
