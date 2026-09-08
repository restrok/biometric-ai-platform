"""Tests for FastAPI endpoints: /health, /setup, /dashboard, OAuth, and LocalSecureVault."""

import json
import os

import pytest
from fastapi.testclient import TestClient

# Ensure local test environment
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("AUTH_DISABLED", "true")


@pytest.fixture(scope="module", autouse=True)
def clean_env_teardown():
    orig_mode = os.environ.get("STORAGE_MODE")
    orig_auth = os.environ.get("AUTH_DISABLED")
    os.environ["STORAGE_MODE"] = "local"
    os.environ["AUTH_DISABLED"] = "true"
    yield
    if orig_mode is not None:
        os.environ["STORAGE_MODE"] = orig_mode
    else:
        os.environ.pop("STORAGE_MODE", None)
    if orig_auth is not None:
        os.environ["AUTH_DISABLED"] = orig_auth
    else:
        os.environ.pop("AUTH_DISABLED", None)
    from src.storage.factory import reset_storage_engine

    reset_storage_engine()


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
    response = client.get("/auth/google/login?user_id=athlete_oauth_test", headers={"accept": "application/json"})
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
    response = client.get("/auth/fitbit/login?user_id=athlete_fitbit_test", headers={"accept": "application/json"})
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


from unittest.mock import patch


def test_garmin_exchange_endpoint_invalid_ticket(client: TestClient):
    response = client.post(
        "/auth/garmin/exchange", json={"ticket_or_url": "invalid-url-without-st", "user_id": "athlete_test"}
    )
    assert response.status_code == 400
    assert "No se encontró un ticket válido" in response.json()["detail"]


