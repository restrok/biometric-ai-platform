"""Unit tests for LocalStorageEngine (SQLite + DuckDB)."""

import shutil
import tempfile
from datetime import datetime

import pytest

from src.storage.local_engine import LocalStorageEngine


@pytest.fixture
def temp_storage():
    temp_dir = tempfile.mkdtemp()
    engine = LocalStorageEngine(data_dir=temp_dir)
    yield engine
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_user_profile_crud(temp_storage: LocalStorageEngine):
    user_id = "test_athlete"
    assert temp_storage.get_user_profile(user_id) == {}

    temp_storage.update_user_profile(user_id, {"name": "Test Runner", "custom_zones": {"z1_max": 130, "z2_max": 145}})
    profile = temp_storage.get_user_profile(user_id)
    assert profile["name"] == "Test Runner"
    assert profile["custom_zones"]["z1_max"] == 130

    temp_storage.update_user_profile(user_id, {"age": 30})
    updated = temp_storage.get_user_profile(user_id)
    assert updated["name"] == "Test Runner"
    assert updated["age"] == 30


def test_user_goals_crud(temp_storage: LocalStorageEngine):
    user_id = "test_athlete"
    goal_id = temp_storage.save_user_goal(
        user_id,
        {
            "goal_type": "half_marathon",
            "description": "Sub 1:40 HM",
            "target_date": "2026-11-15",
            "status": "active",
        },
    )
    assert goal_id is not None
    goals = temp_storage.get_user_goals(user_id)
    assert len(goals) == 1
    assert goals[0]["goal_type"] == "half_marathon"
    assert goals[0]["description"] == "Sub 1:40 HM"


def test_semantic_memories_crud(temp_storage: LocalStorageEngine):
    user_id = "test_athlete"
    mem_id = temp_storage.save_semantic_memory(
        user_id,
        memory_text="Prefers running in early mornings",
        memory_type="preference",
    )
    assert mem_id is not None

    memories = temp_storage.get_semantic_memories(user_id)
    assert len(memories) == 1
    assert memories[0]["memory_text"] == "Prefers running in early mornings"

    # Update
    res_update = temp_storage.update_semantic_memory(mem_id, "Prefers running at 6am sharp")
    assert "Successfully updated" in res_update
    memories = temp_storage.get_semantic_memories(user_id)
    assert memories[0]["memory_text"] == "Prefers running at 6am sharp"

    # Retire
    res_retire = temp_storage.retire_semantic_memory(mem_id)
    assert "Successfully retired" in res_retire
    assert len(temp_storage.get_semantic_memories(user_id)) == 0


def test_calibration_and_health(temp_storage: LocalStorageEngine):
    user_id = "test_athlete"
    m_id = temp_storage.save_calibration_marker(user_id, "max_hr", 192.0, "5k race finish")
    assert m_id is not None
    markers = temp_storage.get_calibration_markers(user_id)
    assert len(markers) == 1
    assert markers[0]["marker_value"] == 192.0

    # Health status
    date_str = temp_storage.log_health_status(
        user_id,
        {
            "date": "2026-09-08",
            "feeling": "Great",
            "fatigue_level": 2,
            "notes": "Well rested",
        },
    )
    assert date_str == "2026-09-08"
    status = temp_storage.get_health_status(user_id)
    assert status is not None
    assert status["feeling"] == "Great"
    assert status["fatigue_level"] == 2


def test_activities_and_analytics(temp_storage: LocalStorageEngine):
    user_id = "test_athlete"
    now_ts = datetime(2026, 9, 8, 8, 0, 0)
    temp_storage.insert_activities(
        user_id,
        [
            {
                "activity_id": "act_1001",
                "activity_name": "Easy Base Run",
                "activity_type": "running",
                "start_time": now_ts,
                "duration_seconds": 3600.0,
                "distance_meters": 10000.0,
                "avg_heart_rate": 142.0,
                "max_heart_rate": 155.0,
                "aerobic_training_effect": 3.2,
                "trimp": 85.0,
            }
        ],
    )

    activities = temp_storage.get_recent_activities(user_id, limit=5)
    assert len(activities) == 1
    assert activities[0]["activity_name"] == "Easy Base Run"
    assert activities[0]["distance_meters"] == 10000.0

    # Test macro history
    history = temp_storage.query_macro_load_history(user_id, group_by="weekly", limit_months=1)
    assert len(history) >= 1
    assert history[0]["total_sessions"] == 1


def test_api_keys_security(temp_storage: LocalStorageEngine):
    user_id = "test_athlete"
    api_key = temp_storage.create_api_key(user_id, name="runner_mobile_app")
    assert api_key.startswith("bio_")

    assert temp_storage.validate_api_key(api_key, user_id) is True
    assert temp_storage.validate_api_key("invalid_key", user_id) is False
    assert temp_storage.validate_api_key(api_key, "another_athlete") is False
