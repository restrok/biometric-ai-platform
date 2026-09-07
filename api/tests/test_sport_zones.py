import json
from unittest.mock import MagicMock, patch

from src.tools.profile_manager import get_sport_zones, update_sport_zones
from src.tools.retriever import retrieve_biometric_data
from src.utils.physiology import calculate_sport_hr_zones


def test_calculate_sport_hr_zones_running():
    """Test standard running heart rate zones."""
    running_zones = {"z1_max": 115, "z2_max": 142, "z3_max": 155, "z4_max": 170, "z5_max": 185}
    zones = calculate_sport_hr_zones(running_zones=running_zones, sport="running")

    assert zones.sport == "running"
    assert zones.z1_max == 115
    assert zones.z2_max == 142
    assert zones.aet_hr == 142
    assert zones.z4_max == 170
    assert zones.ant_hr == 170
    assert zones.hr_offset_from_running_bpm == 0


def test_calculate_sport_hr_zones_swimming_offset():
    """Test swimming heart rate zones with physiological -13 bpm shift."""
    running_zones = {"z1_max": 115, "z2_max": 142, "z3_max": 155, "z4_max": 170, "z5_max": 185}
    swim_zones = calculate_sport_hr_zones(running_zones=running_zones, sport="swimming")

    assert swim_zones.sport == "swimming"
    # AeT drops from 142 to 129 bpm (~12-14 bpm lower)
    assert swim_zones.z2_max == 129
    assert swim_zones.aet_hr == 129
    # AnT drops from 170 to 157 bpm (170 - 13)
    assert swim_zones.z4_max == 157
    assert swim_zones.ant_hr == 157
    assert swim_zones.hr_offset_from_running_bpm == -13


def test_calculate_sport_hr_zones_cycling():
    """Test cycling heart rate zones with -6 bpm shift."""
    running_zones = {"z1_max": 115, "z2_max": 142, "z3_max": 155, "z4_max": 170, "z5_max": 185}
    cycle_zones = calculate_sport_hr_zones(running_zones=running_zones, sport="cycling")

    assert cycle_zones.sport == "cycling"
    assert cycle_zones.z2_max == 136
    assert cycle_zones.hr_offset_from_running_bpm == -6


@patch("src.tools.profile_manager.update_user_profile")
@patch("src.tools.profile_manager.get_user_profile")
def test_update_and_get_sport_zones(mock_get_profile, mock_update_profile):
    """Test update_sport_zones and get_sport_zones tools."""
    mock_get_profile.return_value = {
        "custom_zones": {"z1_max": 115, "z2_max": 142, "z3_max": 155, "z4_max": 170},
        "max_hr": 183,
        "resting_hr": 60,
    }

    # 1. Update swimming zones
    res_update = update_sport_zones.invoke(
        {
            "user_id": "mercedes",
            "sport": "swimming",
            "z1_max": 103,
            "z2_max": 128,
            "z3_max": 142,
            "z4_max": 156,
            "z5_max": 170,
        }
    )
    assert "Successfully updated swimming heart rate zones" in res_update
    mock_update_profile.assert_called_once()

    # 2. Get sport zones (derived fallback)
    raw_get = get_sport_zones.invoke({"user_id": "mercedes", "sport": "swimming"})
    res_get = json.loads(raw_get)
    assert res_get["user_id"] == "mercedes"
    assert res_get["sport"] == "swimming"
    assert res_get["zones"]["z2_max"] == 129  # 142 - 13
    assert "Frank-Starling" in res_get["physiological_note"]


@patch("src.tools.retriever.get_user_profile")
@patch("src.tools.retriever.bigquery.Client")
def test_retriever_includes_sport_zones(mock_bq, mock_get_profile):
    """Test that retrieve_biometric_data includes sport_zones with running and swimming."""
    mock_get_profile.return_value = {
        "custom_zones": {"z1_max": 115, "z2_max": 142, "z3_max": 155, "z4_max": 170},
        "max_hr": 183,
        "resting_hr": 60,
    }
    mock_client = MagicMock()
    mock_bq.return_value = mock_client
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = []
    mock_client.query.return_value = mock_query_job

    data = retrieve_biometric_data.invoke({"user_id": "mercedes"})
    profile = data.get("user_profile", {})

    assert "sport_zones" in profile
    assert "running" in profile["sport_zones"]
    assert "swimming" in profile["sport_zones"]
    assert profile["sport_zones"]["running"]["aet_hr"] == 142
    assert profile["sport_zones"]["swimming"]["aet_hr"] == 129
