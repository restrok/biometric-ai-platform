import json
from unittest.mock import MagicMock, patch

from src.tools.alerting import check_proactive_alerts


@patch("src.tools.alerting.get_storage_engine")
@patch("src.tools.alerting.send_proactive_notification")
@patch("src.tools.alerting.bigquery.Client")
def test_check_proactive_alerts(mock_bq_client, mock_send_notif, mock_get_engine):
    """Test check_proactive_alerts tool functionality and dispatch recording."""
    mock_engine = MagicMock()
    mock_engine.is_alert_dispatched.return_value = False
    mock_get_engine.return_value = mock_engine
    mock_send_notif.return_value = True

    client_instance = MagicMock()
    mock_bq_client.return_value = client_instance

    # Mock HRV query
    mock_hrv_query = MagicMock()
    mock_hrv_query.result.return_value = [
        MagicMock(avg_hrv=30.0, date="2026-09-23"),
        MagicMock(avg_hrv=50.0, date="2026-09-22"),
        MagicMock(avg_hrv=52.0, date="2026-09-21"),
        MagicMock(avg_hrv=48.0, date="2026-09-20"),
        MagicMock(avg_hrv=51.0, date="2026-09-19"),
        MagicMock(avg_hrv=49.0, date="2026-09-18"),
    ]

    # Mock RHR query
    mock_rhr_query = MagicMock()
    mock_rhr_query.result.return_value = [
        MagicMock(resting_heart_rate=75.0, date="2026-09-23"),
        MagicMock(resting_heart_rate=60.0, date="2026-09-22"),
        MagicMock(resting_heart_rate=61.0, date="2026-09-21"),
        MagicMock(resting_heart_rate=59.0, date="2026-09-20"),
        MagicMock(resting_heart_rate=60.0, date="2026-09-19"),
        MagicMock(resting_heart_rate=62.0, date="2026-09-18"),
    ]

    # Mock ACWR query
    mock_acwr_query = MagicMock()
    mock_acwr_query.result.return_value = [MagicMock(ac_ratio=1.42, date="2026-09-23")]

    client_instance.query.side_effect = [mock_hrv_query, mock_rhr_query, mock_acwr_query]

    raw_res = check_proactive_alerts.invoke({"user_id": "test_user"})
    res = json.loads(raw_res)

    assert res["user_id"] == "test_user"
    assert res["has_alerts"] is True
    assert res["acwr_ratio"] == 1.42
    assert len(res["alerts_triggered"]) == 2
    assert mock_send_notif.call_count == 2
    assert mock_engine.record_alert_dispatch.call_count == 2


@patch("src.tools.alerting.get_storage_engine")
@patch("src.tools.alerting.send_proactive_notification")
@patch("src.tools.alerting.bigquery.Client")
def test_check_proactive_alerts_dedup(mock_bq_client, mock_send_notif, mock_get_engine):
    """Test that check_proactive_alerts does not send notifications when already dispatched."""
    mock_engine = MagicMock()
    mock_engine.is_alert_dispatched.return_value = True
    mock_get_engine.return_value = mock_engine

    client_instance = MagicMock()
    mock_bq_client.return_value = client_instance

    mock_hrv_query = MagicMock()
    mock_hrv_query.result.return_value = [
        MagicMock(avg_hrv=30.0, date="2026-09-23"),
        MagicMock(avg_hrv=50.0, date="2026-09-22"),
        MagicMock(avg_hrv=52.0, date="2026-09-21"),
        MagicMock(avg_hrv=48.0, date="2026-09-20"),
        MagicMock(avg_hrv=51.0, date="2026-09-19"),
        MagicMock(avg_hrv=49.0, date="2026-09-18"),
    ]

    mock_rhr_query = MagicMock()
    mock_rhr_query.result.return_value = [
        MagicMock(resting_heart_rate=75.0, date="2026-09-23"),
        MagicMock(resting_heart_rate=60.0, date="2026-09-22"),
        MagicMock(resting_heart_rate=61.0, date="2026-09-21"),
        MagicMock(resting_heart_rate=59.0, date="2026-09-20"),
        MagicMock(resting_heart_rate=60.0, date="2026-09-19"),
        MagicMock(resting_heart_rate=62.0, date="2026-09-18"),
    ]

    mock_acwr_query = MagicMock()
    mock_acwr_query.result.return_value = [MagicMock(ac_ratio=1.42, date="2026-09-23")]

    client_instance.query.side_effect = [mock_hrv_query, mock_rhr_query, mock_acwr_query]

    raw_res = check_proactive_alerts.invoke({"user_id": "test_user"})
    res = json.loads(raw_res)

    assert res["user_id"] == "test_user"
    assert res["has_alerts"] is True
    assert len(res["alerts_triggered"]) == 2
    # Dispatches were skipped due to dedup!
    mock_send_notif.assert_not_called()
    mock_engine.record_alert_dispatch.assert_not_called()


@patch("src.tools.alerting.get_storage_engine")
@patch("src.tools.alerting.send_proactive_notification")
def test_check_proactive_alerts_local(mock_send_notif, mock_get_engine, monkeypatch):
    """Test local storage engine alerting and deduplication."""
    monkeypatch.setenv("STORAGE_MODE", "local")
    mock_engine = MagicMock()
    mock_engine.get_daily_physiology.return_value = [
        {"date": "2026-09-23", "hrv_rmssd": 20.0, "resting_heart_rate": 80.0},
        {"date": "2026-09-22", "hrv_rmssd": 50.0, "resting_heart_rate": 60.0},
        {"date": "2026-09-21", "hrv_rmssd": 52.0, "resting_heart_rate": 61.0},
        {"date": "2026-09-20", "hrv_rmssd": 48.0, "resting_heart_rate": 59.0},
        {"date": "2026-09-19", "hrv_rmssd": 51.0, "resting_heart_rate": 60.0},
        {"date": "2026-09-18", "hrv_rmssd": 49.0, "resting_heart_rate": 62.0},
    ]
    mock_engine.is_alert_dispatched.return_value = False
    mock_send_notif.return_value = True
    mock_get_engine.return_value = mock_engine

    raw_res = check_proactive_alerts.invoke({"user_id": "test_user"})
    res = json.loads(raw_res)

    assert res["has_alerts"] is True
    assert mock_send_notif.call_count == 1
    assert mock_engine.record_alert_dispatch.call_count == 1
