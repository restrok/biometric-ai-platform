import json
from unittest.mock import patch

from src.tools.profile_manager import calibrate_profile_max_hr


@patch("src.tools.profile_manager.save_calibration_marker")
@patch("src.tools.profile_manager.get_user_profile")
def test_calibrate_profile_max_hr_triggered(mock_get_profile, mock_save_marker):
    """Test max_hr auto-calibration when peak HR exceeds stored threshold."""
    mock_get_profile.return_value = {
        "personal_calibration_profile": {
            "max_hr": {"value": 123.0},
            "resting_hr": {"value": 55.0},
        }
    }
    mock_save_marker.invoke.return_value = "Successfully saved marker"

    raw_res = calibrate_profile_max_hr.invoke(
        {
            "user_id": "mercedes",
            "observed_peak_hr": 179.0,
            "activity_name": "Tigre 10k Race",
        }
    )

    res = json.loads(raw_res)
    assert res["user_id"] == "mercedes"
    assert res["action"] == "MAX_HR_AUTOCALIBRATED"
    assert res["previous_max_hr"] == 123.0
    assert res["new_max_hr"] == 179.0
    assert "recalculated_karvonen_zones" in res
    mock_save_marker.invoke.assert_called_once()


@patch("src.tools.profile_manager.get_user_profile")
def test_calibrate_profile_max_hr_no_change(mock_get_profile):
    """Test max_hr when observed HR is within stored limit."""
    mock_get_profile.return_value = {
        "personal_calibration_profile": {
            "max_hr": {"value": 185.0},
        }
    }

    raw_res = calibrate_profile_max_hr.invoke(
        {
            "user_id": "fsirio",
            "observed_peak_hr": 165.0,
        }
    )

    res = json.loads(raw_res)
    assert res["user_id"] == "fsirio"
    assert res["action"] == "NO_CHANGE_NEEDED"
