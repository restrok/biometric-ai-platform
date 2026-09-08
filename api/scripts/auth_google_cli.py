#!/usr/bin/env python3
"""CLI script to authenticate with Google Health / Fitness API and obtain OAuth tokens.

Zero-redirect manual flow:
1. Generates the Google Auth URL.
2. You open it in your browser and authorize your account.
3. Copy the 'code' parameter from the resulting URL and paste it here.
4. Exchanges code for tokens and saves them encrypted into LocalSecureVault.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Add api/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fitbit_training_toolkit_sdk.auth.google_auth import GoogleHealthOAuthClient
from src.utils.vault import LocalSecureVault

DEFAULT_CLIENT_ID = os.getenv("GOOGLE_HEALTH_CLIENT_ID", "")
DEFAULT_CLIENT_SECRET = os.getenv("GOOGLE_HEALTH_CLIENT_SECRET", "")
DEFAULT_REDIRECT_URI = "http://localhost:8002/auth/google/callback"

GOOGLE_FITNESS_SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
    "https://www.googleapis.com/auth/fitness.body.read",
    "openid",
    "profile",
]


def main():
    parser = argparse.ArgumentParser(description="Obtain Google Health / Fitness OAuth Tokens")
    parser.add_argument("--user-id", default="athlete_1", help="Target athlete or user ID (default: athlete_1)")
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID, help="Google OAuth Client ID")
    parser.add_argument("--client-secret", default=DEFAULT_CLIENT_SECRET, help="Google OAuth Client Secret")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI, help="Authorized Redirect URI in Google Cloud")
    args = parser.parse_args()

    client_id = args.client_id or os.getenv("GOOGLE_HEALTH_CLIENT_ID")
    if not client_id:
        client_id = input("Ingresá tu Google OAuth Client ID: ").strip()

    client_secret = args.client_secret or os.getenv("GOOGLE_HEALTH_CLIENT_SECRET")
    if not client_secret:
        client_secret = input("Ingresá tu Google OAuth Client Secret: ").strip()

    print("\n" + "=" * 65)
    print("🔑 GOOGLE HEALTH / FITNESS API - TOKEN GENERATOR (CLI)")
    print("=" * 65)
    print(f"• User ID:       {args.user_id}")
    print(f"• Client ID:     {client_id[:20]}...")
    print(f"• Redirect URI:  {args.redirect_uri}")
    print("-" * 65)

    client = GoogleHealthOAuthClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=args.redirect_uri,
        scopes=GOOGLE_FITNESS_SCOPES,
    )

    auth_url, verifier = client.get_authorization_url()

    print("\nPASO 1: Abrí esta URL en tu navegador:\n")
    print(auth_url)
    print("\n" + "-" * 65)
    print("PASO 2: Iniciá sesión con tu cuenta de Google y aceptá los permisos.")
    print("Al terminar, el navegador intentará redirigir a una URL como:")
    print("  http://localhost:8002/auth/google/callback?code=4/0A...&state=...")
    print("\nPASO 3: Copiá la URL completa de la barra del navegador (o solo el código '4/0A...'):")

    raw_input_val = input("\nPegá la URL o el código aquí: ").strip()
    if not raw_input_val:
        print("❌ Error: No se ingresó ningún código.")
        return

    # Extract code
    code = raw_input_val
    if "code=" in raw_input_val:
        m = re.search(r"code=([^&]+)", raw_input_val)
        if m:
            code = urllib.parse.unquote(m.group(1)) if "urllib" in globals() else m.group(1)

    print("\n🔄 Canjeando código por tokens con Google...")
    try:
        import urllib.parse
        code = urllib.parse.unquote(code)
        token_data = client.exchange_code_for_tokens(code=code, code_verifier=verifier)
        print("✅ ¡Tokens obtenidos con éxito de Google!")
        
        # Save to dev container vault if it exists
        dev_vault_dir = Path("/home/fsirio/homelab/biometric-coach-dev/data")
        if dev_vault_dir.exists():
            v_dev = LocalSecureVault(vault_dir=dev_vault_dir)
            enc_path = v_dev.store_tokens("google_health", args.user_id, token_data)
            print(f"🔒 Guardado cifrado en el contenedor dev: {enc_path}")

        # Save to standard local vault
        v_local = LocalSecureVault()
        v_local.store_tokens("google_health", args.user_id, token_data)
        print(f"🔒 Guardado cifrado en el vault local: google_health_tokens_{args.user_id}.enc")

        print("\n" + "=" * 65)
        print("📋 TOKEN JSON (por si querés guardarlo o pegarlo en /setup):")
        print("=" * 65)
        print(json.dumps(token_data, indent=2))
        print("=" * 65 + "\n")

    except Exception as e:
        print(f"\n❌ Error al canjear el código con Google: {e}")
        print("Verificá que la Fitness API esté habilitada en Google Cloud y que tu email sea Test User.")


if __name__ == "__main__":
    main()
