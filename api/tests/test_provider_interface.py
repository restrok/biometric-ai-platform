from unittest.mock import patch, MagicMock
from garmin_training_toolkit_sdk.core.base import BaseBiometricProvider
from garmin_training_toolkit_sdk.protocol.workouts import WorkoutPlan

from src.utils.provider_factory import get_provider


@patch("src.utils.provider_factory.GarminProvider")
@patch("src.utils.provider_factory.find_token_file")
def test_provider_instantiation(mock_find_token, mock_garmin_provider):
    """Verify that the factory returns a valid BaseBiometricProvider using mocks."""
    mock_find_token.return_value = "dummy_token.json"
    mock_provider_instance = MagicMock(spec=BaseBiometricProvider)
    mock_garmin_provider.return_value = mock_provider_instance

    provider = get_provider()
    assert provider == mock_provider_instance


def test_workout_protocol_validation():
    """Verify that the SDK's new semantic protocol validates correctly."""
    # This tests if the SDK (v0.4.0) accepts our new semantic names
    raw_plan = [
        {
            "name": "Test SDK 0.4.0",
            "description": "Validation test",
            "duration": 30.0,
            "date": "2026-05-01",
            "steps": [
                {
                    "type": "run",
                    "duration": 30.0,
                    "target": {"target_type": "heart.rate.zone", "min_target": 140, "max_target": 150},
                }
            ],
        }
    ]
    # If this doesn't raise a Pydantic error, the SDK is compatible with our tool's logic
    from typing import Any, cast

    plan = WorkoutPlan(root=cast(Any, raw_plan))
    assert len(plan.root) == 1
    # Cast to Any to bypass complex union attribute check
    step: Any = plan.root[0].steps[0]
    assert step.target.min_target == 140.0
