import time

"""Web UI router providing zero-configuration Setup wizard and dark-mode Dashboard."""

import json
import logging
import math
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from src.storage.base import StorageEngine
from src.storage.factory import get_storage_engine
from src.utils.vault import get_vault

log = logging.getLogger(__name__)

router = APIRouter(tags=["Web UI"])

# In-memory store for pending PKCE authorization flows: state -> {user_id, code_verifier, client_id, redirect_uri}
_oauth_sessions: dict[str, dict[str, Any]] = {}

GARMIN_SSO_LOGIN_URL = (
    "https://sso.garmin.com/sso/embed?"
    "id=gauth-widget&embedWidget=true&gauthHost=https://sso.garmin.com/sso&"
    "clientId=GarminConnect&locale=en_US&"
    "redirectAfterAccountLoginUrl=https://sso.garmin.com/sso/embed&"
    "service=https://sso.garmin.com/sso/embed"
)


class SetupConfigPayload(BaseModel):
    storage_mode: str = "local"
    user_id: str = "athlete_1"
    watch_provider: str = "garmin"
    embeddings_provider: str = "fastembed"
    embedding_base_url: str | None = None
    llm_provider: str = "ollama"
    llm_base_url: str = "https://ollama.com/v1"
    llm_api_key: str | None = None
    garmin_sso_tokens: str | None = None
    fitbit_client_id: str | None = None
    fitbit_token_json: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_token_json: str | None = None
    use_mock_data: bool = False
    generate_key: bool = True


class SystemConfigPayload(BaseModel):
    storage_mode: str = "local"
    llm_provider: str = "ollama"
    llm_model: str = "deepseek-v4.1-flash"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    embeddings_provider: str = "fastembed"
    embedding_base_url: str | None = None
    embedding_model: str | None = None


class DeleteAthletePayload(BaseModel):
    user_id: str


class ApiKeyRequest(BaseModel):
    user_id: str
    name: str = "mcp_client"


def seed_mock_biometric_data(engine: StorageEngine, user_id: str, provider: str = "garmin") -> None:
    """Seeds realistic sample biometric data tailored to the tracker provider."""
    now = datetime.now()
    log.info(f"🌱 Seeding simulated biometric data for athlete '{user_id}' with provider '{provider}'...")

    # 1. 14 Days of Daily Physiology
    physio_records = []
    base_hrv = 58.0
    base_rhr = 57
    for i in range(14):
        d = (now - timedelta(days=13 - i)).strftime("%Y-%m-%d")
        noise = (i % 5) - 2
        physio_records.append(
            {
                "date": d,
                "resting_heart_rate": base_rhr + noise,
                "hrv_rmssd": round(base_hrv + (noise * 3.5), 1),
                "hrv_sdnn": round(base_hrv * 1.4, 1),
                "body_battery_max": min(100, 88 + (noise * 3)),
                "body_battery_min": max(15, 26 + noise),
                "stress_avg": 24 - noise,
                "sleep_duration_seconds": 27600 + (noise * 600),
                "sleep_score": min(98, max(65, 86 + (noise * 3))),
            }
        )
    engine.insert_daily_physiology(user_id, physio_records)

    # 2. Activities
    if provider == "garmin":
        activities = [
            {
                "activity_id": f"sim_garmin_{user_id}_1",
                "activity_name": "Garmin Forerunner - Aerobic Base Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=1)).strftime("%Y-%m-%dT07:30:00Z"),
                "duration_seconds": 2700,
                "distance_meters": 8800.0,
                "avg_heart_rate": 142,
                "max_heart_rate": 156,
                "aerobic_training_effect": 3.3,
                "anaerobic_training_effect": 0.2,
                "trimp": 85.0,
                "summary": "Garmin Running Dynamics: Cadence 176 spm, Vert Osc 7.6 cm, GCT Balance 49.8% L / 50.2% R.",
            },
            {
                "activity_id": f"sim_garmin_{user_id}_2",
                "activity_name": "Garmin Forerunner - Lactate Threshold Progression",
                "activity_type": "running",
                "start_time": (now - timedelta(days=3)).strftime("%Y-%m-%dT07:45:00Z"),
                "duration_seconds": 3300,
                "distance_meters": 11400.0,
                "avg_heart_rate": 159,
                "max_heart_rate": 174,
                "aerobic_training_effect": 4.1,
                "anaerobic_training_effect": 1.2,
                "trimp": 128.0,
                "summary": "Garmin Running Dynamics: Cadence 182 spm, Stride Length 1.18m, Avg Power 268W.",
            },
        ]
    elif provider == "google_health":
        activities = [
            {
                "activity_id": f"sim_google_{user_id}_1",
                "activity_name": "Fitbit Air 2026 - Continuous Cadence Aerobic Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=1)).strftime("%Y-%m-%dT08:00:00Z"),
                "duration_seconds": 2400,
                "distance_meters": 7500.0,
                "avg_heart_rate": 138,
                "max_heart_rate": 151,
                "aerobic_training_effect": 3.0,
                "anaerobic_training_effect": 0.1,
                "trimp": 72.0,
                "summary": "Google Health API (Fitbit Air 2026): Stride rate 178 spm, Active Zone Minutes: 38 min.",
            }
        ]
    else:
        activities = [
            {
                "activity_id": f"sim_fitbit_{user_id}_1",
                "activity_name": "Fitbit Web API - Morning Tempo Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=1)).strftime("%Y-%m-%dT08:00:00Z"),
                "duration_seconds": 2400,
                "distance_meters": 7200.0,
                "avg_heart_rate": 145,
                "max_heart_rate": 160,
                "aerobic_training_effect": 3.2,
                "anaerobic_training_effect": 0.3,
                "trimp": 78.0,
                "summary": "Fitbit Web API: Cardio Minutes 28 min, Fat Burn Minutes 12 min.",
            }
        ]

    engine.insert_activities(user_id, activities)
    engine.log_health_status(
        user_id, {"feeling": "Ready & Rested", "fatigue_level": 2, "notes": "Simulated initial baseline."}
    )
    engine.save_user_goal(
        user_id,
        {"goal_type": "race", "description": "Sub-40min 10K Target", "target_date": "2026-11-15", "status": "active"},
    )
    log.info(f"✅ Demo biometric baseline seeded for '{user_id}' ({provider}).")


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
_template_cache: dict[str, str] = {}


