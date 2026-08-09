import json
from unittest.mock import MagicMock, patch

from src.tools.predictive_modeler import project_training_impact


@patch("src.tools.predictive_modeler.bigquery.Client")
def test_project_training_impact_simulation(mock_bq_client):
    """Test that project_training_impact simulates daily load and returns ACWR trajectory."""
    client_instance = MagicMock()
    mock_bq_client.return_value = client_instance

    mock_history_query = MagicMock()
    mock_history_query.result.return_value = []

    mock_calib_query = MagicMock()
    mock_calib_query.result.return_value = []

    client_instance.query.side_effect = [mock_history_query, mock_calib_query]

    proposed_sessions = [
        {"date": "2026-08-10", "duration_mins": 45, "avg_hr": 150},
        {"date": "2026-08-12", "duration_mins": 60, "avg_hr": 155},
    ]
    raw_res = project_training_impact.invoke(
        {
            "user_id": "test_user",
            "proposed_sessions": proposed_sessions,
            "projection_days": 7,
        }
    )

    res = json.loads(raw_res)
    assert res["user_id"] == "test_user"
    assert "peak_acwr" in res
    assert "simulation_timeline" in res
    assert len(res["simulation_timeline"]) >= 7
