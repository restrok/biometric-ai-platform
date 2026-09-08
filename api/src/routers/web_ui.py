"""Web UI router providing zero-configuration Setup wizard and dark-mode Dashboard."""

import json
import logging
import math
import os
import re
import secrets
from datetime import datetime, timedelta
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
    user_id: str = "fsirio"
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
    google_token_json: str | None = None
    use_mock_data: bool = False
    generate_key: bool = True


class SystemConfigPayload(BaseModel):
    storage_mode: str = "local"
    llm_provider: str = "ollama"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    embeddings_provider: str = "fastembed"
    embedding_base_url: str | None = None


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


SETUP_HTML = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Biometric AI Platform - Setup Wizard</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col items-center justify-center p-4">
  <div class="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl p-8 space-y-6">
    <!-- Header with Back to Dashboard button -->
    <div class="flex items-center justify-between border-b border-slate-800 pb-4">
      <div class="flex items-center space-x-3">
        <span class="text-3xl">🏃‍♂️</span>
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white">Biometric AI Platform</h1>
          <p class="text-xs text-slate-400">Local-First (Offline) & Multi-Cloud Autonomous Coaching Assistant</p>
        </div>
      </div>
      <a href="/dashboard" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold px-3.5 py-2 rounded-xl border border-slate-700 transition flex items-center gap-1.5 shadow-sm">
        <span>←</span> Volver al Dashboard
      </a>
    </div>

    <!-- Tab Navigation: Athlete Config vs System Config -->
    <div class="flex border-b border-slate-800 gap-2">
      <button type="button" id="tab-btn-athlete" onclick="switchTab('athlete')" class="pb-2.5 px-4 text-sm font-bold border-b-2 border-blue-500 text-blue-400 flex items-center gap-2">
        <span>🏃‍♂️</span> Configuración del Atleta
      </button>
      <button type="button" id="tab-btn-system" onclick="switchTab('system')" class="pb-2.5 px-4 text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2">
        <span>⚙️</span> Sistema e Infraestructura (LLM / Storage)
      </button>
    </div>

    <!-- TAB 1: Configuración del Atleta (Per-Athlete) -->
    <div id="tab-athlete" class="space-y-6">
      <form id="athlete-form" class="space-y-6" onsubmit="saveAthleteSetup(event)">
        <!-- Athlete Selector & Creator -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="space-y-2">
            <label class="block text-sm font-semibold text-slate-300">1. Seleccionar Atleta</label>
            <select id="user_id_select" onchange="onAthleteSelectChange(this.value)" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
              <option value="new">+ Nuevo Atleta...</option>
            </select>
          </div>
          <div class="space-y-2">
            <label class="block text-sm font-semibold text-slate-300">Tenant / Athlete ID</label>
            <input type="text" id="user_id" value="athlete_1" required
                   class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500 font-mono">
          </div>
        </div>

        <!-- Biometric Tracker Selection -->
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-slate-300">2. Dispositivo / Tracker Biométrico</label>
          <select id="watch_provider" onchange="toggleTrackerOptions(this.value)" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
            <option value="garmin">Garmin Connect Integration (FIT / Telemetry)</option>
            <option value="fitbit">Fitbit Web API (OAuth2 PKCE)</option>
            <option value="google_health">Google Health & Fitbit Air (OAuth 2.0 PKCE)</option>
          </select>
        </div>

        <!-- Garmin Connect Configuration Section -->
        <div id="garmin-config-section" class="bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Garmin Connect Integration</span>
              <span class="bg-cyan-500/20 text-cyan-400 text-[10px] px-2 py-0.5 rounded-full font-mono">SSO / FIT</span>
            </div>
            <span class="text-xs text-slate-400">connect.garmin.com</span>
          </div>

          <!-- Mode 1: Simulated Garmin Device -->
          <div class="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 space-y-1.5">
            <label class="flex items-center space-x-2.5 cursor-pointer select-none">
              <input type="checkbox" id="use_mock_garmin" checked class="w-4 h-4 text-blue-600 rounded bg-slate-800 border-slate-700 focus:ring-blue-500">
              <span class="text-xs font-semibold text-slate-200">🧪 Habilitar Dispositivo Simulado Garmin (Demo Offline)</span>
            </label>
            <p class="text-[11px] text-slate-400 pl-6.5">Cero credenciales requeridas. Genera 14 días de fisiología (HRV, sueño, Body Battery) y actividades con Running Dynamics.</p>
          </div>

          <!-- Mode 2: Real Garmin Connection via SSO Ticket -->
          <div class="space-y-3 pt-2 border-t border-slate-700/50">
            <div class="flex items-center justify-between">
              <span class="text-xs font-semibold text-sky-400">🔗 Conexión Real con tu Reloj Garmin</span>
              <a href="https://sso.garmin.com/sso/embed?id=gauth-widget&embedWidget=true&gauthHost=https://sso.garmin.com/sso&clientId=GarminConnect&locale=en_US&redirectAfterAccountLoginUrl=https://sso.garmin.com/sso/embed&service=https://sso.garmin.com/sso/embed"
                 target="_blank" rel="noopener noreferrer"
                 class="inline-flex items-center space-x-1.5 bg-sky-600 hover:bg-sky-500 text-white px-3 py-1.5 rounded-lg text-xs font-bold transition shadow-sm">
                <span>1. Abrir Garmin SSO Login ↗</span>
              </a>
            </div>

            <div class="space-y-1.5">
              <label class="block text-xs font-semibold text-slate-300">2. Pegar URL con Ticket de Garmin o JSON de Sesión</label>
              <textarea id="garmin_sso_tokens" rows="2"
                        placeholder="https://sso.garmin.com/sso/embed?ticket=ST-XXXXX... o JSON con di_token"
                        class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-xs font-mono text-white focus:outline-none focus:border-blue-500"></textarea>
            </div>
            <button type="button" onclick="exchangeGarminTicket()" class="text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 px-3 py-1.5 rounded-lg font-semibold transition">
              🔄 Canjear Ticket de Garmin
            </button>
            <div id="garmin-exchange-msg" class="hidden text-xs p-2 rounded"></div>
          </div>
        </div>

        <!-- Fitbit Configuration Section -->
        <div id="fitbit-config-section" class="hidden bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Fitbit Web API</span>
            <span class="bg-emerald-500/20 text-emerald-400 text-[10px] px-2 py-0.5 rounded-full font-mono">OAuth 2.0 PKCE</span>
          </div>
          <div class="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 space-y-1.5">
            <label class="flex items-center space-x-2.5 cursor-pointer select-none">
              <input type="checkbox" id="use_mock_fitbit" class="w-4 h-4 text-blue-600 rounded bg-slate-800 border-slate-700">
              <span class="text-xs font-semibold text-slate-200">🧪 Habilitar Dispositivo Simulado Fitbit</span>
            </label>
          </div>
          <div class="flex items-center justify-between pt-2 border-t border-slate-700/50">
            <button type="button" onclick="connectFitbitOAuth()" class="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition">
              Conectar con Fitbit OAuth ↗
            </button>
          </div>
        </div>

        <!-- Google Health Configuration Section -->
        <div id="google-health-config-section" class="hidden bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Google Health & Fitbit Air (Fitbit Air 2026)</span>
            <span class="bg-blue-500/20 text-blue-400 text-[10px] px-2 py-0.5 rounded-full font-mono">OAuth 2.0 PKCE</span>
          </div>
          <div class="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 space-y-1.5">
            <label class="flex items-center space-x-2.5 cursor-pointer select-none">
              <input type="checkbox" id="use_mock_google" class="w-4 h-4 text-blue-600 rounded bg-slate-800 border-slate-700">
              <span class="text-xs font-semibold text-slate-200">🧪 Habilitar Dispositivo Simulado Fitbit Air</span>
            </label>
          </div>
          <div class="flex items-center justify-between pt-2 border-t border-slate-700/50">
            <span class="text-xs text-slate-400">OAuth 2.0 PKCE Directo</span>
            <button type="button" onclick="connectGoogleOAuth()" class="bg-white hover:bg-slate-100 text-slate-900 px-3 py-1.5 rounded-lg text-xs font-semibold transition">
              Conectar con Google ↗
            </button>
          </div>
        </div>

        <div class="pt-4 border-t border-slate-800 flex justify-between items-center">
          <span class="text-xs text-slate-500">Los tokens se guardan cifrados en LocalSecureVault.</span>
          <button type="submit" id="athlete-submit-btn" class="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6 py-2 rounded-xl shadow-lg transition">
            Guardar Atleta
          </button>
        </div>
      </form>

      <!-- MCP API Key Section for this Athlete -->
      <div class="bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">🔑 Servidor MCP & API Key (Model Context Protocol)</span>
          </div>
          <span class="text-[10px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800/80 px-2 py-0.5 rounded">SSE Endpoint: /mcp</span>
        </div>
        <p class="text-xs text-slate-400 leading-relaxed">
          Cada atleta tiene su clave API para interactuar con agentes IA (Antigravity, Claude Desktop, Cursor) a través del protocolo MCP.
        </p>

        <div class="flex items-center gap-3">
          <button type="button" onclick="generateMcpApiKey()" class="bg-slate-700 hover:bg-slate-600 text-white text-xs font-semibold px-3 py-2 rounded-lg transition flex items-center gap-1.5">
            <span>🔑</span> Generar / Ver API Key
          </button>
        </div>

        <div id="mcp-key-box" class="hidden space-y-3 bg-slate-900/80 border border-slate-700 rounded-lg p-3.5">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-emerald-400">API Key Generada:</span>
            <button onclick="copyApiKey()" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded transition">
              📋 Copiar Clave
            </button>
          </div>
          <code id="mcp-key-val" class="block font-mono text-xs text-white bg-slate-950 p-2 rounded border border-slate-800 select-all overflow-x-auto"></code>

          <div class="text-xs text-slate-400 space-y-1">
            <span class="font-semibold text-slate-300">Configuración para Claude Desktop / Antigravity:</span>
            <pre id="mcp-snippet" class="bg-slate-950 p-2.5 rounded border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto select-all"></pre>
          </div>
        </div>
      </div>

      <!-- Delete Athlete (Danger Zone) -->
      <div class="bg-rose-950/20 border border-rose-900/40 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold text-rose-400 uppercase tracking-wider">🗑️ Zona de Peligro: Eliminar Atleta</span>
        </div>
        <p class="text-xs text-slate-400">
          Elimina de forma permanente este atleta, sus actividades en DuckDB, perfiles en SQLite y tokens de credenciales cifrados en Vault.
        </p>
        <button type="button" onclick="deleteAthleteFromSetup()" class="bg-rose-900/60 hover:bg-rose-800 text-rose-200 border border-rose-700 text-xs font-semibold px-4 py-2 rounded-lg transition">
          🗑️ Eliminar Atleta y todos sus datos
        </button>
      </div>
    </div>

    <!-- TAB 2: Infraestructura del Sistema (Global) -->
    <div id="tab-system" class="hidden space-y-6">
      <form id="system-form" class="space-y-6" onsubmit="saveSystemSetup(event)">
        <!-- Storage Architecture -->
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-slate-300">1. Arquitectura de Almacenamiento</label>
          <div class="grid grid-cols-2 gap-4">
            <label class="cursor-pointer border border-slate-700 rounded-xl p-4 flex flex-col items-start bg-slate-800/50 hover:border-blue-500 transition">
              <input type="radio" name="system_storage_mode" value="local" checked class="text-blue-600 mb-2">
              <span class="font-bold text-white">Local-First (Offline)</span>
              <span class="text-xs text-slate-400 mt-1">100% privado. DuckDB + SQLite + Vault. Cero costo GCP.</span>
            </label>
            <label class="cursor-pointer border border-slate-700 rounded-xl p-4 flex flex-col items-start bg-slate-800/50 hover:border-blue-500 transition">
              <input type="radio" name="system_storage_mode" value="gcp" class="text-blue-600 mb-2">
              <span class="font-bold text-white">Google Cloud (GCP)</span>
              <span class="text-xs text-slate-400 mt-1">Data lake empresarial con BigQuery y Secret Manager.</span>
            </label>
          </div>
        </div>

        <!-- System LLM & Embeddings -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="space-y-2">
            <label class="block text-sm font-semibold text-slate-300">2. Motor de Inferencia LLM</label>
            <select id="system_llm_provider" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
              <option value="ollama">Ollama (Local / Cloud)</option>
              <option value="openai">OpenAI Compatible</option>
              <option value="google">Google Gemini</option>
            </select>
          </div>
          <div class="space-y-2">
            <label class="block text-sm font-semibold text-slate-300">3. Motor de Embeddings</label>
            <select id="system_embeddings_provider" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
              <option value="fastembed">FastEmbed (ONNX, CPU/ARM, 0 GPU)</option>
              <option value="ollama">Ollama (nomic-embed-text)</option>
            </select>
          </div>
        </div>

        <div class="bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label class="block text-xs text-slate-400 mb-1">Ollama Base URL</label>
              <input type="text" id="system_llm_base_url" value="https://ollama.com/v1"
                     class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 font-mono">
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Ollama API Key (Opcional)</label>
              <input type="password" id="system_llm_api_key" placeholder="Bearer key"
                     class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 font-mono">
            </div>
          </div>
        </div>

        <div class="pt-4 border-t border-slate-800 flex justify-end">
          <button type="submit" id="system-submit-btn" class="bg-emerald-600 hover:bg-emerald-500 text-white font-semibold px-6 py-2 rounded-xl shadow-lg transition">
            Guardar Configuración del Sistema
          </button>
        </div>
      </form>
    </div>

    <div id="status-msg" class="hidden p-4 rounded-xl text-sm"></div>
  </div>

  <script>
    let activeAthletes = [];

    function switchTab(tab) {
      if (tab === 'athlete') {
        document.getElementById('tab-athlete').classList.remove('hidden');
        document.getElementById('tab-system').classList.add('hidden');
        document.getElementById('tab-btn-athlete').className = 'pb-2.5 px-4 text-sm font-bold border-b-2 border-blue-500 text-blue-400 flex items-center gap-2';
        document.getElementById('tab-btn-system').className = 'pb-2.5 px-4 text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2';
      } else {
        document.getElementById('tab-athlete').classList.add('hidden');
        document.getElementById('tab-system').classList.remove('hidden');
        document.getElementById('tab-btn-athlete').className = 'pb-2.5 px-4 text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center gap-2';
        document.getElementById('tab-btn-system').className = 'pb-2.5 px-4 text-sm font-bold border-b-2 border-blue-500 text-blue-400 flex items-center gap-2';
      }
    }

    async function loadAthletesList() {
      try {
        const res = await fetch('/dashboard/users');
        const data = await res.json();
        activeAthletes = data.users || [];
        const sel = document.getElementById('user_id_select');
        sel.innerHTML = '';
        activeAthletes.forEach(u => {
          const opt = document.createElement('option');
          opt.value = u;
          opt.innerText = u;
          sel.appendChild(opt);
        });
        const newOpt = document.createElement('option');
        newOpt.value = 'new';
        newOpt.innerText = '➕ Nuevo Atleta...';
        sel.appendChild(newOpt);

        const urlParams = new URLSearchParams(window.location.search);
        const currentParam = urlParams.get('user_id');
        if (currentParam && activeAthletes.includes(currentParam)) {
          sel.value = currentParam;
          document.getElementById('user_id').value = currentParam;
        } else if (activeAthletes.length > 0) {
          sel.value = activeAthletes[0];
          document.getElementById('user_id').value = activeAthletes[0];
        }
      } catch (err) {
        console.error('Error loading athletes:', err);
      }
    }

    function onAthleteSelectChange(val) {
      const input = document.getElementById('user_id');
      if (val === 'new') {
        input.value = '';
        input.focus();
      } else {
        input.value = val;
      }
      document.getElementById('mcp-key-box').classList.add('hidden');
    }

    function toggleTrackerOptions(provider) {
      document.getElementById('garmin-config-section').classList.add('hidden');
      document.getElementById('fitbit-config-section').classList.add('hidden');
      document.getElementById('google-health-config-section').classList.add('hidden');

      if (provider === 'garmin') document.getElementById('garmin-config-section').classList.remove('hidden');
      if (provider === 'fitbit') document.getElementById('fitbit-config-section').classList.remove('hidden');
      if (provider === 'google_health') document.getElementById('google-health-config-section').classList.remove('hidden');
    }

    async function saveAthleteSetup(e) {
      e.preventDefault();
      const btn = document.getElementById('athlete-submit-btn');
      btn.disabled = true;
      btn.innerText = 'Guardando...';

      const provider = document.getElementById('watch_provider').value;
      let useMock = false;
      if (provider === 'garmin') useMock = document.getElementById('use_mock_garmin')?.checked ?? false;
      else if (provider === 'fitbit') useMock = document.getElementById('use_mock_fitbit')?.checked ?? false;
      else if (provider === 'google_health') useMock = document.getElementById('use_mock_google')?.checked ?? false;

      const userId = document.getElementById('user_id').value.trim();
      if (!userId) {
        alert('Ingresa un Tenant / Athlete ID válido.');
        btn.disabled = false;
        btn.innerText = 'Guardar Atleta';
        return;
      }

      const payload = {
        storage_mode: 'local',
        user_id: userId,
        watch_provider: provider,
        garmin_sso_tokens: document.getElementById('garmin_sso_tokens')?.value || null,
        use_mock_data: useMock,
        generate_key: true
      };

      try {
        const res = await fetch('/setup/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
          const msg = document.getElementById('status-msg');
          msg.className = 'p-4 rounded-xl text-sm bg-emerald-950/80 border border-emerald-800 text-emerald-300 space-y-2';
          msg.innerHTML = '<p class="font-bold">✅ Atleta Guardado Correctamente!</p>' +
            '<p class="text-xs text-slate-300">Atleta: <span class="text-white font-bold">' + data.user_id + '</span></p>' +
            '<a href="/dashboard?user_id=' + encodeURIComponent(data.user_id) + '" class="inline-block mt-2 text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-semibold px-3 py-1.5 rounded transition">Ir al Dashboard →</a>';
          msg.classList.remove('hidden');
          btn.innerText = '✅ Guardado';
          await loadAthletesList();
        } else {
          throw new Error(data.detail || 'Error al guardar');
        }
      } catch (err) {
        const msg = document.getElementById('status-msg');
        msg.className = 'p-4 rounded-xl text-sm bg-rose-950/80 border border-rose-800 text-rose-300';
        msg.innerText = '❌ Error: ' + err.message;
        msg.classList.remove('hidden');
        btn.disabled = false;
        btn.innerText = 'Reintentar';
      }
    }

    async function saveSystemSetup(e) {
      e.preventDefault();
      const btn = document.getElementById('system-submit-btn');
      btn.disabled = true;
      btn.innerText = 'Guardando...';

      const payload = {
        storage_mode: document.querySelector('input[name="system_storage_mode"]:checked').value,
        llm_provider: document.getElementById('system_llm_provider').value,
        llm_base_url: document.getElementById('system_llm_base_url').value,
        llm_api_key: document.getElementById('system_llm_api_key').value || null,
        embeddings_provider: document.getElementById('system_embeddings_provider').value,
      };

      try {
        const res = await fetch('/setup/system/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
          const msg = document.getElementById('status-msg');
          msg.className = 'p-4 rounded-xl text-sm bg-emerald-950/80 border border-emerald-800 text-emerald-300';
          msg.innerText = '✅ Configuración del sistema guardada con éxito.';
          msg.classList.remove('hidden');
          btn.innerText = '✅ Guardado';
        } else {
          throw new Error(data.detail || 'Error al guardar sistema');
        }
      } catch (err) {
        alert('Error: ' + err.message);
        btn.disabled = false;
        btn.innerText = 'Reintentar';
      }
    }

    async function generateMcpApiKey() {
      const userId = document.getElementById('user_id').value.trim();
      if (!userId) {
        alert('Selecciona o ingresa un Athlete ID primero.');
        return;
      }
      try {
        const res = await fetch('/setup/api-key', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId, name: 'mcp_agent' })
        });
        const data = await res.json();
        if (res.ok) {
          document.getElementById('mcp-key-val').innerText = data.api_key;
          const host = window.location.host;
          const configSnippet = {
            "mcpServers": {
              "biometric-ai": {
                "url": `http://${host}/mcp`,
                "headers": {
                  "X-API-Key": data.api_key
                }
              }
            }
          };
          document.getElementById('mcp-snippet').innerText = JSON.stringify(configSnippet, null, 2);
          document.getElementById('mcp-key-box').classList.remove('hidden');
        } else {
          alert('Error generando API Key: ' + (data.detail || 'Desconocido'));
        }
      } catch (err) {
        alert('Error de red al generar API Key: ' + err.message);
      }
    }

    function copyApiKey() {
      const key = document.getElementById('mcp-key-val').innerText;
      navigator.clipboard.writeText(key).then(() => {
        alert('API Key copiada al portapapeles!');
      });
    }

    async function deleteAthleteFromSetup() {
      const userId = document.getElementById('user_id').value.trim();
      if (!userId) return;
      if (!confirm(`¿Estás seguro de que deseas eliminar permanentemente al atleta "${userId}" y todos sus datos biométricos de DuckDB, SQLite y Vault?\n\nEsta acción es irreversible.`)) {
        return;
      }
      try {
        const res = await fetch('/athletes/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId })
        });
        const data = await res.json();
        if (res.ok) {
          alert(`Atleta ${userId} eliminado correctamente.`);
          await loadAthletesList();
          document.getElementById('mcp-key-box').classList.add('hidden');
        } else {
          alert('Error al eliminar: ' + (data.detail || 'Desconocido'));
        }
      } catch (err) {
        alert('Error de red al eliminar: ' + err.message);
      }
    }

    async function exchangeGarminTicket() {
      const raw = document.getElementById('garmin_sso_tokens').value.trim();
      const userId = document.getElementById('user_id').value.trim() || 'athlete_1';
      const msg = document.getElementById('garmin-exchange-msg');
      if (!raw) {
        alert('Pegá la URL del ticket de Garmin primero.');
        return;
      }
      msg.className = 'text-xs p-2 rounded bg-blue-950/60 text-blue-300 border border-blue-800';
      msg.innerText = '⏳ Canjeando ticket con Garmin...';
      msg.classList.remove('hidden');
      try {
        const res = await fetch('/auth/garmin/exchange', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticket_or_url: raw, user_id: userId })
        });
        const data = await res.json();
        if (res.ok) {
          msg.className = 'text-xs p-2 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800';
          msg.innerText = data.message;
        } else {
          throw new Error(data.detail || 'Error al canjear ticket');
        }
      } catch (err) {
        msg.className = 'text-xs p-2 rounded bg-rose-950/80 text-rose-300 border border-rose-800';
        msg.innerText = '❌ ' + err.message;
      }
    }

    function connectGoogleOAuth() {
      const userId = document.getElementById('user_id').value.trim() || 'athlete_1';
      window.location.href = `/auth/google/login?user_id=${encodeURIComponent(userId)}`;
    }

    function connectFitbitOAuth() {
      const userId = document.getElementById('user_id').value.trim() || 'athlete_1';
      window.location.href = `/auth/fitbit/login?user_id=${encodeURIComponent(userId)}`;
    }

    window.addEventListener('DOMContentLoaded', () => {
      loadAthletesList();
    });
  </script>