def get_template(name: str) -> str:
    """Loads an HTML template from api/templates, caching in memory for zero-IO subsequent reads."""
    if name not in _template_cache:
        template_file = TEMPLATES_DIR / name
        if not template_file.exists():
            raise FileNotFoundError(f"Template {name} not found at {template_file}")
        with open(template_file, encoding="utf-8") as f:
            _template_cache[name] = f.read()
    return _template_cache[name]


def _sanitize_for_json(data: Any) -> Any:
    """Recursively replaces NaN and Infinity floats with None for valid JSON serialization."""
    if isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    if isinstance(data, dict):
        return {k: _sanitize_for_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitize_for_json(v) for v in data]
    return data


@router.get("/setup", response_class=HTMLResponse)
async def setup_page():
    """Renders the single-port onboarding setup wizard."""
    return HTMLResponse(content=get_template("setup.html"))


@router.post("/setup/save")
async def save_setup(payload: SetupConfigPayload):
    """Initializes athlete profile, encrypts tokens, and optionally seeds demo data."""
    engine = get_storage_engine(mode="local" if payload.storage_mode == "local" else "gcp")
    vault = get_vault()

    # 1. Initialize or update user profile
    existing_profile = engine.get_user_profile(payload.user_id)
    updated_profile = {
        **existing_profile,
        "user_id": payload.user_id,
        "watch_provider": payload.watch_provider,
        "storage_mode": payload.storage_mode,
        "setup_completed_at": datetime.now().isoformat(),
    }
    engine.update_user_profile(payload.user_id, updated_profile)

    # 2. Encrypted Vault token persistence
    has_tokens = False

    # Garmin SSO Token or Ticket Paste
    if payload.garmin_sso_tokens:
        raw_val = payload.garmin_sso_tokens.strip()
        ticket_match = re.search(r"(ST-[A-Za-z0-9\-]+)", raw_val)
        tok = None
        if ticket_match:
            ticket = ticket_match.group(1)
            try:
                from garmin_training_toolkit_sdk.auth import get_tokens_from_ticket

                tok = get_tokens_from_ticket(ticket)
                log.info(f"🎫 Exchanged Garmin SSO ticket '{ticket[:10]}...' for user '{payload.user_id}'.")
            except Exception as e:
                log.error(f"Failed to exchange Garmin ticket: {e}")
                err_str = str(e)
                if "401" in err_str or "Unauthorized" in err_str:
                    detail = (
                        f"Garmin rechazó el ticket ({ticket[:12]}...) con 401 Unauthorized. "
                        "Los tickets web de Garmin expiran en pocos segundos. "
                        "💡 Te sugerimos pegar directamente tu JSON de sesión o activar el 'Modo Simulado'."
                    )
                else:
                    detail = f"Error al canjear ticket de Garmin: {err_str}."
                raise HTTPException(status_code=400, detail=detail)

        if not tok:
            try:
                tok = json.loads(raw_val)
            except Exception:
                if not ticket_match:
                    raise HTTPException(
                        status_code=400,
                        detail="Formato de token de Garmin no reconocido. Pegá la URL con 'ticket=ST-...' o el JSON de sesión.",
                    )

        if tok:
            vault.store_tokens("garmin", payload.user_id, tok)
            has_tokens = True
            log.info(f"🔒 Garmin tokens encrypted into vault for '{payload.user_id}'.")

    # Google Health client config and manual token paste
    if payload.google_client_id:
        os.environ["GOOGLE_HEALTH_CLIENT_ID"] = payload.google_client_id
    if payload.google_client_secret:
        os.environ["GOOGLE_HEALTH_CLIENT_SECRET"] = payload.google_client_secret
    if payload.google_token_json:
        try:
            tok = json.loads(payload.google_token_json)
            vault.store_tokens("google_health", payload.user_id, tok)
            has_tokens = True
            log.info(f"🔒 Google Health tokens encrypted into vault for '{payload.user_id}'.")
        except Exception as e:
            log.warning(f"Failed to parse google_token_json: {e}")

    # Fitbit client config and manual token paste
    if payload.fitbit_client_id:
        os.environ["FITBIT_CLIENT_ID"] = payload.fitbit_client_id
    if payload.fitbit_token_json:
        try:
            tok = json.loads(payload.fitbit_token_json)
            vault.store_tokens("fitbit", payload.user_id, tok)
            has_tokens = True
            log.info(f"🔒 Fitbit tokens encrypted into vault for '{payload.user_id}'.")
        except Exception as e:
            log.warning(f"Failed to parse fitbit_token_json: {e}")

    # Seed mock biometric data if requested
    if payload.use_mock_data or (
        payload.storage_mode == "local"
        and not has_tokens
        and not vault.has_tokens(payload.watch_provider, payload.user_id)
    ):
        seed_mock_biometric_data(engine, payload.user_id, provider=payload.watch_provider)

    # Generate initial API key
    api_key = engine.create_api_key(payload.user_id, name="initial_setup_key")

    return {
        "status": "success",
        "user_id": payload.user_id,
        "storage_mode": payload.storage_mode,
        "api_key": api_key,
        "watch_provider": payload.watch_provider,
    }


