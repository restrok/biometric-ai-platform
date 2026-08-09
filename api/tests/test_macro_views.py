import json
from unittest.mock import MagicMock, patch

from src.tools.historical_biometrics import query_macro_load_history


@patch("src.tools.historical_biometrics.get_bq_client")
def test_query_macro_load_history(mock_get_client):
    """Test query_macro_load_history tool returns macro aggregated data."""
    client_instance = MagicMock()
    mock_get_client.return_value = client_instance

    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [
        {
            "user_id": "test_user",
            "week_start_date": "2026-08-03",
            "runs_count": 3,
            "total_distance_km": 25.5,
            "total_duration_hours": 2.5,
            "total_work_kj": 2100.0,
            "total_trimp": 140.0,
            "avg_hr": 150.0,
            "avg_pace": 2.1,
            "avg_power": 230.0,
        }
    ]
    client_instance.query.return_value = mock_query_job

    raw_res = query_macro_load_history.invoke(
        {
            "user_id": "test_user",
            "group_by": "weekly",
            "limit_months": 3,
        }
    )

    res = json.loads(raw_res)
    assert res["user_id"] == "test_user"
    assert res["group_by"] == "weekly"
    assert res["record_count"] == 1
    assert len(res["macro_history"]) == 1
    assert res["macro_history"][0]["total_distance_km"] == 25.5
