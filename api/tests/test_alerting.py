import json
from unittest.mock import MagicMock, patch

from src.tools.alerting import check_proactive_alerts


@patch("src.tools.alerting.send_proactive_notification")
@patch("src.tools.alerting.bigquery.Client")
def test_check_proactive_alerts(mock_bq_client, mock_send_notif):
    """Test check_proactive_alerts tool functionality."""
    client_instance = MagicMock()
    mock_bq_client.return_value = client_instance

    # Mock HRV query
    mock_hrv_query = MagicMock()
    mock_hrv_query.result.return_value = [
        MagicMock(avg_hrv=30.0),
        MagicMock(avg_hrv=50.0),
        MagicMock(avg_hrv=52.0),
        MagicMock(avg_hrv=48.0),
        MagicMock(avg_hrv=51.0),
        MagicMock(avg_hrv=49.0),
    ]

    # Mock RHR query
    mock_rhr_query = MagicMock()
    mock_rhr_query.result.return_value = [
        MagicMock(resting_heart_rate=75.0),
        MagicMock(resting_heart_rate=60.0),
        MagicMock(resting_heart_rate=61.0),
        MagicMock(resting_heart_rate=59.0),
        MagicMock(resting_heart_rate=60.0),
        MagicMock(resting_heart_rate=62.0),
    ]

    # Mock ACWR query
    mock_acwr_query = MagicMock()
    mock_acwr_query.result.return_value = [MagicMock(ac_ratio=1.42)]

    client_instance.query.side_effect = [mock_hrv_query, mock_rhr_query, mock_acwr_query]

    raw_res = check_proactive_alerts.invoke({"user_id": "test_user"})
    res = json.loads(raw_res)

    assert res["user_id"] == "test_user"
    assert res["has_alerts"] is True
    assert res["acwr_ratio"] == 1.42
    assert len(res["alerts_triggered"]) >= 1
