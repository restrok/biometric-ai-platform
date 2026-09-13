"""Google Gmail Read-Only Client.

Provides structured read access to Gmail messages and threads.
Uses encrypted tokens stored in LocalSecureVault under provider 'google_gmail'.
Enforces read-only scope: https://www.googleapis.com/auth/gmail.readonly.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from src.google_workspace.oauth import (
    GMAIL_READONLY_SCOPE,
    GoogleOAuthClient,
    get_valid_access_token,
)
from src.utils.vault import LocalSecureVault

log = logging.getLogger(__name__)

GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"


def _decode_base64_url_safe(data_str: str) -> str:
    """Decodes standard base64url-encoded body text from Gmail API payloads."""
    if not data_str:
        return ""
    try:
        # Add padding if required
        padding = "=" * ((4 - len(data_str) % 4) % 4)
        padded_str = data_str.replace("-", "+").replace("_", "/") + padding
        decoded_bytes = base64.b64decode(padded_str)
        return decoded_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        log.debug(f"Error decoding base64 Gmail body part: {e}")
        return ""


def _extract_body_text(payload: dict[str, Any]) -> str:
    """Recursively traverses Gmail MIME payload parts to extract plain text body."""
    body_data = payload.get("body", {}).get("data")
    if body_data:
        mime_type = payload.get("mimeType", "")
        if mime_type.startswith("text/plain") or not payload.get("parts"):
            return _decode_base64_url_safe(body_data)

    # Check multipart parts
    parts = payload.get("parts", [])
    plain_text_parts = []
    html_parts = []

    for part in parts:
        mime = part.get("mimeType", "")
        part_data = part.get("body", {}).get("data")
        if part_data:
            decoded = _decode_base64_url_safe(part_data)
            if mime == "text/plain":
                plain_text_parts.append(decoded)
            elif mime == "text/html":
                html_parts.append(decoded)
        elif part.get("parts"):
            nested_text = _extract_body_text(part)
            if nested_text:
                plain_text_parts.append(nested_text)

    if plain_text_parts:
        return "\n".join(plain_text_parts)
    if html_parts:
        return "\n".join(html_parts)
    return ""


def _parse_message_payload(msg_json: dict[str, Any]) -> dict[str, Any]:
    """Extracts a clean, normalized dictionary representation of a Gmail message."""
    payload = msg_json.get("payload", {})
    headers_list = payload.get("headers", [])
    headers: dict[str, str] = {h.get("name", "").lower(): h.get("value", "") for h in headers_list}

    body_content = _extract_body_text(payload)

    return {
        "id": msg_json.get("id"),
        "thread_id": msg_json.get("threadId"),
        "label_ids": msg_json.get("labelIds", []),
        "snippet": msg_json.get("snippet", ""),
        "subject": headers.get("subject", "(No subject)"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "body": body_content,
        "internal_date": msg_json.get("internalDate"),
        "size_estimate": msg_json.get("sizeEstimate"),
    }


class GoogleGmailClient:
    """Read-only client for Gmail API."""

    def __init__(
        self,
        user_id: str,
        vault: LocalSecureVault | None = None,
        oauth_client: GoogleOAuthClient | None = None,
        access_token: str | None = None,
    ):
        self.user_id = user_id
        self.vault = vault
        self.oauth_client = oauth_client or GoogleOAuthClient(scopes=[GMAIL_READONLY_SCOPE])
        self._explicit_access_token = access_token

    def _get_access_token(self) -> str:
        """Resolves a valid access token for the client."""
        if self._explicit_access_token:
            return self._explicit_access_token
        return get_valid_access_token(
            provider="google_gmail",
            user_id=self.user_id,
            vault=self.vault,
            oauth_client=self.oauth_client,
        )

    def list_messages(
        self,
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_results: int = 20,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Lists message IDs matching search query or label criteria.

        Args:
            query: Gmail search query (e.g. 'is:unread', 'from:coach', 'after:2026/09/01').
            label_ids: List of label IDs to filter (e.g. ['INBOX', 'UNREAD']).
            max_results: Maximum messages to return (max 500, default 20).
            page_token: Page token for pagination.

        Returns:
            Dictionary containing 'messages' (list of {'id': ..., 'threadId': ...}) and optional 'next_page_token'.
        """
        token = self._get_access_token()
        url = f"{GMAIL_API_BASE_URL}/users/me/messages"

        params: dict[str, Any] = {
            "maxResults": min(max_results, 100),
        }
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return {
            "messages": data.get("messages", []),
            "next_page_token": data.get("nextPageToken"),
            "result_size_estimate": data.get("resultSizeEstimate", 0),
        }

    def get_message(
        self,
        message_id: str,
        format_type: str = "full",
    ) -> dict[str, Any]:
        """Retrieves and parses a specific email message by ID.

        Args:
            message_id: The ID of the Gmail message.
            format_type: Desired format: 'full', 'metadata', or 'minimal'.

        Returns:
            Normalized message dictionary including subject, from, to, date, snippet, and body.
        """
        token = self._get_access_token()
        url = f"{GMAIL_API_BASE_URL}/users/me/messages/{message_id}"
        params = {"format": format_type}
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return _parse_message_payload(resp.json())

    def list_and_read_messages(
        self,
        query: str | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Convenience function: lists messages matching query and fetches full content for each.

        Args:
            query: Gmail search query (e.g. 'is:unread', 'subject:workout').
            max_results: Max messages to retrieve and parse (default: 10).

        Returns:
            List of parsed message dictionaries.
        """
        listing = self.list_messages(query=query, max_results=max_results)
        raw_items = listing.get("messages", [])

        results = []
        for item in raw_items:
            mid = item.get("id")
            if mid:
                try:
                    msg = self.get_message(message_id=mid)
                    results.append(msg)
                except Exception as e:
                    log.warning(f"Could not fetch message {mid}: {e}")
        return results
