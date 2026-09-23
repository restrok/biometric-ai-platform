#!/usr/bin/env python3
"""CLI Script to authenticate Google Calendar & Gmail (Read-Only) via OAuth 2.0 PKCE.

Reuses existing Web application OAuth credentials from the environment (.env):
- GOOGLE_HEALTH_CLIENT_ID
- GOOGLE_HEALTH_CLIENT_SECRET
- Redirect URI: http://localhost:8002/auth/google/callback

Flow:
1. Generates PKCE authorization URL with requested readonly scope(s).
2. Prints instructions for the user to authorize via their browser.
3. Receives authorization code (or full callback URL) from user.
4. Exchanges code for tokens.
5. Saves tokens encrypted with Fernet AES in LocalSecureVault, separated by purpose:
   - google_calendar_tokens_<user_id>.enc
   - google_gmail_tokens_<user_id>.enc
   (and synchronizes to homelab dev container vault if available).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.parse
from pathlib import Path

# Add api/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.google_workspace.oauth import (
    CALENDAR_READONLY_SCOPE,
    DEFAULT_REDIRECT_URI,
    GMAIL_READONLY_SCOPE,
    GoogleOAuthClient,
    save_tokens_to_vault,
)
from src.utils.config import setup_environment
from src.utils.vault import LocalSecureVault


def init_env() -> None:
    """Load environment variables for CLI execution."""
    setup_environment()
    dev_env = Path("/home/fsirio/homelab/biometric-coach-dev/.env")
    if dev_env.exists():
        from dotenv import load_dotenv

        load_dotenv(dev_env)


def get_default_client_id() -> str:
    return (
        os.getenv("GOOGLE_HEALTH_CLIENT_ID")
        or os.getenv("GOOGLE_CLIENT_ID")
        or os.getenv("GOOGLE_WORKSPACE_CLIENT_ID")
        or ""
    )


def get_default_client_secret() -> str:
    return (
        os.getenv("GOOGLE_HEALTH_CLIENT_SECRET")
        or os.getenv("GOOGLE_CLIENT_SECRET")
        or os.getenv("GOOGLE_WORKSPACE_CLIENT_SECRET")
        or ""
    )


def parse_code_from_input(raw_input: str) -> str:
    """Extracts authorization code from either a raw code string or a full redirect URL."""
    raw_input = raw_input.strip()
    if "code=" in raw_input:
        match = re.search(r"code=([^&]+)", raw_input)
        if match:
            return urllib.parse.unquote(match.group(1))
    return urllib.parse.unquote(raw_input)


def main():
    init_env()
    parser = argparse.ArgumentParser(
        description="Authorize Google Calendar & Gmail in Read-Only mode and store encrypted tokens."
    )
    parser.add_argument(
        "--service",
        choices=["calendar", "gmail", "both"],
        default="both",
        help="Google service to authorize: 'calendar', 'gmail', or 'both' (default: both)",
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("GOOGLE_USER_ID", "fedeale.sirio@gmail.com"),
        help="Target user or athlete ID (default: fedeale.sirio@gmail.com)",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Google OAuth Client ID (defaults to GOOGLE_HEALTH_CLIENT_ID from environment)",
    )
    parser.add_argument(
        "--client-secret",
        default=None,
        help="Google OAuth Client Secret (defaults to GOOGLE_HEALTH_CLIENT_SECRET from environment)",
    )
    parser.add_argument(
        "--redirect-uri",
        default=DEFAULT_REDIRECT_URI,
        help=f"Redirect URI registered in Google Cloud Console (default: {DEFAULT_REDIRECT_URI})",
    )
    parser.add_argument(
        "--url-only",
        action="store_true",
        help="Print authorization URL and exit without waiting for code",
    )
    parser.add_argument(
        "--code",
        default=None,
        help="Authorization code or full callback URL to exchange directly without waiting for input",
    )
    parser.add_argument(
        "--vault-dir",
        default=os.getenv("VAULT_DIR") or os.getenv("BIOMETRIC_DATA_DIR"),
        help="Custom vault or data directory path (defaults to host homelab dev vault or local vault)",
    )
    args = parser.parse_args()

    client_id = args.client_id or get_default_client_id()
    client_secret = args.client_secret or get_default_client_secret()

    if not client_id and not args.url_only:
        client_id = input("Enter Google OAuth Client ID: ").strip()
    if not client_secret and not args.url_only:
        client_secret = input("Enter Google OAuth Client Secret: ").strip()

    if not client_id:
        print("❌ Error: Client ID is required.")
        sys.exit(1)
    if not client_secret and not args.url_only:
        print("❌ Error: Both Client ID and Client Secret are required.")
        sys.exit(1)

    # Resolve scopes based on selected service
    scopes = []
    if args.service in ("calendar", "both"):
        scopes.append(CALENDAR_READONLY_SCOPE)
    if args.service in ("gmail", "both"):
        scopes.append(GMAIL_READONLY_SCOPE)

    masked_id = f"{client_id[:12]}...{client_id[-12:]}" if len(client_id) > 24 else client_id

    print("\n" + "=" * 70)
    print("🔒 GOOGLE CALENDAR & GMAIL READONLY INTEGRATION (CLI)")
    print("=" * 70)
    print(f"• Service:       {args.service.upper()} (READONLY)")
    print(f"• Target User:   {args.user_id}")
    print(f"• Client ID:     {masked_id}")
    print(f"• Redirect URI:  {args.redirect_uri}")
    print(f"• Scopes:        {', '.join(scopes)}")
    print("-" * 70)

    # Handle --url-only mode (non-blocking for mobile/remote manual flow)
    if args.url_only:
        params = {
            "client_id": client_id,
            "redirect_uri": args.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
        }
        direct_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
        print("\nURL de autorización (abrir en navegador móvil/escritorio):\n")
        print(direct_url)
        print("\n" + "-" * 70)
        print("INSTRUCCIONES:")
        print("1. Abrí la URL en el navegador de tu celular.")
        print("2. Aceptá el consentimiento con tu cuenta de Google.")
        print(f"3. El celular intentará redirigir a {args.redirect_uri}?code=... (la página no cargará).")
        print("4. Copiá la URL completa de la barra de direcciones del navegador del celular.")
        print("5. Canjeá el código ejecutando:")
        print('   python scripts/auth_google_calendar_gmail_cli.py --code "<URL_O_CODIGO>"\n')
        return

    oauth_client = GoogleOAuthClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=args.redirect_uri,
        scopes=scopes,
    )

    verifier = None
    if args.code:
        code = parse_code_from_input(args.code)
    else:
        auth_url, verifier, state = oauth_client.get_authorization_url()

        print("\nPASO 1: Abrí la siguiente URL de autorización en tu navegador:\n")
        print(auth_url)
        print("\n" + "-" * 70)
        print("PASO 2: Iniciá sesión con tu cuenta de Google y aceptá los permisos requeridos.")
        print("Al finalizar el consentimiento, el navegador redirigirá a:")
        print(f"  {args.redirect_uri}?code=4/0A...&state={state}")
        print("-" * 70)
        print("PASO 3: Copiá la URL completa de la barra de direcciones (o únicamente el código '4/0A...'):")

        user_input = input("\nPegá la URL o el código aquí: ").strip()
        if not user_input:
            print("❌ Operación cancelada: no se ingresó el código de autorización.")
            sys.exit(1)

        code = parse_code_from_input(user_input)

    print("\n🔄 Canjeando código de autorización por tokens con Google...")
    try:
        token_data = oauth_client.exchange_code_for_tokens(code=code, code_verifier=verifier)
        print("✅ ¡Tokens obtenidos exitosamente desde Google OAuth!")

        # Enforce least privilege token separation
        local_vault = LocalSecureVault(vault_dir=args.vault_dir)
        saved_files = []

        if args.service in ("calendar", "both"):
            cal_tokens = {**token_data, "service": "calendar", "scope": CALENDAR_READONLY_SCOPE}
            p = save_tokens_to_vault("google_calendar", args.user_id, cal_tokens, vault=local_vault)
            saved_files.append(p.name)

        if args.service in ("gmail", "both"):
            gmail_tokens = {**token_data, "service": "gmail", "scope": GMAIL_READONLY_SCOPE}
            p = save_tokens_to_vault("google_gmail", args.user_id, gmail_tokens, vault=local_vault)
            saved_files.append(p.name)

        print("\n" + "=" * 70)
        print("🔐 ALMACENAMIENTO SEGURO COMPLETADO")
        print("=" * 70)
        for f in saved_files:
            print(f"  ✓ Archivo cifrado con Fernet: {f}")
        print(f"  ✓ Ubicación principal: {local_vault.vault_dir}")

        homelab_dev_vault = Path("/home/fsirio/homelab/biometric-coach-dev/data/vault")
        if homelab_dev_vault.exists() and local_vault.vault_dir.resolve() != homelab_dev_vault.resolve():
            print(f"  ✓ Sincronizado en contenedor dev: {homelab_dev_vault}")

        homelab_prod_vault = Path("/home/fsirio/homelab/biometric-coach/data/vault")
        if homelab_prod_vault.exists() and local_vault.vault_dir.resolve() != homelab_prod_vault.resolve():
            print(f"  ✓ Sincronizado en contenedor prod: {homelab_prod_vault}")

        print("=" * 70)
        print("🎉 Integración configurada correctamente con permisos de solo lectura.\n")

    except Exception as e:
        print(f"\n❌ Error durante el canje de tokens: {e}")
        print("Sugerencias:")
        print("1. Verificá que las APIs de Calendar y Gmail estén habilitadas en el proyecto GCP.")
        print("2. Verificá que la cuenta de usuario esté añadida en la lista de Test Users en el Consent Screen.")
        print("3. Recordá que el código de autorización solo puede usarse una única vez y expira rápidamente.")
        sys.exit(1)


if __name__ == "__main__":
    main()