@router.get("/setup/system")
async def get_system_setup():
    """Returns current active system configuration."""
    provider = os.getenv("LLM_PROVIDER", "ollama")
    model = os.getenv("CORE_MODEL_NAME") or os.getenv("LLM_MODEL", "deepseek-v4.1-flash")
    base_url = (
        os.getenv("OLLAMA_BASE_URL")
        if provider == "ollama"
        else (os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL") or os.getenv("LM_STUDIO_BASE_URL"))
    )
    emb_provider = os.getenv("EMBEDDINGS_PROVIDER", "fastembed")
    emb_base_url = os.getenv("EMBEDDING_BASE_URL")
    emb_model = os.getenv("EMBEDDING_MODEL")
    storage_mode = os.getenv("STORAGE_MODE", "local")
    return {
        "storage_mode": storage_mode,
        "llm_provider": provider,
        "llm_model": model,
        "llm_base_url": base_url,
        "llm_has_api_key": bool(
            os.getenv("OLLAMA_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        ),
        "embeddings_provider": emb_provider,
        "embedding_base_url": emb_base_url,
        "embedding_model": emb_model,
    }


@router.post("/setup/system/save")
async def save_system_setup(payload: SystemConfigPayload):
    """Saves system-level infrastructure configuration persistently."""
    persistent_cfg: dict[str, Any] = {
        "STORAGE_MODE": payload.storage_mode,
        "LLM_PROVIDER": payload.llm_provider,
        "CORE_MODEL_NAME": payload.llm_model,
        "LLM_MODEL": payload.llm_model,
        "EMBEDDINGS_PROVIDER": payload.embeddings_provider,
    }

    os.environ["STORAGE_MODE"] = payload.storage_mode
    os.environ["LLM_PROVIDER"] = payload.llm_provider
    os.environ["CORE_MODEL_NAME"] = payload.llm_model
    os.environ["LLM_MODEL"] = payload.llm_model
    os.environ["EMBEDDINGS_PROVIDER"] = payload.embeddings_provider

    if payload.llm_base_url:
        os.environ["OLLAMA_BASE_URL"] = payload.llm_base_url
        os.environ["OPENAI_BASE_URL"] = payload.llm_base_url
        os.environ["LLM_BASE_URL"] = payload.llm_base_url
        os.environ["LM_STUDIO_BASE_URL"] = payload.llm_base_url
        persistent_cfg["OLLAMA_BASE_URL"] = payload.llm_base_url
        persistent_cfg["OPENAI_BASE_URL"] = payload.llm_base_url
        persistent_cfg["LLM_BASE_URL"] = payload.llm_base_url

    if payload.llm_api_key:
        os.environ["OLLAMA_API_KEY"] = payload.llm_api_key
        os.environ["OPENAI_API_KEY"] = payload.llm_api_key
        os.environ["GOOGLE_API_KEY"] = payload.llm_api_key
        persistent_cfg["OLLAMA_API_KEY"] = payload.llm_api_key
        persistent_cfg["OPENAI_API_KEY"] = payload.llm_api_key
        persistent_cfg["GOOGLE_API_KEY"] = payload.llm_api_key

    if payload.embedding_base_url:
        os.environ["EMBEDDING_BASE_URL"] = payload.embedding_base_url
        persistent_cfg["EMBEDDING_BASE_URL"] = payload.embedding_base_url

    if payload.embedding_model:
        os.environ["EMBEDDING_MODEL"] = payload.embedding_model
        persistent_cfg["EMBEDDING_MODEL"] = payload.embedding_model

    # Persist to system_config.json in data directory
    storage_dir = Path(os.getenv("LOCAL_STORAGE_DIR", "/app/data"))
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        with open(storage_dir / "system_config.json", "w") as f:
            json.dump(persistent_cfg, f, indent=2)
        log.info(f"💾 Persistent system configuration written to {storage_dir / 'system_config.json'}")
    except Exception as e:
        log.warning(f"Could not write system_config.json: {e}")

    return {
        "status": "success",
        "storage_mode": payload.storage_mode,
        "llm_provider": payload.llm_provider,
        "llm_model": payload.llm_model,
        "embeddings_provider": payload.embeddings_provider,
    }


@router.post("/setup/api-key")
async def generate_api_key_endpoint(payload: ApiKeyRequest):
    """Generates an API key for the athlete to use with MCP or external tools."""
    engine = get_storage_engine()
    raw_key = engine.create_api_key(payload.user_id, name=payload.name)
    return {
        "status": "success",
        "user_id": payload.user_id,
        "api_key": raw_key,
        "mcp_url": "/mcp/sse",
        "mcp_config": {
            "mcpServers": {
                "biometric-ai": {
                    "url": "http://localhost:8002/mcp/sse",
                    "headers": {
                        "X-API-Key": raw_key,
                    },
                }
            }
        },
    }


@router.get("/athletes/{user_id}/status")
async def get_athlete_status(user_id: str):
    """Returns biometric connection and vault token status for a specific athlete."""
    vault = get_vault()
    engine = get_storage_engine()
    profile = engine.get_user_profile(user_id) or {}
    return {
        "user_id": user_id,
        "watch_provider": profile.get("watch_provider", "garmin"),
        "garmin_connected": vault.has_tokens("garmin", user_id),
        "fitbit_connected": vault.has_tokens("fitbit", user_id),
        "google_health_connected": vault.has_tokens("google_health", user_id),
        "google_client_id": os.getenv(
            "GOOGLE_HEALTH_CLIENT_ID",
            "188311881874-03v3k6i5svn4n1804alg6nv75pq1otc7.apps.googleusercontent.com",
        ),
        "fitbit_client_id": os.getenv("FITBIT_CLIENT_ID", "23BXYZ"),
    }


@router.post("/athletes/delete")
@router.delete("/athletes/{user_id}")
async def delete_athlete_endpoint(
    user_id: str | None = None,
    payload: DeleteAthletePayload | None = None,
):
    """Deletes an athlete and all associated data from DuckDB, SQLite, and Vault."""
    target_user = user_id or (payload.user_id if payload else None)
    if not target_user:
        raise HTTPException(status_code=400, detail="Missing user_id parameter.")
    engine = get_storage_engine()
    result = engine.delete_user_data(target_user)
    return {"status": "success", "user_id": target_user, "deleted_data": result}


class GarminExchangePayload(BaseModel):
    ticket_or_url: str
    user_id: str = "athlete_1"


@router.post("/auth/garmin/exchange")
async def exchange_garmin_ticket_endpoint(payload: GarminExchangePayload):
    """Exchanges an SSO ticket from sso.garmin.com for OAuth tokens and stores them in LocalSecureVault."""
    ticket_match = re.search(r"(ST-[A-Za-z0-9\-]+)", payload.ticket_or_url.strip())
    if not ticket_match:
        raise HTTPException(
            status_code=400,
            detail="No se encontró un ticket válido (debe contener 'ST-...'). Verificá que copiaste la URL completa tras el login.",
        )
    ticket = ticket_match.group(1)
    try:
        from garmin_training_toolkit_sdk.auth import get_tokens_from_ticket

        tok = get_tokens_from_ticket(ticket)
        get_vault().store_tokens("garmin", payload.user_id, tok)
        return {
            "status": "success",
            "message": f"¡Sesión de Garmin vinculada y cifrada con éxito para '{payload.user_id}'!",
            "user_id": payload.user_id,
        }
    except Exception as e:
        log.error(f"Failed to exchange Garmin ticket: {e}")
        err_str = str(e)
        if "401" in err_str or "Unauthorized" in err_str:
            detail = (
                f"Garmin rechazó el ticket ({ticket[:12]}...) con 401 Unauthorized. "
                "Los tickets web de Garmin expiran en pocos segundos. "
                "💡 Te sugerimos pegar directamente tu JSON de sesión o activar el 'Modo Simulado'."
            )
        else:
            detail = f"Error al canjear ticket con Garmin ({ticket[:10]}...): {err_str}."
        raise HTTPException(status_code=400, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Google Health OAuth 2.0 PKCE Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/auth/google/login")
async def google_auth_login(
    request: Request,
    user_id: str = Query("athlete_1", description="Target athlete or tenant user ID"),
    client_id: str | None = Query(None, description="Optional Google OAuth Client ID"),
):
    """Initiates Google Health OAuth 2.0 PKCE authorization flow."""
    from fitbit_training_toolkit_sdk.auth.google_auth import GoogleHealthOAuthClient

    effective_client_id = client_id or os.getenv(
        "GOOGLE_HEALTH_CLIENT_ID",
        "188311881874-03v3k6i5svn4n1804alg6nv75pq1otc7.apps.googleusercontent.com",
    )
    base_url = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto and base_url.startswith("http://") and forwarded_proto == "https":
        base_url = "https://" + base_url[len("http://") :]

    if "localhost" in base_url or "127.0.0.1" in base_url:
        redirect_uri = f"{base_url}/auth/google/callback"
    else:
        redirect_uri = "http://localhost:8002/auth/google/callback"

    oauth_client = GoogleHealthOAuthClient(
        client_id=str(effective_client_id or ""),
        redirect_uri=redirect_uri,
        client_secret=os.getenv("GOOGLE_HEALTH_CLIENT_SECRET"),
        scopes=[
            "https://www.googleapis.com/auth/fitness.activity.read",
            "https://www.googleapis.com/auth/fitness.sleep.read",
            "https://www.googleapis.com/auth/fitness.heart_rate.read",
            "https://www.googleapis.com/auth/fitness.body.read",
            "openid",
            "profile",
        ],
    )
    state = f"{user_id}:{secrets.token_urlsafe(16)}"
    auth_url, verifier = oauth_client.get_authorization_url(state=state)

    _oauth_sessions[state] = {
        "provider": "google_health",
        "user_id": user_id,
        "code_verifier": verifier,
        "client_id": effective_client_id,
        "redirect_uri": redirect_uri,
    }

    if request.headers.get("accept", "").startswith("application/json"):
        return {"auth_url": auth_url, "state": state}
    return RedirectResponse(url=auth_url, status_code=307)


@router.get("/auth/google/callback")
async def google_auth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Handles OAuth 2.0 PKCE callback and token exchange from accounts.google.com."""
    from fitbit_training_toolkit_sdk.auth.google_auth import GoogleHealthOAuthClient

    if error or not code or not state:
        return HTMLResponse(
            f"<html><body style='background:#0f172a;color:#ef4444;font-family:sans-serif;padding:40px;text-align:center;'>"
            f"<h2>Google OAuth Authorization Failed</h2>"
            f"<p>{error or 'Missing authorization code or state parameter.'}</p>"
            f"<a href='/setup' style='color:#38bdf8;text-decoration:underline;'>Return to Setup Wizard</a>"
            f"</body></html>",
            status_code=400,
        )

    session_data = _oauth_sessions.pop(state, None)
    if not session_data:
        # User might have initiated OAuth via CLI script or session was in another process.
        # Render a friendly helper page allowing the user to copy their code for the CLI.
        return HTMLResponse(
            f"<html><body style='background:#0f172a;color:#f8fafc;font-family:system-ui,sans-serif;padding:40px;max-width:640px;margin:0 auto;'>"
            f"<div style='background:#1e293b;border:1px solid #334155;border-radius:12px;padding:32px;'>"
            f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:16px;'>"
            f"<span style='font-size:32px;'>🔐</span>"
            f"<h2 style='margin:0;font-size:22px;color:#38bdf8;'>Google Authorization Code Received</h2>"
            f"</div>"
            f"<p style='color:#94a3b8;font-size:14px;line-height:1.5;'>"
            f"Google has successfully issued an authorization code. If you are running the authorization CLI script, "
            f"copy the code below (or the complete URL from your browser's address bar) and paste it into your terminal prompt:"
            f"</p>"
            f"<div style='background:#0f172a;border:1px solid #475569;border-radius:8px;padding:12px;margin:20px 0;word-break:break-all;font-family:monospace;color:#a5f3fc;font-size:14px;'>"
            f"{code}"
            f"</div>"
            f"<div style='display:flex;gap:12px;align-items:center;'>"
            f"<button onclick='navigator.clipboard.writeText(\"{code}\");this.innerText=\"✓ Copied!\";' style='background:#0284c7;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-weight:600;cursor:pointer;'>Copy Code</button>"
            f"<a href='/setup' style='color:#94a3b8;font-size:14px;text-decoration:underline;'>Return to Setup</a>"
            f"</div>"
            f"</div>"
            f"</body></html>",
            status_code=200,
        )

    user_id = session_data["user_id"]
    verifier = session_data["code_verifier"]
    client_id = session_data["client_id"]
    redirect_uri = session_data["redirect_uri"]

    try:
        oauth_client = GoogleHealthOAuthClient(
            client_id=client_id,
            redirect_uri=redirect_uri,
            client_secret=os.getenv("GOOGLE_HEALTH_CLIENT_SECRET"),
            scopes=[
                "https://www.googleapis.com/auth/fitness.activity.read",
                "https://www.googleapis.com/auth/fitness.sleep.read",
                "https://www.googleapis.com/auth/fitness.heart_rate.read",
                "https://www.googleapis.com/auth/fitness.body.read",
                "openid",
                "profile",
            ],
        )
        token_data = oauth_client.exchange_code_for_tokens(code, verifier)

        # Encrypt into secure vault
        get_vault().store_tokens("google_health", user_id, token_data)

        # Update user profile in storage
        engine = get_storage_engine()
        existing = engine.get_user_profile(user_id)
        engine.update_user_profile(
            user_id,
            {
                **existing,
                "user_id": user_id,
                "watch_provider": "google_health",
                "google_health_connected": True,
                "google_health_connected_at": datetime.now().isoformat(),
            },
        )

        return RedirectResponse(url=f"/dashboard?user_id={user_id}&auth=google_success", status_code=303)
    except Exception as e:
        log.exception(f"Failed to exchange Google Health auth code: {e}")
        return HTMLResponse(
            f"<html><body style='background:#0f172a;color:#ef4444;font-family:sans-serif;padding:40px;text-align:center;'>"
            f"<h2>Token Exchange Error</h2>"
            f"<p>Failed to exchange code for tokens: {str(e)}</p>"
            f"<a href='/setup' style='color:#38bdf8;text-decoration:underline;'>Return to Setup Wizard</a>"
            f"</body></html>",
            status_code=500,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fitbit Web API OAuth 2.0 PKCE Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/auth/fitbit/login")
async def fitbit_auth_login(
    request: Request,
    user_id: str = Query("athlete_1", description="Target athlete or tenant user ID"),
    client_id: str | None = Query(None, description="Optional Fitbit OAuth Client ID"),
):
    """Initiates Fitbit Web API OAuth 2.0 PKCE authorization flow."""
    from fitbit_training_toolkit_sdk.auth.pkce import generate_pkce_pair, get_authorization_url

    effective_client_id = client_id or os.getenv("FITBIT_CLIENT_ID", "23BXYZ")
    base_url = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto and base_url.startswith("http://") and forwarded_proto == "https":
        base_url = "https://" + base_url[len("http://") :]
    redirect_uri = f"{base_url}/auth/fitbit/callback"

    verifier, challenge = generate_pkce_pair()
    state = f"{user_id}:{secrets.token_urlsafe(16)}"
    auth_url = get_authorization_url(
        client_id=str(effective_client_id or ""),
        code_challenge=challenge,
        redirect_uri=redirect_uri,
        state=state,
    )

    _oauth_sessions[state] = {
        "provider": "fitbit",
        "user_id": user_id,
        "code_verifier": verifier,
        "client_id": effective_client_id,
        "redirect_uri": redirect_uri,
    }

    if request.headers.get("accept", "").startswith("application/json"):
        return {"auth_url": auth_url, "state": state}
    return RedirectResponse(url=auth_url, status_code=307)


@router.get("/auth/fitbit/callback")
async def fitbit_auth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Handles OAuth 2.0 PKCE callback and token exchange from fitbit.com."""
    from fitbit_training_toolkit_sdk.auth.pkce import exchange_code_for_token

    if error or not code or not state:
        return HTMLResponse(
            f"<html><body style='background:#0f172a;color:#ef4444;font-family:sans-serif;padding:40px;text-align:center;'>"
            f"<h2>Fitbit OAuth Authorization Failed</h2>"
            f"<p>{error or 'Missing authorization code or state parameter.'}</p>"
            f"<a href='/setup' style='color:#38bdf8;text-decoration:underline;'>Return to Setup Wizard</a>"
            f"</body></html>",
            status_code=400,
        )

    session_data = _oauth_sessions.pop(state, None)
    if not session_data:
        return HTMLResponse(
            "<html><body style='background:#0f172a;color:#ef4444;font-family:sans-serif;padding:40px;text-align:center;'>"
            "<h2>OAuth Session Expired</h2>"
            "<p>The state parameter is invalid or the session has timed out. Please try again from the Setup Wizard.</p>"
            "<a href='/setup' style='color:#38bdf8;text-decoration:underline;'>Return to Setup Wizard</a>"
            "</body></html>",
            status_code=400,
        )

    user_id = session_data["user_id"]
    verifier = session_data["code_verifier"]
    client_id = session_data["client_id"]
    redirect_uri = session_data["redirect_uri"]

    try:
        token_data = exchange_code_for_token(
            client_id=client_id,
            code=code,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
        )

        # Encrypt into secure vault
        get_vault().store_tokens("fitbit", user_id, token_data)

        # Update user profile in storage
        engine = get_storage_engine()
        existing = engine.get_user_profile(user_id)
        engine.update_user_profile(
            user_id,
            {
                **existing,
                "user_id": user_id,
                "watch_provider": "fitbit",
                "fitbit_connected": True,
                "fitbit_connected_at": datetime.now().isoformat(),
            },
        )

        return RedirectResponse(url=f"/dashboard?user_id={user_id}&auth=fitbit_success", status_code=303)
    except Exception as e:
        log.exception(f"Failed to exchange Fitbit auth code: {e}")
        return HTMLResponse(
            f"<html><body style='background:#0f172a;color:#ef4444;font-family:sans-serif;padding:40px;text-align:center;'>"
            f"<h2>Token Exchange Error</h2>"
            f"<p>Failed to exchange code for tokens: {str(e)}</p>"
            f"<a href='/setup' style='color:#38bdf8;text-decoration:underline;'>Return to Setup Wizard</a>"
            f"</body></html>",
            status_code=500,
        )


_dashboard_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def invalidate_dashboard_cache(user_id: str | None = None) -> None:
    """Invalidates the in-memory dashboard cache for a specific user or all users."""
    if user_id:
        _dashboard_cache.pop(user_id, None)
    else:
        _dashboard_cache.clear()


@router.post("/dashboard/cache/invalidate")
async def invalidate_dashboard_cache_endpoint(user_id: str | None = None):
    """Explicitly purges in-memory dashboard telemetry cache."""
    invalidate_dashboard_cache(user_id)
    return {"status": "ok", "message": f"Cache invalidated for user: {user_id or 'all'}"}


@router.get("/dashboard/users")
async def dashboard_users():
    """Returns list of all active registered athletes/users."""
    engine = get_storage_engine()
    users = engine.list_users()
    return {"users": users}


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(user_id: str | None = None):
    """Renders the dark-mode sports performance dashboard."""
    engine = get_storage_engine()
    users = engine.list_users()
    default_user = str(user_id or (users[0] if users else os.getenv("DEFAULT_USER_ID", "default_user")))
    content = get_template("dashboard.html").replace("{{ATHLETE_ID}}", default_user)
    return HTMLResponse(content=content)


@router.get("/dashboard/data")
async def dashboard_data(user_id: str | None = None, force: bool = False):
    """Returns biometric summary JSON payload for the dashboard, fetching sources in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    engine = get_storage_engine()
    if user_id:
        target_user = user_id
    else:
        users = engine.list_users()
        target_user = str(users[0] if users else os.getenv("DEFAULT_USER_ID", "default_user"))

    now = time.time()
    if not force and target_user in _dashboard_cache:
        cache_time, cached_payload = _dashboard_cache[target_user]
        if now - cache_time < 60:
            return cached_payload

    with ThreadPoolExecutor(max_workers=6) as executor:
        fut_profile = executor.submit(engine.get_user_profile, target_user)
        fut_health = executor.submit(engine.get_health_status, target_user)
        fut_goals = executor.submit(engine.get_user_goals, target_user)
        fut_physio = executor.submit(engine.get_daily_physiology, target_user, 14)
        fut_acts = executor.submit(engine.get_recent_activities, target_user, 60)
        fut_macro = executor.submit(engine.query_macro_load_history, target_user, "weekly", 3)

        profile = fut_profile.result()
        health_status = fut_health.result()
        goals = fut_goals.result()
        daily_physio = fut_physio.result()
        recent_acts = fut_acts.result()
        try:
            macro_load = fut_macro.result() or []
        except Exception as e:
            log.warning(f"Failed to query macro load for {target_user}: {e}")
            macro_load = []

    computed_acwr = None
    weekly_km = 0.0
    if macro_load:
        recent_km = float(macro_load[-1].get("total_distance_km", 0.0))
        weekly_km = round(recent_km, 1)
        past_weeks = macro_load[-4:-1] if len(macro_load) >= 4 else macro_load[:-1]
        chronic_km = sum(float(w.get("total_distance_km", 0.0)) for w in past_weeks) / max(1, len(past_weeks))
        computed_acwr = round(recent_km / chronic_km, 2) if chronic_km > 0 else 1.0

    raw_payload = {
        "user_id": target_user,
        "profile": profile,
        "health_status": health_status,
        "goals": goals,
        "daily_physiology": daily_physio,
        "activities": recent_acts,
        "macro_load": macro_load,
        "acwr": computed_acwr,
        "weekly_km": weekly_km,
    }
    sanitized = _sanitize_for_json(raw_payload)
    _dashboard_cache[target_user] = (now, sanitized)
    return sanitized


@router.post("/athletes/{user_id}/sync")
async def trigger_athlete_sync(user_id: str, days_back: int = 7):
    """Triggers an incremental background biometric sync for the athlete."""
    import threading

    from src.tools.etl_job import run_etl

    def _sync():
        try:
            _dashboard_cache.pop(user_id, None)
            log.info(f"🔄 Direct UI sync started for athlete {user_id} (days_back={days_back})...")
            run_etl(user_id=user_id, days_back=days_back)
        except Exception as e:
            log.error(f"Manual sync failed for {user_id}: {e}")

    threading.Thread(target=_sync, daemon=True).start()
    return {
        "status": "started",
        "user_id": user_id,
        "days_back": days_back,
        "message": f"Sincronización iniciada en segundo plano para {user_id}.",
    }


DEFAULT_DASHBOARD_LAYOUT: dict[str, Any] = {
    "order": [
        "widget-kpis",
        "widget-chart-physio",
        "widget-zones",
        "widget-progress-running",
        "widget-progress-swimming",
        "widget-chart-volume",
        "widget-chart-stress-bb",
        "widget-chart-acwr",
        "widget-goals",
        "widget-activities",
        "widget-coach",
    ],
    "visible": {
        "widget-kpis": True,
        "widget-chart-physio": True,
        "widget-zones": True,
        "widget-progress-running": True,
        "widget-progress-swimming": True,
        "widget-chart-volume": True,
        "widget-chart-stress-bb": False,
        "widget-chart-acwr": False,
        "widget-goals": True,
        "widget-activities": True,
        "widget-coach": True,
    },
    "sizes": {
        "widget-kpis": "12",
        "widget-chart-physio": "8",
        "widget-zones": "4",
        "widget-progress-running": "12",
        "widget-progress-swimming": "12",
        "widget-chart-volume": "12",
        "widget-chart-stress-bb": "12",
        "widget-chart-acwr": "12",
        "widget-goals": "12",
        "widget-activities": "12",
        "widget-coach": "12",
    },
    "active_kpis": [
        "rhr",
        "hrv",
        "body_battery",
        "feeling",
        "stress_avg",
        "sleep",
        "acwr",
        "weekly_km",
    ],
}


@router.get("/athletes/{user_id}/dashboard-layout")
async def get_athlete_dashboard_layout(user_id: str):
    """Returns the customized dashboard layout for a specific athlete."""
    engine = get_storage_engine()
    profile = engine.get_user_profile(user_id) or {}
    saved_layout = profile.get("dashboard_layout")
    if saved_layout and isinstance(saved_layout, dict):
        merged_visible = {**DEFAULT_DASHBOARD_LAYOUT["visible"], **saved_layout.get("visible", {})}
        merged_sizes = {**DEFAULT_DASHBOARD_LAYOUT["sizes"], **saved_layout.get("sizes", {})}

        # Backward compatibility: migrate widget-chart to widget-chart-physio without overwriting valid values
        if "widget-chart" in merged_visible:
            val = merged_visible.pop("widget-chart")
            if "widget-chart-physio" not in saved_layout.get("visible", {}):
                merged_visible["widget-chart-physio"] = val
        if "widget-chart" in merged_sizes:
            val = merged_sizes.pop("widget-chart")
            if "widget-chart-physio" not in saved_layout.get("sizes", {}):
                merged_sizes["widget-chart-physio"] = val

        order = list(saved_layout.get("order", DEFAULT_DASHBOARD_LAYOUT["order"]))
        if "widget-chart" in order:
            order = ["widget-chart-physio" if x == "widget-chart" else x for x in order]

        for wid in DEFAULT_DASHBOARD_LAYOUT["order"]:
            if wid not in order:
                order.append(wid)

        active_kpis = saved_layout.get("active_kpis", DEFAULT_DASHBOARD_LAYOUT["active_kpis"])
        return {
            "user_id": user_id,
            "layout": {
                "order": order,
                "visible": merged_visible,
                "sizes": merged_sizes,
                "active_kpis": active_kpis,
            },
        }
    return {"user_id": user_id, "layout": DEFAULT_DASHBOARD_LAYOUT}


@router.post("/athletes/{user_id}/dashboard-layout")
async def save_athlete_dashboard_layout(user_id: str, payload: dict[str, Any]):
    """Persists a personalized dashboard widget layout for a specific athlete."""
    engine = get_storage_engine()
    raw_order = payload.get("order", DEFAULT_DASHBOARD_LAYOUT["order"])
    raw_visible = payload.get("visible", DEFAULT_DASHBOARD_LAYOUT["visible"])
    raw_sizes = payload.get("sizes", DEFAULT_DASHBOARD_LAYOUT["sizes"])
    active_kpis = payload.get("active_kpis", DEFAULT_DASHBOARD_LAYOUT["active_kpis"])

    # Clean legacy keys so they are never persisted or merged back
    clean_visible = {k: v for k, v in raw_visible.items() if k != "widget-chart"}
    clean_sizes = {k: v for k, v in raw_sizes.items() if k != "widget-chart"}
    clean_order = ["widget-chart-physio" if x == "widget-chart" else x for x in raw_order]
    clean_layout = {"order": clean_order, "visible": clean_visible, "sizes": clean_sizes, "active_kpis": active_kpis}

    engine.update_user_profile(user_id, {"dashboard_layout": clean_layout})
    log.info(f"🎨 Saved personalized dashboard layout for athlete: {user_id}")
    return {"status": "ok", "user_id": user_id, "layout": clean_layout}
