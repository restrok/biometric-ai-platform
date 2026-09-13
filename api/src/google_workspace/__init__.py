"""Google Workspace Read-Only Integration Module.

Provides OAuth 2.0 PKCE authentication and read-only clients for:
- Google Calendar (events, calendar list)
- Gmail (messages, threads)

Tokens are encrypted with Fernet AES via LocalSecureVault.
"""

from src.google_workspace.calendar import GoogleCalendarClient
from src.google_workspace.gmail import GoogleGmailClient
from src.google_workspace.oauth import (
    CALENDAR_READONLY_SCOPE,
    DEFAULT_REDIRECT_URI,
    GMAIL_READONLY_SCOPE,
    GoogleOAuthClient,
    get_valid_access_token,
    load_tokens_from_vault,
    save_tokens_to_vault,
)

__all__ = [
    "CALENDAR_READONLY_SCOPE",
    "DEFAULT_REDIRECT_URI",
    "GMAIL_READONLY_SCOPE",
    "GoogleCalendarClient",
    "GoogleGmailClient",
    "GoogleOAuthClient",
    "get_valid_access_token",
    "load_tokens_from_vault",
    "save_tokens_to_vault",
]
