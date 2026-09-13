"""Unit tests for Google Calendar & Gmail Read-Only Integration with Mocks.

Verifies:
1. OAuth 2.0 PKCE flow & credentials handling.
2. Local vault Fernet encryption with least-privilege token separation.
3. Google Calendar API client (list events, get event, list calendars, time formatting).
4. Google Gmail API client (list messages, get message, payload decoding).
5. Automatic token refresh when expired.
6. CLI input parser utilities.
"""

from __future__ import annotations

import base64
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.auth_google_calendar_gmail_cli import parse_code_from_input
from src.google_workspace.calendar import GoogleCalendarClient, _format_rfc3339
from src.google_workspace.gmail import (
    GoogleGmailClient,
    _decode_base64_url_safe,
)
from src.google_workspace.oauth import (
    CALENDAR_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GoogleOAuthClient,
    generate_code_challenge,
    generate_code_verifier,
    get_valid_access_token,
    load_tokens_from_vault,
    save_tokens_to_vault,
)
from src.utils.vault import LocalSecureVault


@pytest.fixture
def temp_vault(tmp_path):
    """Creates an isolated LocalSecureVault in a temporary directory."""
    return LocalSecureVault(vault_dir=tmp_path / "vault")


@pytest.fixture
def mock_oauth_client():
    """Provides a GoogleOAuthClient instance configured with test credentials."""
    return GoogleOAuthClient(
        client_id="test-client-id-123.apps.googleusercontent.com",
        client_secret="test-client-secret-xyz",
        redirect_uri="http://localhost:8002/auth/google/callback",
        scopes=[CALENDAR_READONLY_SCOPE, GMAIL_READONLY_SCOPE],
    )


# ==============================================================================
# OAuth Client & PKCE Tests
# ==============================================================================


def test_pkce_generation():
    verifier = generate_code_verifier(64)
    assert len(verifier) == 64
    challenge = generate_code_challenge(verifier)
    assert len(challenge) > 20
    # Deterministic challenge for same verifier
    assert generate_code_challenge(verifier) == challenge


def test_oauth_client_requires_credentials():
    with patch.dict("os.environ", {}, clear=True):
        client = GoogleOAuthClient(client_id="", client_secret="")
        with pytest.raises(ValueError, match="client_id is missing"):
            client.get_authorization_url()


def test_oauth_client_authorization_url(mock_oauth_client):
    url, verifier, state = mock_oauth_client.get_authorization_url(state="custom-state")
    assert "https://accounts.google.com/o/oauth2/v2/auth?" in url
    assert "client_id=test-client-id-123.apps.googleusercontent.com" in url
    assert "response_type=code" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=custom-state" in url
    assert len(verifier) >= 43


