from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


@patch("src.routers.tools.retrieve_biometric_data")
def test_retrieve_biometric_endpoint(mock_tool):
    mock_tool.invoke.return_value = {"activities": []}
    response = client.post("/api/v1/tools/biometric/retrieve", json={"project_id": "test-project"})
    assert response.status_code == 200
    assert response.json() == {"status": "success", "data": {"activities": []}}
    mock_tool.invoke.assert_called_once_with(
        {"project_id": "test-project", "dataset": None, "limit": 20, "offset": 0, "activity_type": None}
    )


@patch("src.routers.tools.analyze_activity_efficiency")
def test_analyze_efficiency_endpoint(mock_tool):
    mock_tool.invoke.return_value = {"avg_hr": 150}
    response = client.post("/api/v1/tools/activity/analyze_efficiency", json={"activity_id": "12345"})
    assert response.status_code == 200
    assert response.json() == {"status": "success", "data": {"avg_hr": 150}}
    mock_tool.invoke.assert_called_once_with({"activity_id": "12345"})


@patch("src.routers.tools.sync_biometric_data")
def test_sync_biometric_endpoint(mock_tool):
    mock_tool.invoke.return_value = "Success"
    response = client.post("/api/v1/tools/biometric/sync")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Success"}


@patch("src.routers.tools.update_user_zones")
def test_update_zones_endpoint(mock_tool):
    mock_tool.invoke.return_value = "Updated"
    payload = {"z1_max": 140, "z2_max": 150, "z3_max": 160, "z4_max": 170}
    response = client.post("/api/v1/tools/zones/update", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Updated"}
    mock_tool.invoke.assert_called_once_with(payload)


@patch("src.routers.tools.upload_training_plan")
def test_upload_plan_endpoint(mock_tool):
    mock_tool.invoke.return_value = "Success: Uploaded"
    payload = {
        "workouts": [{"name": "Test", "duration": 30, "date": "2026-05-01", "steps": [{"type": "run", "duration": 30}]}]
    }
    response = client.post("/api/v1/tools/training_plan/upload", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"


@patch("src.routers.tools.refresh_garmin_session")
@patch("src.routers.tools.find_token_file")
def test_refresh_session_endpoint(mock_find, mock_refresh):
    mock_find.return_value = MagicMock()
    mock_refresh.return_value = True
    response = client.post("/api/v1/tools/session/refresh")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Successfully refreshed biometric session."}
