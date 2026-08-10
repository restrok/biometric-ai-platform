import json
from unittest.mock import MagicMock, patch

from src.tools.historical_biometrics import compare_shoe_biomechanics
from src.tools.predictive_modeler import calculate_critical_power_and_w_prime


@patch("src.tools.predictive_modeler.bigquery.Client")
def test_calculate_critical_power_and_w_prime(mock_bq):
    """Test Critical Power and W' calculation tool."""
    mock_client = MagicMock()
    mock_bq.return_value = mock_client
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [MagicMock(peak_power=310.0, peak_3m_w=290.0, peak_12m_w=255.0)]
    mock_client.query.return_value = mock_query_job

    raw_res = calculate_critical_power_and_w_prime.invoke(
        {
            "user_id": "fsirio",
            "target_power_watts": 268.0,
            "target_duration_mins": 50.0,
        }
    )

    res = json.loads(raw_res)
    assert res["user_id"] == "fsirio"
    assert "critical_power_cp_watts" in res["critical_power_model"]
    assert "w_prime_anaerobic_reserve_kj" in res["critical_power_model"]
    assert res["target_event_assessment"]["target_10k_power_watts"] == 268.0


@patch("src.tools.historical_biometrics.bigquery.Client")
def test_compare_shoe_biomechanics(mock_bq):
    """Test shoe biomechanics comparison tool."""
    mock_client = MagicMock()
    mock_bq.return_value = mock_client

    mock_pre_job = MagicMock()
    mock_pre_job.result.return_value = [
        MagicMock(
            run_count=10,
            avg_gct_ms=248.0,
            avg_vert_osc_cm=8.4,
            avg_stride_m=1.08,
            avg_cadence_spm=168.0,
            avg_w_hr=1.52,
        )
    ]

    mock_post_job = MagicMock()
    mock_post_job.result.return_value = [
        MagicMock(
            run_count=12,
            avg_gct_ms=238.0,
            avg_vert_osc_cm=7.6,
            avg_stride_m=1.14,
            avg_cadence_spm=174.0,
            avg_w_hr=1.61,
        )
    ]

    mock_client.query.side_effect = [mock_pre_job, mock_post_job]

    raw_res = compare_shoe_biomechanics.invoke(
        {
            "user_id": "fsirio",
            "switch_date": "2026-07-18",
        }
    )

    res = json.loads(raw_res)
    assert res["user_id"] == "fsirio"
    assert res["switch_date"] == "2026-07-18"
    assert "metrics_comparison" in res
    assert res["metrics_comparison"]["ground_contact_time_ms"]["delta_ms"] == -10.0
    assert "SIGNIFICANT BIOMECHANICAL IMPROVEMENT" in res["biomechanical_verdict"]