def test_garmin_exchange_endpoint_mocked(client: TestClient):
    mock_tokens = {"di_token": "mock_di_token_abc", "di_refresh_token": "mock_ref_123", "di_client_id": "test_client"}
    with patch("garmin_training_toolkit_sdk.auth.get_tokens_from_ticket", return_value=mock_tokens):
        response = client.post(
            "/auth/garmin/exchange",
            json={
                "ticket_or_url": "https://sso.garmin.com/sso/embed?ticket=ST-TEST-TICKET-999",
                "user_id": "athlete_garmin_mock_exchange",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        saved = get_vault().retrieve_tokens("garmin", "athlete_garmin_mock_exchange")
        assert saved is not None
        assert saved.get("di_token") == "mock_di_token_abc"


def test_setup_save_with_garmin_ticket_url(client: TestClient):
    mock_tokens = {
        "di_token": "mock_di_token_from_setup",
        "di_refresh_token": "mock_ref_from_setup",
        "di_client_id": "test_client",
    }
    with patch("garmin_training_toolkit_sdk.auth.get_tokens_from_ticket", return_value=mock_tokens):
        payload = {
            "storage_mode": "local",
            "user_id": "athlete_garmin_ticket_setup",
            "watch_provider": "garmin",
            "garmin_sso_tokens": "https://sso.garmin.com/sso/embed?ticket=ST-12345-SETUP-TEST",
            "generate_key": True,
        }
        response = client.post("/setup/save", json=payload)
        assert response.status_code == 200

        saved = get_vault().retrieve_tokens("garmin", "athlete_garmin_ticket_setup")
        assert saved is not None
        assert saved.get("di_token") == "mock_di_token_from_setup"


def test_chat_endpoint_empty_message(client: TestClient):
    response = client.post("/chat", json={"message": "", "user_id": "test_user"})
    assert response.status_code == 400
    assert "Empty message" in response.json()["detail"]


def test_chat_endpoint_success_mocked(client: TestClient):
    from langchain_core.messages import AIMessage

    mock_result = {"messages": [AIMessage(content="¡Hola! Soy tu entrenador. Todo listo para empezar.")]}
    with patch("main.graph.ainvoke", return_value=mock_result):
        response = client.post("/chat", json={"message": "Hola coach", "user_id": "test_athlete_chat"})
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "test_athlete_chat"
        assert "¡Hola! Soy tu entrenador" in data["response"]
        assert "¡Hola! Soy tu entrenador" in data["message"]


def test_setup_system_save(client: TestClient):
    payload = {
        "storage_mode": "local",
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "llm_base_url": "https://api.openai.com/v1",
        "llm_api_key": "secret-test-key",
        "embeddings_provider": "ollama",
        "embedding_base_url": "http://192.168.89.32:11434/v1",
        "embedding_model": "nomic-embed-text",
    }
    response = client.post("/setup/system/save", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["storage_mode"] == "local"
    assert data["llm_provider"] == "openai"
    assert data["llm_model"] == "gpt-4o-mini"
    assert data["embeddings_provider"] == "ollama"

    # Verify GET /setup/system returns active config
    res_get = client.get("/setup/system")
    assert res_get.status_code == 200
    get_data = res_get.json()
    assert get_data["llm_provider"] == "openai"
    assert get_data["llm_model"] == "gpt-4o-mini"
    assert get_data["embeddings_provider"] == "ollama"
    assert get_data["embedding_base_url"] == "http://192.168.89.32:11434/v1"


def test_setup_api_key_generation(client: TestClient):
    payload = {"user_id": "athlete_mcp_test", "name": "antigravity_agent"}
    response = client.post("/setup/api-key", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "athlete_mcp_test"
    assert data["api_key"].startswith("bio_")
    assert "X-API-Key" in data["mcp_config"]["mcpServers"]["biometric-ai"]["headers"]
    assert data["mcp_url"] == "/mcp/sse"
    assert data["mcp_config"]["mcpServers"]["biometric-ai"]["url"] == "http://localhost:8002/mcp/sse"


def test_delete_athlete_cascade(client: TestClient):
    user_id = "athlete_to_delete_test"
    # 1. Seed data
    setup_payload = {
        "storage_mode": "local",
        "user_id": user_id,
        "watch_provider": "garmin",
        "use_mock_data": True,
        "generate_key": True,
    }
    res_setup = client.post("/setup/save", json=setup_payload)
    assert res_setup.status_code == 200

    # Verify user exists
    res_users = client.get("/dashboard/users")
    assert user_id in res_users.json()["users"]

    # 2. Delete athlete via POST /athletes/delete
    res_del = client.post("/athletes/delete", json={"user_id": user_id})
    assert res_del.status_code == 200
    del_data = res_del.json()
    assert del_data["status"] == "success"
    assert del_data["user_id"] == user_id

    # Verify user is gone from list
    res_users_after = client.get("/dashboard/users")
    assert user_id not in res_users_after.json()["users"]


def test_athlete_status_endpoint(client: TestClient):
    response = client.get("/athletes/athlete_1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "athlete_1"
    assert "garmin_connected" in data
    assert "fitbit_connected" in data
    assert "google_health_connected" in data
    assert "google_client_id" in data
    assert "fitbit_client_id" in data


def test_athlete_dashboard_layout_persistence(client: TestClient):
    """Tests retrieving and persisting per-athlete custom dashboard layouts."""
    user_id = "test_custom_layout_user"
    # 1. Default layout
    res_get = client.get(f"/athletes/{user_id}/dashboard-layout")
    assert res_get.status_code == 200
    data = res_get.json()
    assert data["user_id"] == user_id
    assert "widget-kpis" in data["layout"]["order"]

    # 2. Save custom layout
    custom_order = ["widget-chart", "widget-kpis", "widget-zones", "widget-goals", "widget-activities", "widget-coach"]
    custom_visible = {
        "widget-kpis": True,
        "widget-chart": True,
        "widget-zones": True,
        "widget-goals": True,
        "widget-activities": True,
        "widget-coach": False,
    }
    res_post = client.post(
        f"/athletes/{user_id}/dashboard-layout",
        json={"order": custom_order, "visible": custom_visible},
    )
    assert res_post.status_code == 200
    post_data = res_post.json()
    assert post_data["status"] == "ok"
    assert post_data["layout"]["order"] == custom_order
    assert post_data["layout"]["visible"]["widget-coach"] is False

    # 3. Retrieve and verify persisted custom layout
    res_get_updated = client.get(f"/athletes/{user_id}/dashboard-layout")
    assert res_get_updated.status_code == 200
    updated_data = res_get_updated.json()
    assert updated_data["layout"]["order"][0] == "widget-chart"
    assert updated_data["layout"]["visible"]["widget-coach"] is False