</body>
</html>
"""


DASHBOARD_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Biometric AI Coach - Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
  <div class="max-w-7xl mx-auto p-6 space-y-6">
    <!-- Navbar -->
    <header class="flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-slate-800 pb-4 gap-4">
      <div class="flex items-center space-x-3">
        <span class="text-3xl">🏃‍♂️</span>
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white">Biometric AI Coach</h1>
          <div class="flex items-center gap-2 mt-0.5">
            <span class="text-xs text-slate-400">Current Athlete:</span>
            <span id="athlete-badge" class="text-xs font-mono font-semibold text-emerald-400 bg-emerald-950/60 border border-emerald-800/80 px-2 py-0.5 rounded">{{ATHLETE_ID}}</span>
          </div>
        </div>
      </div>
      <div class="flex items-center space-x-3">
        <!-- Athlete Switcher Dropdown & Delete Shortcut -->
        <div class="flex items-center space-x-2 bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5">
          <label for="user-select" class="text-xs font-semibold text-slate-400">Athlete:</label>
          <select id="user-select" onchange="switchAthlete(this.value)" class="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-white font-medium focus:outline-none focus:border-blue-500">
            <option value="{{ATHLETE_ID}}" selected>{{ATHLETE_ID}}</option>
          </select>
          <button onclick="deleteCurrentAthlete()" title="Eliminar atleta actual y todos sus datos" class="text-slate-400 hover:text-rose-400 text-xs px-1.5 py-0.5 rounded transition">
            🗑️
          </button>
        </div>

        <!-- Restored Original Refresh Button -->
        <button onclick="refreshData()" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold px-3 py-2 rounded-xl border border-slate-700 transition flex items-center gap-1.5">
          <span>🔄</span> Refresh
        </button>

        <!-- Restored Original Blue Setup Button -->
        <a href="/setup" class="text-xs bg-blue-600 hover:bg-blue-500 text-white font-semibold px-3 py-2 rounded-xl transition flex items-center gap-1.5 shadow-lg shadow-blue-600/20">
          <span>⚙️</span> Setup
        </a>
      </div>
    </header>

    <!-- Success notification banner (e.g. from OAuth redirect) -->
    <div id="oauth-success-banner" class="hidden bg-emerald-950/70 border border-emerald-800/80 rounded-xl p-3.5 flex items-center justify-between">
      <div class="flex items-center space-x-2.5">
        <span class="text-lg">🎉</span>
        <span id="oauth-banner-text" class="text-xs text-emerald-200 font-medium">Tracker account connected successfully! Biometric telemetry is live.</span>
      </div>
      <button onclick="this.parentElement.remove()" class="text-emerald-400 hover:text-emerald-200 text-xs font-bold px-2 py-1">✕</button>
    </div>

    <!-- KPIs -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-1">
        <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Resting Heart Rate</div>
        <div id="kpi-rhr" class="text-3xl font-bold text-white">-- bpm</div>
        <div class="text-xs text-emerald-400">Baseline resting</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-1">
        <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">HRV (RMSSD)</div>
        <div id="kpi-hrv" class="text-3xl font-bold text-white">-- ms</div>
        <div class="text-xs text-slate-400">Autonomic recovery</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-1">
        <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Body Battery</div>
        <div id="kpi-bb" class="text-3xl font-bold text-blue-400">-- / 100</div>
        <div class="text-xs text-slate-400">Energy reserves</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-1">
        <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Subjective Feeling</div>
        <div id="kpi-feeling" class="text-2xl font-bold text-emerald-400 capitalize">--</div>
        <div class="text-xs text-slate-400">Athlete check-in</div>
      </div>
    </div>

    <!-- Main Grid: Chart & Heart Rate Zones -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- 14-Day Physiology Chart -->
      <div class="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div class="flex justify-between items-center">
          <h2 class="font-bold text-lg text-white">14-Day Physiological Recovery Trends</h2>
          <span class="text-xs text-slate-400">RHR & HRV (RMSSD)</span>
        </div>
        <div id="chart-physio" class="h-64"></div>
      </div>

      <!-- Zones & Training Intensity -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <h2 class="font-bold text-lg text-white">Heart Rate Training Zones</h2>
        <div id="zones-container" class="space-y-3">
          <!-- Populated by JS -->
        </div>
      </div>
    </div>

    <!-- Recent Activities Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
      <h2 class="font-bold text-lg text-white">Recent Training Sessions</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-400">
          <thead class="text-xs uppercase bg-slate-950/60 text-slate-400 border-b border-slate-800">
            <tr>
              <th class="py-3 px-2">Date</th>
              <th>Name</th>
              <th>Type</th>
              <th>Distance</th>
              <th>Duration</th>
              <th>Avg HR</th>
              <th>Power / TE</th>
            </tr>
          </thead>
          <tbody id="activities-tbody" class="divide-y divide-slate-800/60">
            <tr><td colspan="7" class="py-4 text-center text-slate-500">Loading activities...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Chat with AI Coach -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
      <div class="flex items-center space-x-2">
        <span class="text-xl">🤖</span>
        <h2 class="font-bold text-lg text-white">Ask Your Biometric AI Coach</h2>
      </div>

      <div id="chat-box" class="h-64 overflow-y-auto bg-slate-950/60 border border-slate-800/80 rounded-xl p-4 space-y-3 text-sm font-sans">
        <div class="text-slate-400">
          Hola, soy tu entrenador biométrico. Puedes consultarme sobre tu recuperación, zonas de ritmo cardíaco o planificación de tus próximas carreras.
        </div>
      </div>

      <form id="chat-form" onsubmit="sendChatMessage(event)" class="flex gap-2">
        <input type="text" id="chat-input" placeholder="Pregúntale a tu entrenador (ej: ¿Cómo está mi fatiga hoy?)..."
               class="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-4 py-2 text-sm text-white focus:outline-none focus:border-blue-500 transition">
        <button type="submit" id="chat-send-btn"
                class="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-5 py-2 rounded-xl transition">
          Send
        </button>
      </form>
    </div>
  </div>

  <script>
    let physioChart = null;
    let currentUserId = '{{ATHLETE_ID}}';

    async function initAthleteSelector() {
      try {
        const res = await fetch('/dashboard/users');
        const data = await res.json();
        const users = data.users || [];
        const sel = document.getElementById('user-select');
        sel.innerHTML = '';
        users.forEach(u => {
          const opt = document.createElement('option');
          opt.value = u;
          opt.innerText = u;
          if (u === currentUserId) opt.selected = true;
          sel.appendChild(opt);
        });
      } catch (err) {
        console.error('Failed to load users:', err);
      }
    }

    function switchAthlete(userId) {
      currentUserId = userId;
      document.getElementById('athlete-badge').innerText = userId;
      loadDashboard();
    }

    async function deleteCurrentAthlete() {
      if (!confirm(`¿Estás seguro de que deseas eliminar permanentemente al atleta "${currentUserId}" y todos sus datos biométricos de DuckDB, SQLite y Vault?\n\nEsta acción es irreversible.`)) {
        return;
      }
      try {
        const res = await fetch('/athletes/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: currentUserId })
        });
        const data = await res.json();
        if (res.ok) {
          alert(`Atleta ${currentUserId} eliminado correctamente.`);
          window.location.href = '/dashboard';
        } else {
          alert('Error al eliminar atleta: ' + (data.detail || 'Error desconocido'));
        }
      } catch (err) {
        alert('Error de red al eliminar atleta: ' + err.message);
      }
    }

    async function loadDashboard() {
      try {
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('auth') === 'google_success') {
          const banner = document.getElementById('oauth-success-banner');
          document.getElementById('oauth-banner-text').innerText = '🎉 Google Health / Fitbit Air vinculado exitosamente. Tus datos biométricos ya están conectados.';
          banner.classList.remove('hidden');
        } else if (urlParams.get('auth') === 'fitbit_success') {
          const banner = document.getElementById('oauth-success-banner');
          document.getElementById('oauth-banner-text').innerText = '🎉 Fitbit conectado exitosamente con OAuth 2.0 PKCE.';
          banner.classList.remove('hidden');
        }

        const res = await fetch('/dashboard/data?user_id=' + encodeURIComponent(currentUserId));
        const data = await res.json();

        // Populate KPIs
        if (data.daily_physiology && data.daily_physiology.length > 0) {
          const latest = data.daily_physiology[0];
          document.getElementById('kpi-rhr').innerText = latest.resting_heart_rate ? (latest.resting_heart_rate + ' bpm') : '-- bpm';
          document.getElementById('kpi-hrv').innerText = latest.hrv_rmssd ? (Math.round(latest.hrv_rmssd) + ' ms') : '-- ms';
          document.getElementById('kpi-bb').innerText = latest.body_battery_max ? (latest.body_battery_max + ' / 100') : '-- / 100';
          renderPhysioChart(data.daily_physiology.slice().reverse());
        } else {
          document.getElementById('kpi-rhr').innerText = '-- bpm';
          document.getElementById('kpi-hrv').innerText = '-- ms';
          document.getElementById('kpi-bb').innerText = '-- / 100';
          if (physioChart) { physioChart.destroy(); physioChart = null; }
          document.getElementById('chart-physio').innerHTML = '<div class="h-full flex items-center justify-center text-slate-500 text-sm">Sin datos fisiológicos registrados aún.</div>';
        }

        if (data.health_status) {
          document.getElementById('kpi-feeling').innerText = data.health_status.feeling || '--';
        } else {
          document.getElementById('kpi-feeling').innerText = '--';
        }

        // Render Zones
        renderZones(data.profile?.custom_zones || { z1_max: 135, z2_max: 152, z3_max: 165, z4_max: 178 });

        // Render Activities
        renderActivities(data.activities || []);

      } catch (err) {
        console.error('Failed to load dashboard data:', err);
      }
    }

    function renderZones(zones) {
      const zContainer = document.getElementById('zones-container');
      const zoneDefs = [
        { name: 'Zone 1 - Recovery', max: zones.z1_max || 135, color: 'bg-blue-500' },
        { name: 'Zone 2 - Aerobic Base', max: zones.z2_max || 152, color: 'bg-emerald-500' },
        { name: 'Zone 3 - Tempo', max: zones.z3_max || 165, color: 'bg-amber-500' },
        { name: 'Zone 4 - Threshold', max: zones.z4_max || 178, color: 'bg-orange-500' },
        { name: 'Zone 5 - Anaerobic', max: 'Max', color: 'bg-rose-500' }
      ];
      zContainer.innerHTML = zoneDefs.map(z => `
        <div>
          <div class="flex justify-between text-xs mb-1">
            <span class="text-slate-300 font-medium">${z.name}</span>
            <span class="font-mono text-slate-400">&lt; ${z.max} bpm</span>
          </div>
          <div class="w-full bg-slate-800 rounded-full h-2">
            <div class="${z.color} h-2 rounded-full" style="width: 100%"></div>
          </div>
        </div>
      `).join('');
    }

    function renderPhysioChart(series) {
      const dates = series.map(s => s.date);
      const rhr = series.map(s => s.resting_heart_rate);
      const hrv = series.map(s => s.hrv_rmssd);

      const options = {
        chart: { type: 'line', height: 240, toolbar: { show: false }, background: 'transparent' },
        theme: { mode: 'dark' },
        stroke: { curve: 'smooth', width: 2 },
        series: [
          { name: 'Resting HR (bpm)', data: rhr },
          { name: 'HRV RMSSD (ms)', data: hrv }
        ],
        xaxis: { categories: dates, labels: { style: { colors: '#94a3b8' } } },
        yaxis: { labels: { style: { colors: '#94a3b8' } } },
        colors: ['#ef4444', '#3b82f6'],
        grid: { borderColor: '#1e293b' }
      };

      if (physioChart) physioChart.destroy();
      physioChart = new ApexCharts(document.getElementById('chart-physio'), options);
      physioChart.render();
    }

    function renderActivities(activities) {
      const tbody = document.getElementById('activities-tbody');
      if (activities.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-slate-500">No activities recorded yet.</td></tr>';
        return;
      }
      tbody.innerHTML = activities.map(a => `
        <tr class="hover:bg-slate-800/40 transition">
          <td class="py-3 px-2 font-medium">${a.start_time ? new Date(a.start_time).toLocaleDateString() : '--'}</td>
          <td class="font-semibold text-slate-200">${a.activity_name || 'Run'}</td>
          <td class="capitalize">${a.activity_type || 'running'}</td>
          <td>${((a.distance_meters || 0) / 1000).toFixed(2)} km</td>
          <td>${Math.round((a.duration_seconds || 0) / 60)} min</td>
          <td>${Math.round(a.avg_heart_rate || 0)} bpm</td>
          <td>${a.aerobic_training_effect || a.summary?.slice(0, 30) || '--'}</td>
        </tr>
      `).join('');
    }

    async function sendChatMessage(e) {
      e.preventDefault();
      const input = document.getElementById('chat-input');
      const msg = input.value.trim();
      if (!msg) return;

      const chatBox = document.getElementById('chat-box');
      chatBox.innerHTML += '<div class="text-blue-400 font-semibold">You: <span class="text-slate-200 font-normal">' + msg + '</span></div>';
      input.value = '';
      chatBox.scrollTop = chatBox.scrollHeight;

      const btn = document.getElementById('chat-send-btn');
      btn.disabled = true;
      btn.innerText = 'Thinking...';

      try {
        const res = await fetch('/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-User-ID': currentUserId
          },
          body: JSON.stringify({ message: msg, user_id: currentUserId })
        });
        const data = await res.json();
        const reply = data.response || data.message || 'Analysis complete.';
        chatBox.innerHTML += '<div class="text-emerald-400 font-semibold">Coach: <span class="text-slate-200 font-normal whitespace-pre-wrap">' + reply + '</span></div>';
      } catch (err) {
        chatBox.innerHTML += '<div class="text-rose-400 text-xs">Error communicating with coach: ' + err.message + '</div>';
      } finally {
        btn.disabled = false;
        btn.innerText = 'Send';
        chatBox.scrollTop = chatBox.scrollHeight;
      }
    }

    function refreshData() {
      loadDashboard();
    }

    window.addEventListener('DOMContentLoaded', async () => {
      await initAthleteSelector();
      await loadDashboard();
    });
  </script>
</body>
</html>
"""


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
    return HTMLResponse(content=SETUP_HTML)


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

    # Seed mock biometric data if requested
    if payload.use_mock_data or (payload.storage_mode == "local" and not has_tokens):
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