def test_oauth_exchange_code_success(mock_oauth_client):
    fake_tokens = {
        "access_token": "ya29.fake-access-token",
        "refresh_token": "1//fake-refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": f"{CALENDAR_READONLY_SCOPE} {GMAIL_READONLY_SCOPE}",
    }

    def mock_post(url, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        data = kwargs.get("data", {})
        assert data.get("grant_type") == "authorization_code"
        assert data.get("code") == "test-auth-code"
        assert data.get("client_id") == "test-client-id-123.apps.googleusercontent.com"
        assert data.get("client_secret") == "test-client-secret-xyz"

        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_tokens
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    with patch("httpx.Client.post", side_effect=mock_post):
        result = mock_oauth_client.exchange_code_for_tokens("test-auth-code", code_verifier="test-verifier")
        assert result["access_token"] == "ya29.fake-access-token"
        assert result["refresh_token"] == "1//fake-refresh-token"
        assert "created_at" in result


def test_oauth_refresh_token(mock_oauth_client):
    fake_refresh_response = {
        "access_token": "ya29.new-refreshed-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }

    def mock_post(url, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        data = kwargs.get("data", {})
        assert data.get("grant_type") == "refresh_token"
        assert data.get("refresh_token") == "1//existing-refresh-token"

        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_refresh_response
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    with patch("httpx.Client.post", side_effect=mock_post):
        refreshed = mock_oauth_client.refresh_access_token("1//existing-refresh-token")
        assert refreshed["access_token"] == "ya29.new-refreshed-token"
        assert refreshed["refresh_token"] == "1//existing-refresh-token"


# ==============================================================================
# Fernet Vault Encryption & Separation Tests (Least Privilege)
# ==============================================================================


def test_vault_encrypted_storage_and_separation(temp_vault):
    user_id = "test_athlete@example.com"
    cal_tokens = {"access_token": "cal-access", "refresh_token": "cal-refresh", "expires_in": 3600}
    gmail_tokens = {"access_token": "gmail-access", "refresh_token": "gmail-refresh", "expires_in": 3600}

    # Store separately
    cal_path = save_tokens_to_vault("google_calendar", user_id, cal_tokens, vault=temp_vault, sync_homelab_dev=False)
    gmail_path = save_tokens_to_vault("google_gmail", user_id, gmail_tokens, vault=temp_vault, sync_homelab_dev=False)

    assert cal_path.name == f"google_calendar_tokens_{user_id}.enc"
    assert gmail_path.name == f"google_gmail_tokens_{user_id}.enc"
    assert cal_path.exists()
    assert gmail_path.exists()

    # Verify files on disk are ciphertext, NOT plaintext
    raw_content = cal_path.read_bytes()
    assert b"cal-access" not in raw_content
    assert b"cal-refresh" not in raw_content

    # Retrieve and verify decryption
    retrieved_cal = load_tokens_from_vault("google_calendar", user_id, vault=temp_vault)
    retrieved_gmail = load_tokens_from_vault("google_gmail", user_id, vault=temp_vault)

    assert retrieved_cal["access_token"] == "cal-access"
    assert retrieved_gmail["access_token"] == "gmail-access"


def test_get_valid_access_token_auto_refresh(temp_vault, mock_oauth_client):
    user_id = "athlete_auto_refresh"
    # Token expired 100 seconds ago
    expired_tokens = {
        "access_token": "old-expired-token",
        "refresh_token": "valid-refresh-token",
        "expires_in": 3600,
        "created_at": time.time() - 4000,
    }
    save_tokens_to_vault("google_calendar", user_id, expired_tokens, vault=temp_vault, sync_homelab_dev=False)

    with patch.object(
        mock_oauth_client,
        "refresh_access_token",
        return_value={"access_token": "fresh-refreshed-token", "expires_in": 3600, "created_at": time.time()},
    ) as mock_refresh:
        token = get_valid_access_token(
            provider="google_calendar",
            user_id=user_id,
            vault=temp_vault,
            oauth_client=mock_oauth_client,
        )
        assert token == "fresh-refreshed-token"
        assert mock_refresh.called


# ==============================================================================
# Google Calendar Client Tests
# ==============================================================================


def test_rfc3339_formatting():
    dt = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)
    assert _format_rfc3339(dt) == "2026-09-13T10:00:00+00:00"
    assert _format_rfc3339("2026-09-13T10:00:00Z") == "2026-09-13T10:00:00Z"
    assert _format_rfc3339(None) is None


def test_calendar_list_events(mock_oauth_client):
    user_id = "test_user"
    client = GoogleCalendarClient(
        user_id=user_id,
        oauth_client=mock_oauth_client,
        access_token="test-access-token",
    )

    mock_api_response = {
        "items": [
            {
                "id": "evt_123",
                "status": "confirmed",
                "summary": "Morning Interval Run",
                "description": "5x1000m VO2 max intervals",
                "start": {"dateTime": "2026-09-13T08:00:00Z"},
                "end": {"dateTime": "2026-09-13T09:00:00Z"},
                "location": "Running Track",
                "htmlLink": "https://calendar.google.com/event?eid=evt_123",
                "attendees": [{"email": "coach@example.com", "displayName": "Coach", "responseStatus": "accepted"}],
            },
            {
                "id": "evt_456",
                "status": "confirmed",
                "summary": "Rest Day",
                "start": {"date": "2026-09-14"},
                "end": {"date": "2026-09-15"},
            },
        ]
    }

    def mock_get(url, **kwargs):
        assert "calendars/primary/events" in url
        params = kwargs.get("params", {})
        assert params.get("timeMin") == "2026-09-13T00:00:00Z"
        assert params.get("timeMax") == "2026-09-14T00:00:00Z"
        assert kwargs["headers"]["Authorization"] == "Bearer test-access-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_api_response
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    with patch("httpx.Client.get", side_effect=mock_get):
        events = client.list_events(
            time_min="2026-09-13T00:00:00Z",
            time_max="2026-09-14T00:00:00Z",
        )

        assert len(events) == 2
        ev1 = events[0]
        assert ev1["id"] == "evt_123"
        assert ev1["summary"] == "Morning Interval Run"
        assert ev1["is_all_day"] is False
        assert ev1["location"] == "Running Track"
        assert len(ev1["attendees"]) == 1

        ev2 = events[1]
        assert ev2["id"] == "evt_456"
        assert ev2["summary"] == "Rest Day"
        assert ev2["is_all_day"] is True


def test_calendar_get_event(mock_oauth_client):
    client = GoogleCalendarClient(
        user_id="test_user",
        oauth_client=mock_oauth_client,
        access_token="test-access-token",
    )

    mock_event = {
        "id": "evt_single",
        "summary": "Physiotherapy Session",
        "start": {"dateTime": "2026-09-15T15:00:00Z"},
        "end": {"dateTime": "2026-09-15T16:00:00Z"},
    }

    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_event
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        event = client.get_event("evt_single")
        assert event["id"] == "evt_single"
        assert event["summary"] == "Physiotherapy Session"


# ==============================================================================
# Google Gmail Client Tests
# ==============================================================================


def test_gmail_base64_url_decoding():
    raw_text = "Hello! Your weekly training plan is ready."
    # Standard base64url encode without padding
    encoded = base64.urlsafe_b64encode(raw_text.encode("utf-8")).decode("ascii").rstrip("=")
    decoded = _decode_base64_url_safe(encoded)
    assert decoded == raw_text


def test_gmail_list_messages(mock_oauth_client):
    client = GoogleGmailClient(
        user_id="test_user",
        oauth_client=mock_oauth_client,
        access_token="gmail-test-token",
    )

    mock_resp_data = {
        "messages": [
            {"id": "msg_001", "threadId": "th_001"},
            {"id": "msg_002", "threadId": "th_002"},
        ],
        "nextPageToken": "token_page_2",
        "resultSizeEstimate": 2,
    }

    def mock_get(url, **kwargs):
        assert "users/me/messages" in url
        params = kwargs.get("params", {})
        assert params.get("q") == "label:INBOX"
        assert kwargs["headers"]["Authorization"] == "Bearer gmail-test-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_resp_data
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    with patch("httpx.Client.get", side_effect=mock_get):
        result = client.list_messages(query="label:INBOX")
        assert len(result["messages"]) == 2
        assert result["next_page_token"] == "token_page_2"


def test_gmail_get_message(mock_oauth_client):
    client = GoogleGmailClient(
        user_id="test_user",
        oauth_client=mock_oauth_client,
        access_token="gmail-test-token",
    )

    body_text = "Good morning Federico, your readiness score is 88."
    b64_body = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("ascii")

    mock_msg_data = {
        "id": "msg_readiness",
        "threadId": "th_readiness",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Good morning Federico...",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Morning Biometric Readiness"},
                {"name": "From", "value": "coach@biometric.local"},
                {"name": "To", "value": "fedeale.sirio@gmail.com"},
                {"name": "Date", "value": "Sun, 13 Sep 2026 07:00:00 +0000"},
            ],
            "body": {
                "size": len(body_text),
                "data": b64_body,
            },
        },
    }

    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_msg_data
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        parsed = client.get_message("msg_readiness")
        assert parsed["id"] == "msg_readiness"
        assert parsed["subject"] == "Morning Biometric Readiness"
        assert parsed["from"] == "coach@biometric.local"
        assert parsed["to"] == "fedeale.sirio@gmail.com"
        assert parsed["body"] == body_text
        assert "INBOX" in parsed["label_ids"]


