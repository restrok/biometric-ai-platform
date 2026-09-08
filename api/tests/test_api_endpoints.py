"""Tests for FastAPI endpoints: /health, /setup, /dashboard, OAuth, and LocalSecureVault."""

import json
import os

import pytest
from fastapi.testclient import TestClient

# Ensure local test environment
os.environ["STORAGE_MODE"] = "local"
os.environ["AUTH_DISABLED"] = "true"

from main import app
from src.utils.vault import get_vault


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_setup_page(client: TestClient):
    response = client.get("/setup")
    assert response.status_code == 200
    assert "Biometric AI Platform - Setup Wizard" in response.text
    assert "Local-First (Offline)" in response.text
    assert "Garmin Connect Integration" in response.text
    assert "Fitbit Web API" in response.text
    assert "Google Health & Fitbit Air" in response.text


def test_setup_save(client: TestClient):
    payload = {
        "storage_mode": "local",
        "user_id": "test_athlete_onboarding",
        "llm_provider": "ollama",
        "embeddings_provider": "fastembed",
        "watch_provider": "fitbit",
        "generate_key": True,
    }
    response = client.post("/setup/save", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["user_id"] == "test_athlete_onboarding"
    assert data["api_key"].startswith("bio_")


def test_setup_save_with_simulated_fitbit_air(client: TestClient):
    payload = {
        "storage_mode": "local",
        "user_id": "athlete_fitbit_air_sim",
        "llm_provider": "ollama",
        "embeddings_provider": "fastembed",
        "watch_provider": "google_health",
        "use_mock_data": True,
        "generate_key": True,
    }
    response = client.post("/setup/save", json=payload)
    assert response.status_code == 200

    dash_resp = client.get("/dashboard/data?user_id=athlete_fitbit_air_sim")
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert len(dash_data.get("daily_physiology", [])) == 14
    assert len(dash_data.get("activities", [])) >= 5
    assert dash_data["health_status"]["feeling"] == "Ready & Rested"
    assert dash_data["goals"][0]["description"] == "Sub-40min 10K Target"


def test_setup_save_with_simulated_garmin(client: TestClient):
    payload = {
        "storage_mode": "local",
        "user_id": "athlete_garmin_sim",
        "watch_provider": "garmin",
        "use_mock_data": True,
        "generate_key": True,
    }
    response = client.post("/setup/save", json=payload)
    assert response.status_code == 200

    dash_resp = client.get("/dashboard/data?user_id=athlete_garmin_sim")
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert len(dash_data.get("daily_physiology", [])) == 14
    assert len(dash_data.get("activities", [])) >= 5
    # Verify Garmin Running Dynamics in summary
    summaries = [a.get("summary", "") for a in dash_data.get("activities", [])]
    assert any("Running Dynamics" in s for s in summaries)


def test_setup_save_with_garmin_sso_vault(client: TestClient):
    raw_sso = json.dumps({"di_token": "sso_tok_12345", "di_refresh_token": "ref_98765"})
    payload = {
        "storage_mode": "local",
        "user_id": "athlete_garmin_sso",
        "watch_provider": "garmin",
        "garmin_sso_tokens": raw_sso,
        "generate_key": True,
    }
    response = client.post("/setup/save", json=payload)
    assert response.status_code == 200

    # Verify tokens were stored encrypted in LocalSecureVault
    retrieved = get_vault().retrieve_tokens("garmin", "athlete_garmin_sso")
    assert retrieved is not None
    assert retrieved.get("di_token") == "sso_tok_12345"


def test_google_auth_login_redirect(client: TestClient):
    response = client.get("/auth/google/login?user_id=athlete_oauth_test", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers.get("location", "")
    assert "accounts.google.com/o/oauth2/v2/auth" in location
    assert "code_challenge=" in location
    assert "state=athlete_oauth_test" in location


def test_google_auth_login_json(client: TestClient):
    response = client.get(
        "/auth/google/login?user_id=athlete_oauth_test",
        headers={"accept": "application/json"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "auth_url" in data
    assert "state" in data
    assert "accounts.google.com" in data["auth_url"]


def test_fitbit_auth_login_redirect(client: TestClient):
    response = client.get("/auth/fitbit/login?user_id=athlete_fitbit_test", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers.get("location", "")
    assert "fitbit.com/oauth2/authorize" in location
    assert "code_challenge=" in location
    assert "state=athlete_fitbit_test" in location


def test_fitbit_auth_login_json(client: TestClient):
    response = client.get(
        "/auth/fitbit/login?user_id=athlete_fitbit_test",
        headers={"accept": "application/json"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "auth_url" in data
    assert "state" in data
    assert "fitbit.com/oauth2/authorize" in data["auth_url"]


def test_dashboard_page(client: TestClient):
    response = client.get("/dashboard?user_id=test_athlete_onboarding")
    assert response.status_code == 200
    assert "Biometric AI Coach - Dashboard" in response.text
    assert "test_athlete_onboarding" in response.text


def test_dashboard_data(client: TestClient):
    response = client.get("/dashboard/data?user_id=test_athlete_onboarding")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "test_athlete_onboarding"
    assert "profile" in data
    assert "goals" in data
    assert "activities" in data


def test_dashboard_users(client: TestClient):
    response = client.get("/dashboard/users")
    assert response.status_code == 200
    data = response.json()
    assert "users" in data
    assert isinstance(data["users"], list)
