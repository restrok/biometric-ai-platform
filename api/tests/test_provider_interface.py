from garmin_training_toolkit_sdk.core.base import BaseBiometricProvider
from garmin_training_toolkit_sdk.protocol.workouts import WorkoutPlan

from src.utils.provider_factory import get_provider


def test_provider_instantiation():
    """Verify that the factory returns a valid BaseBiometricProvider."""
    provider = get_provider()
    assert isinstance(provider, BaseBiometricProvider)
    assert hasattr(provider, "get_activities")
    assert hasattr(provider, "upload_training_plan")


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
    plan = WorkoutPlan(root=raw_plan)
    assert len(plan.root) == 1
    assert plan.root[0].steps[0].target.min_target == 140.0