@router.post("/setup/system/save")
async def save_system_setup(payload: SystemConfigPayload):
    """Saves system-level infrastructure configuration."""
    if payload.llm_base_url:
        os.environ["OLLAMA_BASE_URL"] = payload.llm_base_url
    if payload.llm_api_key:
        os.environ["OLLAMA_API_KEY"] = payload.llm_api_key
        os.environ["OPENAI_API_KEY"] = payload.llm_api_key
    if payload.llm_provider:
        os.environ["LLM_PROVIDER"] = payload.llm_provider
    if payload.embeddings_provider:
        os.environ["EMBEDDINGS_PROVIDER"] = payload.embeddings_provider

    return {
        "status": "success",
        "storage_mode": payload.storage_mode,
        "llm_provider": payload.llm_provider,
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
        "mcp_url": "/mcp",
        "mcp_config": {
            "mcpServers": {
                "biometric-ai": {
                    "url": "http://localhost:8002/mcp",
                    "headers": {
                        "X-API-Key": raw_key,
                    },
                }
            }
        },
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
        client_id=effective_client_id,
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
        client_id=effective_client_id,
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
    content = DASHBOARD_HTML_TEMPLATE.replace("{{ATHLETE_ID}}", default_user)
    return HTMLResponse(content=content)


@router.get("/dashboard/data")
async def dashboard_data(user_id: str | None = None):
    """Returns biometric summary JSON payload for the dashboard."""
    engine = get_storage_engine()
    users = engine.list_users()
    target_user = str(user_id or (users[0] if users else os.getenv("DEFAULT_USER_ID", "default_user")))

    profile = engine.get_user_profile(target_user)
    health_status = engine.get_health_status(target_user)
    goals = engine.get_user_goals(target_user)
    daily_physio = engine.get_daily_physiology(target_user, days=14)
    recent_acts = engine.get_recent_activities(target_user, limit=10)

    raw_payload = {
        "user_id": target_user,
        "profile": profile,
        "health_status": health_status,
        "goals": goals,
        "daily_physiology": daily_physio,
        "activities": recent_acts,
    }
    return _sanitize_for_json(raw_payload)
