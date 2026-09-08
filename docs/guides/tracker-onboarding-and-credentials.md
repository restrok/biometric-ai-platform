# Biometric Tracker Onboarding & Local Credential Vault Guide

This guide details how to connect and configure biometric trackers (**Garmin Connect**, **Google Health API / Fitbit Air 2026**, **Fitbit Web API**) in local-first and self-hosted environments.

---

## 1. Fast Track: Offline Demo Mode (Zero Credentials)
If you are evaluating or developing locally and do not want to configure developer accounts or cloud projects:
- In `/setup`, select your tracker and check **🧪 Enable Simulated Device**.
- Automatically generates 14 days of realistic HRV (RMSSD 50–65 ms), resting heart rate, sleep architecture, and activities with complete Garmin Running Dynamics (cadence 176–182 spm, vertical oscillation, GCT balance) directly into DuckDB and SQLite.

---

## 2. Google Health API & Fitbit Air (OAuth 2.0 PKCE)

In a self-hosted / homelab environment, Google OAuth requires an authorized OAuth Client ID to permit redirects.

### Step 1: Google Cloud Console Configuration
1. **Enable API**: In your GCP project (e.g. `bio-intelligence-dev`), navigate to **APIs & Services** > **Enabled APIs & Services** > **+ Enable APIs and Services**, search for **`Fitness API`**, and click **Enable**.
2. **OAuth Consent Screen**:
   - User Type: **External**.
   - If the app is in *Testing* status: Under **Test users**, add your Google account email (e.g. `user@gmail.com`). Otherwise, Google returns `Error 403: access_denied`.
3. **Create Credentials**:
   - Go to **Credentials** > **+ Create Credentials** > **OAuth client ID**.
   - Application Type: **Web application**.
   - **Authorized JavaScript origins**:
     ```text
     http://localhost:8002
     ```
     *(Note: Google strictly forbids raw private numeric IPs such as `http://192.168.x.x` with `Error 400: invalid_request`).*
   - **Authorized redirect URIs**:
     ```text
     http://localhost:8002/auth/google/callback
     ```
   - Click **Create** and copy your `Client ID` and `Client Secret`.

### Step 2: Running from a Local Workstation (SSH Port Forwarding)
When running the platform inside a remote Docker container / Raspberry Pi (`192.168.90.5:8002`) from a separate workstation:
1. Open an SSH local port-forwarding tunnel on your workstation:
   ```bash
   ssh -L 8002:localhost:8002 fsirio@192.168.90.5
   ```
2. Open your browser to:
   ```text
   http://localhost:8002/setup
   ```
3. Click **Conectar con Google**. Google will authorize `http://localhost:8002/auth/google/callback` through the tunnel and encrypt the tokens into your local vault.

### Step 3: Zero-Redirect CLI Alternative (Headless)
If you prefer not to manage browser callbacks or SSH tunnels, run the CLI tool directly on the server:
```bash
PYTHONPATH=api uv run --project api python api/scripts/auth_google_cli.py --user-id athlete_1
```
- The script generates the Google Auth URL.
- Open the URL in any browser, log in, and authorize.
- Copy the resulting URL or `code=4/0A...` and paste it into the terminal.
- Tokens are automatically exchanged and encrypted directly into `LocalSecureVault`.

---

## 3. Garmin Connect Integration

Garmin Connect uses mobile DI session tokens (`di_token`, `di_refresh_token`).

### Connecting with Session Token JSON (Recommended)
1. Paste your Garmin session JSON into `/setup`:
   ```json
   {
     "di_token": "eyJhbGciOiJSUzI1NiIs...",
     "di_refresh_token": "eyJyZWZyZXNoVG9rZW5WYWx1ZSI...",
     "di_client_id": "GARMIN_CONNECT_MOBILE_ANDROID_DI"
   }
   ```
2. The tokens are immediately encrypted into `LocalSecureVault` at `/app/data/vault/garmin_tokens_{user_id}.enc`.
3. Background synchronization and automatic token refresh will maintain the session permanently.

---

## 4. LocalSecureVault Architecture & Security

All OAuth tokens, refresh tokens, and passwords are protected by `LocalSecureVault`:
- **Cipher**: Symmetric Fernet (AES-128-CBC + HMAC-SHA256 authenticated encryption).
- **Master Key**: Generated automatically on first run at `/app/data/.vault_key` (POSIX permissions `0600`).
- **Encrypted Directory**: `/app/data/vault/`.
  - `garmin_tokens_{user_id}.enc`
  - `fitbit_tokens_{user_id}.enc`
  - `google_health_tokens_{user_id}.enc`
- **Zero Plaintext**: No token JSON files are persisted in plaintext. Any legacy plaintext token files found in `~/.garminconnect` are automatically migrated to encrypted storage and unlinked.
