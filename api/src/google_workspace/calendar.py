"""Google Calendar Read-Only Client.

Provides structured read access to Google Calendar events within date ranges.
Uses encrypted tokens stored in LocalSecureVault under provider 'google_calendar'.
Enforces read-only scope: https://www.googleapis.com/auth/calendar.readonly.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

from src.google_workspace.oauth import (
    CALENDAR_READONLY_SCOPE,
    GoogleOAuthClient,
    get_valid_access_token,
)
from src.utils.vault import LocalSecureVault

log = logging.getLogger(__name__)

CALENDAR_API_BASE_URL = "https://www.googleapis.com/calendar/v3"


def _format_rfc3339(dt: datetime | date | str | None) -> str | None:
    """Formats a datetime or date object/string into RFC3339 string format."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # Assume UTC if naive
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()
    if isinstance(dt, date):
        # Beginning of day UTC
        return datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=UTC).isoformat()
    if isinstance(dt, str):
        # Validate or pass through string
        return dt
    return str(dt)


def _parse_event_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Extracts a clean, normalized dictionary representation of a Calendar event."""
    start_info = item.get("start", {})
    end_info = item.get("end", {})

    start_val = start_info.get("dateTime") or start_info.get("date")
    end_val = end_info.get("dateTime") or end_info.get("date")
    is_all_day = "date" in start_info and "dateTime" not in start_info

    attendees = [
        {
            "email": a.get("email"),
            "display_name": a.get("displayName"),
            "response_status": a.get("responseStatus"),
            "self": a.get("self", False),
        }
        for a in item.get("attendees", [])
    ]

    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "summary": item.get("summary", "(No title)"),
        "description": item.get("description", ""),
        "start": start_val,
        "end": end_val,
        "is_all_day": is_all_day,
        "time_zone": start_info.get("timeZone"),
        "location": item.get("location"),
        "html_link": item.get("htmlLink"),
        "organizer": item.get("organizer", {}).get("email"),
        "attendees": attendees,
        "created": item.get("created"),
        "updated": item.get("updated"),
    }


class GoogleCalendarClient:
    """Read-only client for Google Calendar API."""

    def __init__(
        self,
        user_id: str,
        vault: LocalSecureVault | None = None,
        oauth_client: GoogleOAuthClient | None = None,
        access_token: str | None = None,
    ):
        self.user_id = user_id
        self.vault = vault
        self.oauth_client = oauth_client or GoogleOAuthClient(scopes=[CALENDAR_READONLY_SCOPE])
        self._explicit_access_token = access_token

    def _get_access_token(self) -> str:
        """Resolves a valid access token for the client."""
        if self._explicit_access_token:
            return self._explicit_access_token
        return get_valid_access_token(
            provider="google_calendar",
            user_id=self.user_id,
            vault=self.vault,
            oauth_client=self.oauth_client,
        )

    def list_events(
        self,
        calendar_id: str = "primary",
        time_min: datetime | date | str | None = None,
        time_max: datetime | date | str | None = None,
        max_results: int = 100,
        single_events: bool = True,
        order_by: str = "startTime",
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lists events from the specified calendar within a date/time range.

        Args:
            calendar_id: The identifier of the calendar (default: 'primary').
            time_min: Lower bound for an event's end time (RFC3339 format or datetime).
            time_max: Upper bound for an event's start time (RFC3339 format or datetime).
            max_results: Maximum number of events to return (default 100).
            single_events: Whether to expand recurring events into individual instances.
            order_by: Order of the events. Allowed: 'startTime' or 'updated'.
            query: Free text search terms to filter events.

        Returns:
            List of normalized event dictionaries.
        """
        token = self._get_access_token()
        url = f"{CALENDAR_API_BASE_URL}/calendars/{calendar_id}/events"

        params: dict[str, Any] = {
            "maxResults": min(max_results, 250),
            "singleEvents": str(single_events).lower(),
        }
        if single_events and order_by:
            params["orderBy"] = order_by

        formatted_min = _format_rfc3339(time_min)
        if formatted_min:
            params["timeMin"] = formatted_min

        formatted_max = _format_rfc3339(time_max)
        if formatted_max:
            params["timeMax"] = formatted_max

        if query:
            params["q"] = query

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code == 401 and not self._explicit_access_token:
                # Token might have expired during runtime; retry once with forced refresh
                log.info(f"Received 401 for user '{self.user_id}'. Forcing token refresh...")
                tokens = self.oauth_client.refresh_access_token(
                    self.oauth_client.load_tokens_from_vault("google_calendar", self.user_id)["refresh_token"]
                    if hasattr(self.oauth_client, "load_tokens_from_vault")
                    else ""
                )
                headers["Authorization"] = f"Bearer {tokens.get('access_token')}"
                resp = client.get(url, params=params, headers=headers)

            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        return [_parse_event_payload(item) for item in items]

    def get_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Retrieves details of a specific event by ID.

        Args:
            event_id: The Google Calendar event ID.
            calendar_id: The calendar ID (default: 'primary').
        """
        token = self._get_access_token()
        url = f"{CALENDAR_API_BASE_URL}/calendars/{calendar_id}/events/{event_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return _parse_event_payload(resp.json())

    def list_calendars(self) -> list[dict[str, Any]]:
        """Retrieves the list of calendars accessible by the user."""
        token = self._get_access_token()
        url = f"{CALENDAR_API_BASE_URL}/users/me/calendarList"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return [
            {
                "id": c.get("id"),
                "summary": c.get("summary"),
                "description": c.get("description", ""),
                "primary": c.get("primary", False),
                "time_zone": c.get("timeZone"),
                "access_role": c.get("accessRole"),
            }
            for c in data.get("items", [])
        ]
