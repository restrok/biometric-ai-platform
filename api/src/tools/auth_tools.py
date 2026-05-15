import json
import logging
import re

from garmin_training_toolkit_sdk.auth import (
    exchange_oauth2,
    get_oauth1_token,
    get_oauth_consumer,
)
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import set_secret

log = logging.getLogger(__name__)

# The official SSO Embed URL for Garmin Connect
GARMIN_SSO_URL = (
    "https://sso.garmin.com/sso/embed"
    "?id=gauth-widget"
    "&embedWidget=true"
    "&gauthHost=https://sso.garmin.com/sso"
    "&clientId=GarminConnect"
    "&locale=en_US"
    "&redirectAfterAccountLoginUrl=https://sso.garmin.com/sso/embed"
    "&service=https://sso.garmin.com/sso/embed"
)


class AuthUrlInput(BaseModel):
    """Input for getting the auth URL."""

    user_id: str = Field(..., description="The ID of the user.")


@tool(args_schema=AuthUrlInput)
def get_garmin_auth_url(user_id: str) -> str:
    """
    Returns the secure Garmin SSO login URL. MANDATORY for any Garmin connection or login request.
    There is NO 'Connect Button' in the UI; you MUST use this tool to provide the link.
    The user must open this link in their browser, log in, and then
    provide the 'ticket' or full URL from the resulting page to complete the connection.
    """
    return (
        f"To connect your account for user '{user_id}', please open this link in your browser:\n\n"
        f"{GARMIN_SSO_URL}\n\n"
        "After logging in, you will be redirected to a page that might look empty. "
        "COPY the full URL from your browser's address bar (it should contain 'ticket=ST-...') "
        "and paste it here."
    )


class CompleteAuthInput(BaseModel):
    """Input for completing the auth flow."""

    ticket_or_url: str = Field(
        ...,
        description="The full redirect URL or the ticket (ST-...) provided by Garmin after login.",
    )
    user_id: str = Field(..., description="The ID of the user.")


@tool(args_schema=CompleteAuthInput)
def complete_garmin_auth(ticket_or_url: str, user_id: str) -> str:
    """
    Completes the Garmin authentication process by exchanging an SSO ticket for OAuth tokens.
    Saves the tokens securely in Google Secret Manager for the specific user.
    """
    # 1. Robust Ticket Extraction
    # We look for the pattern ST- followed by alphanumeric and dashes
    ticket_match = re.search(r"(ST-[A-Za-z0-9\-]+)", ticket_or_url)
    
    if not ticket_match:
        return "❌ Could not find a valid ticket (ST-...) in your message. Please make sure to copy the full URL or the service ticket."

    ticket = ticket_match.group(1)
    log.info(f"🎫 Extracted ticket: {ticket[:10]}... for user: {user_id}")

    try:
        log.info(f"🔄 Exchanging ticket for tokens for user: {user_id}")

        # 2. Fetch Consumer Credentials (Shared)
        consumer = get_oauth_consumer()

        # 3. Exchange Ticket -> OAuth1
        oauth1 = get_oauth1_token(ticket, consumer)

        # 4. Exchange OAuth1 -> OAuth2
        oauth2 = exchange_oauth2(oauth1, consumer)

        # 5. Persist to Secret Manager
        secret_name = f"garmin-tokens-{user_id}"
        if set_secret(secret_name, json.dumps(oauth2)):
            log.info(f"✅ Connection successful for {user_id}. Tokens saved to Secret Manager.")
            return (
                f"✅ **Connection successful!**\n\n"
                f"Your Garmin account is now linked to user ID '{user_id}'. "
                "I am now ready to analyze your activities and health metrics."
            )
        return "❌ Authentication succeeded, but I failed to save the tokens to Secret Manager. Please check logs."

    except Exception as e:
        log.error(f"❌ Auth exchange failed: {e}")
        return f"❌ Failed to connect your account: {str(e)}"
