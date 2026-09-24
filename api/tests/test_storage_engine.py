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


def test_alert_dispatch_log_local(temp_storage: LocalStorageEngine):
    alert_key = "test_key_123"
    assert temp_storage.is_alert_dispatched(alert_key, data_date="2026-09-23") is False

    temp_storage.record_alert_dispatch(
        alert_key=alert_key,
        alert_type="immune_radar",
        data_date="2026-09-23",
        payload_hash="hash123",
        channel="telegram",
        user_id="test_athlete",
    )

    assert temp_storage.is_alert_dispatched(alert_key, data_date="2026-09-23") is True
    assert temp_storage.is_alert_dispatched(alert_key) is True
    assert temp_storage.is_alert_dispatched("non_existent_key") is False


def test_alert_dispatch_log_gcp():
    from unittest.mock import MagicMock, patch

    from src.storage.gcp_engine import GCPStorageEngine

    with (
        patch("src.storage.gcp_engine.bigquery.Client") as mock_bq_cls,
        patch("src.storage.gcp_engine.firestore.Client"),
    ):
        mock_bq = MagicMock()
        mock_bq_cls.return_value = mock_bq

        engine = GCPStorageEngine(project_id="test-proj", dataset_id="test-ds")

        # Test is_alert_dispatched returns False when no rows
        mock_job = MagicMock()
        mock_job.result.return_value = []
        mock_bq.query.return_value = mock_job

        assert engine.is_alert_dispatched("gcp_key", data_date="2026-09-23") is False

        # Verify query used data_date filter (partition pruning)
        call_args = mock_bq.query.call_args
        sql = call_args[0][0]
        assert "WHERE data_date = @data_date AND alert_key = @alert_key" in sql

        # Test record_alert_dispatch uses DML INSERT
        engine.record_alert_dispatch(
            alert_key="gcp_key",
            alert_type="immune_radar",
            data_date="2026-09-23",
            payload_hash="gcp_hash",
            channel="telegram",
            user_id="test_athlete",
        )
        insert_args = mock_bq.query.call_args
        insert_sql = insert_args[0][0]
        assert "INSERT INTO `test-proj.test-ds.alert_dispatch_log`" in insert_sql


def test_daily_physiology_and_hrv_readings_local(temp_storage: LocalStorageEngine):
    user_id = "test_athlete"

    # 1. Insert daily physiology with body_battery_charged_sleep
    temp_storage.insert_daily_physiology(
        user_id,
        [
            {
                "date": "2026-09-22",
                "resting_heart_rate": 48,
                "hrv_rmssd": 65.0,
                "body_battery_max": 95,
                "body_battery_min": 25,
                "stress_avg": 22,
                "sleep_duration_seconds": 28800.0,
                "sleep_score": 88,
                "body_battery_charged_sleep": 45,
            }
        ],
    )

    phys = temp_storage.get_daily_physiology(user_id, days=5)
    assert len(phys) == 1
    assert phys[0]["body_battery_charged_sleep"] == 45
    assert phys[0]["resting_heart_rate"] == 48

    # 2. Insert raw 5-minute HRV readings
    readings = [
        {"date": "2026-09-22", "timestamp_ms": 1790123456000, "hrv_value": 62.5},
        {"date": "2026-09-22", "timestamp_ms": 1790123756000, "hrv_value": 67.0},
    ]
    temp_storage.insert_hrv_readings(user_id, readings)

    # Verify DuckDB table contents
    conn = temp_storage._get_duckdb_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM hrv_readings_history WHERE user_id = ? ORDER BY timestamp_ms ASC",
            [user_id],
        ).fetchall()
        assert len(rows) == 2
        assert any(1790123456000 in r for r in rows)
    finally:
        conn.close()


def test_hrv_readings_gcp():
    from unittest.mock import MagicMock, patch

    from src.storage.gcp_engine import GCPStorageEngine

    with (
        patch("src.storage.gcp_engine.bigquery.Client") as mock_bq_cls,
        patch("src.storage.gcp_engine.firestore.Client"),
    ):
        mock_bq = MagicMock()
        mock_bq_cls.return_value = mock_bq

        engine = GCPStorageEngine(project_id="test-proj", dataset_id="test-ds")
        readings = [
            {"date": "2026-09-22", "timestamp_ms": 1790123456000, "hrv_value": 62.5},
        ]
        engine.insert_hrv_readings("test_athlete", readings)

        mock_bq.insert_rows_json.assert_called_once()
        call_args = mock_bq.insert_rows_json.call_args
        table_id = call_args[0][0]
        rows = call_args[0][1]
        assert table_id == "test-proj.test-ds.hrv_readings_history"
        assert len(rows) == 1
        assert rows[0]["user_id"] == "test_athlete"
        assert rows[0]["hrv_value"] == 62.5

