import json
from unittest.mock import MagicMock, patch

from src.tools.nutrition_modeler import assess_glycogen_readiness


@patch("src.tools.nutrition_modeler.bigquery.Client")
@patch("src.tools.nutrition_modeler.retrieve_biometric_data")
def test_assess_glycogen_readiness_high_band(mock_retrieve, mock_bq):
    """Test assess_glycogen_readiness tool with dense carb intake (HIGH band)."""
    mock_retrieve.invoke.return_value = {
        "semantic_memories": [
            "[2026-08-08] Nutritional Log: Dinner: Salad, chard pie (tarta de acelga), pizza.",
            "[2026-08-09] Nutritional Log: Lunch: Asado (vacío), salad, red wine.",
            "[2026-05-25] Nutritional Log: Dense carb load: Guiso and calzone.",
        ]
    }

    mock_client = MagicMock()
    mock_bq.return_value = mock_client
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [MagicMock(avg_efficiency_w_hr=1.61)]
    mock_client.query.return_value = mock_query_job

    raw_res = assess_glycogen_readiness.invoke(
        {
            "user_id": "fsirio",
            "target_power_watts": 300.0,
            "duration_mins": 20.0,
        }
    )

    res = json.loads(raw_res)
    assert res["user_id"] == "fsirio"
    assert res["glycogen_readiness"]["band"] == "HIGH"
    assert res["glycogen_readiness"]["readiness_status"] == "OPTIMAL"
    assert res["target_workout"]["work_kj"] == 360.0
    assert "OPTIMAL FUELING" in res["fueling_recommendation"]


@patch("src.tools.nutrition_modeler.bigquery.Client")
@patch("src.tools.nutrition_modeler.retrieve_biometric_data")
def test_assess_glycogen_readiness_low_band(mock_retrieve, mock_bq):
    """Test assess_glycogen_readiness tool with low carb intake (LOW band)."""
    mock_retrieve.invoke.return_value = {
        "semantic_memories": [
            "[2026-08-08] Nutritional Log: Dinner: Green salad and grilled chicken.",
        ]
    }

    mock_client = MagicMock()
    mock_bq.return_value = mock_client
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [MagicMock(avg_efficiency_w_hr=1.50)]
    mock_client.query.return_value = mock_query_job

    raw_res = assess_glycogen_readiness.invoke(
        {
            "user_id": "test_athlete",
            "target_power_watts": 300.0,
            "duration_mins": 20.0,
        }
    )

    res = json.loads(raw_res)
    assert res["user_id"] == "test_athlete"
    assert res["glycogen_readiness"]["band"] == "LOW"
    assert res["glycogen_readiness"]["readiness_status"] == "UNFAVORABLE"
    assert "CRITICAL FUELING DEFICIT" in res["fueling_recommendation"]
