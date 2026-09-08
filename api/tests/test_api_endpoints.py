"""Tests for FastAPI endpoints: /health, /setup, /dashboard, and MCP server mount."""

import os

import pytest
from fastapi.testclient import TestClient

# Ensure local test environment
os.environ["STORAGE_MODE"] = "local"
os.environ["AUTH_DISABLED"] = "true"

from main import app


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