def test_gmail_list_and_read_messages(mock_oauth_client):
    client = GoogleGmailClient(
        user_id="test_user",
        oauth_client=mock_oauth_client,
        access_token="gmail-test-token",
    )

    with (
        patch.object(client, "list_messages", return_value={"messages": [{"id": "m1"}, {"id": "m2"}]}),
        patch.object(
            client,
            "get_message",
            side_effect=[
                {"id": "m1", "subject": "Workout 1", "body": "Leg day"},
                {"id": "m2", "subject": "Workout 2", "body": "Swim session"},
            ],
        ),
    ):
        messages = client.list_and_read_messages(query="is:unread", max_results=5)
        assert len(messages) == 2
        assert messages[0]["subject"] == "Workout 1"
        assert messages[1]["subject"] == "Workout 2"


# ==============================================================================
# CLI Utility Tests
# ==============================================================================


def test_cli_parse_code_from_input():
    # Raw code input
    assert parse_code_from_input("4/0AY0e-g4") == "4/0AY0e-g4"

    # Full callback URL
    url = "http://localhost:8002/auth/google/callback?code=4%2F0AY0e-g4xyz&state=abc123"
    assert parse_code_from_input(url) == "4/0AY0e-g4xyz"

    # URL with whitespace
    url_spaces = "  http://localhost:8002/auth/google/callback?code=4/0A_test&scope=read  "
    assert parse_code_from_input(url_spaces) == "4/0A_test"
