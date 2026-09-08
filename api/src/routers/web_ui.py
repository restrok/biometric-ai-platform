"""Web UI router providing zero-configuration Setup wizard and dark-mode Dashboard."""

import json
import logging
import math
import os
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from src.storage.base import StorageEngine
from src.storage.factory import get_storage_engine
from src.utils.vault import get_vault

log = logging.getLogger(__name__)

router = APIRouter(tags=["Web UI"])

# In-memory store for pending PKCE authorization flows: state -> session_dict
_oauth_sessions: dict[str, dict[str, Any]] = {}


class SetupConfigPayload(BaseModel):
    storage_mode: str = "local"  # "local" or "gcp"
    user_id: str = "athlete_1"
    llm_provider: str = "ollama"  # "ollama", "openrouter", "google", "openai"
    llm_model: str = "deepseek-v4-flash:0731"
    llm_base_url: str | None = "https://ollama.com/v1"
    llm_api_key: str | None = None
    embeddings_provider: str = "fastembed"  # "fastembed", "ollama", "google"
    embedding_base_url: str | None = "http://192.168.89.32:11434/v1"
    watch_provider: str = "garmin"  # "garmin", "fitbit", "google_health"
    garmin_sso_tokens: str | None = None
    fitbit_client_id: str | None = None
    fitbit_token_json: str | None = None
    google_client_id: str | None = None
    google_token_json: str | None = None
    use_mock_data: bool = False
    generate_key: bool = True


def seed_mock_biometric_data(engine: StorageEngine, user_id: str, provider: str = "garmin") -> None:
    """Seeds realistic sample biometric data tailored to the tracker provider."""
    now = datetime.now()
    log.info(f"🌱 Seeding simulated biometric data for athlete '{user_id}' with provider '{provider}'...")

    # 1. 14 Days of Daily Physiology (HRV RMSSD, RHR, Sleep, Body Battery)
    physio_records = []
    base_hrv = 58.0
    base_rhr = 57
    for i in range(14):
        d = (now - timedelta(days=13 - i)).strftime("%Y-%m-%d")
        noise = (i % 5) - 2
        physio_records.append({
            "date": d,
            "resting_heart_rate": base_rhr + noise,
            "hrv_rmssd": round(base_hrv + (noise * 3.5), 1),
            "hrv_sdnn": round(base_hrv * 1.4, 1),
            "body_battery_max": min(100, 88 + (noise * 3)),
            "body_battery_min": max(15, 26 + noise),
            "stress_avg": 24 - noise,
            "sleep_duration_seconds": 27600 + (noise * 600),  # ~7.6 hours
            "sleep_score": min(98, max(65, 86 + (noise * 3))),
        })
    engine.insert_daily_physiology(user_id, physio_records)

    # 2. Realistic Running Sessions tailored to tracker
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
                "anaerobic_training_effect": 1.8,
                "trimp": 128.0,
                "summary": "Garmin Running Dynamics: Cadence 182 spm, Vert Osc 8.1 cm, GCT Balance 50.0% L / 50.0% R.",
            },
            {
                "activity_id": f"sim_garmin_{user_id}_3",
                "activity_name": "Garmin Forerunner - 5x1000m VO2 Max Intervals",
                "activity_type": "running",
                "start_time": (now - timedelta(days=6)).strftime("%Y-%m-%dT18:30:00Z"),
                "duration_seconds": 3120,
                "distance_meters": 10500.0,
                "avg_heart_rate": 166,
                "max_heart_rate": 185,
                "aerobic_training_effect": 4.5,
                "anaerobic_training_effect": 2.9,
                "trimp": 142.0,
                "summary": "High intensity interval workout. Rapid recovery in active recovery intervals.",
            },
            {
                "activity_id": f"sim_garmin_{user_id}_4",
                "activity_name": "Garmin Forerunner - Sunday Long Aerobic Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=8)).strftime("%Y-%m-%dT08:00:00Z"),
                "duration_seconds": 5700,
                "distance_meters": 17200.0,
                "avg_heart_rate": 145,
                "max_heart_rate": 160,
                "aerobic_training_effect": 3.9,
                "anaerobic_training_effect": 0.3,
                "trimp": 168.0,
                "summary": "Garmin Running Dynamics: Cadence 174 spm, Ground contact time 238 ms.",
            },
            {
                "activity_id": f"sim_garmin_{user_id}_5",
                "activity_name": "Garmin Forerunner - Easy Recovery Shakeout",
                "activity_type": "running",
                "start_time": (now - timedelta(days=11)).strftime("%Y-%m-%dT08:15:00Z"),
                "duration_seconds": 1800,
                "distance_meters": 4800.0,
                "avg_heart_rate": 131,
                "max_heart_rate": 142,
                "aerobic_training_effect": 2.0,
                "anaerobic_training_effect": 0.0,
                "trimp": 38.0,
                "summary": "Low aerobic load Zone 1 recovery session.",
            },
        ]
    elif provider == "fitbit":
        activities = [
            {
                "activity_id": f"sim_fitbit_{user_id}_1",
                "activity_name": "Fitbit - Morning Tempo Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=1)).strftime("%Y-%m-%dT07:30:00Z"),
                "duration_seconds": 2580,
                "distance_meters": 8200.0,
                "avg_heart_rate": 153,
                "max_heart_rate": 171,
                "aerobic_training_effect": 3.5,
                "anaerobic_training_effect": 1.1,
                "trimp": 94.0,
                "summary": "Fitbit cardio fitness telemetry capture. High tempo interval in cardio zone.",
            },
            {
                "activity_id": f"sim_fitbit_{user_id}_2",
                "activity_name": "Fitbit - Easy Aerobic Recovery",
                "activity_type": "running",
                "start_time": (now - timedelta(days=3)).strftime("%Y-%m-%dT08:00:00Z"),
                "duration_seconds": 2100,
                "distance_meters": 5500.0,
                "avg_heart_rate": 133,
                "max_heart_rate": 144,
                "aerobic_training_effect": 2.1,
                "anaerobic_training_effect": 0.0,
                "trimp": 44.0,
                "summary": "Fat burn zone aerobic recovery session.",
            },
            {
                "activity_id": f"sim_fitbit_{user_id}_3",
                "activity_name": "Fitbit - Peak Zone Interval Session",
                "activity_type": "running",
                "start_time": (now - timedelta(days=6)).strftime("%Y-%m-%dT18:15:00Z"),
                "duration_seconds": 3000,
                "distance_meters": 9800.0,
                "avg_heart_rate": 164,
                "max_heart_rate": 182,
                "aerobic_training_effect": 4.2,
                "anaerobic_training_effect": 2.5,
                "trimp": 130.0,
                "summary": "Fitbit peak zone interval workout with rapid HR descent.",
            },
            {
                "activity_id": f"sim_fitbit_{user_id}_4",
                "activity_name": "Fitbit - Weekend Endurance Long Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=8)).strftime("%Y-%m-%dT08:30:00Z"),
                "duration_seconds": 5400,
                "distance_meters": 15800.0,
                "avg_heart_rate": 147,
                "max_heart_rate": 161,
                "aerobic_training_effect": 3.8,
                "anaerobic_training_effect": 0.4,
                "trimp": 158.0,
                "summary": "Extended cardio zone endurance run.",
            },
            {
                "activity_id": f"sim_fitbit_{user_id}_5",
                "activity_name": "Fitbit - Progression Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=11)).strftime("%Y-%m-%dT07:15:00Z"),
                "duration_seconds": 2820,
                "distance_meters": 9100.0,
                "avg_heart_rate": 157,
                "max_heart_rate": 175,
                "aerobic_training_effect": 3.7,
                "anaerobic_training_effect": 1.4,
                "trimp": 108.0,
                "summary": "Progressive build from fat burn to peak zone.",
            },
        ]
    else:  # google_health / default
        activities = [
            {
                "activity_id": f"sim_fitbit_air_{user_id}_1",
                "activity_name": "Fitbit Air - Morning Tempo Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=1)).strftime("%Y-%m-%dT07:30:00Z"),
                "duration_seconds": 2640,
                "distance_meters": 8500.0,
                "avg_heart_rate": 154,
                "max_heart_rate": 172,
                "aerobic_training_effect": 3.6,
                "anaerobic_training_effect": 1.2,
                "trimp": 98.5,
                "summary": "Fitbit Air 2026 PPG sensor capture. High tempo interval in Zone 3/4.",
            },
            {
                "activity_id": f"sim_fitbit_air_{user_id}_2",
                "activity_name": "Fitbit Air - Easy Aerobic Recovery",
                "activity_type": "running",
                "start_time": (now - timedelta(days=3)).strftime("%Y-%m-%dT08:00:00Z"),
                "duration_seconds": 2100,
                "distance_meters": 5600.0,
                "avg_heart_rate": 134,
                "max_heart_rate": 145,
                "aerobic_training_effect": 2.2,
                "anaerobic_training_effect": 0.0,
                "trimp": 45.0,
                "summary": "Low intensity Zone 2 recovery jog with smooth cardiac drift.",
            },
            {
                "activity_id": f"sim_fitbit_air_{user_id}_3",
                "activity_name": "Fitbit Air - 6x800m VO2 Max Intervals",
                "activity_type": "running",
                "start_time": (now - timedelta(days=6)).strftime("%Y-%m-%dT18:15:00Z"),
                "duration_seconds": 3120,
                "distance_meters": 10200.0,
                "avg_heart_rate": 165,
                "max_heart_rate": 184,
                "aerobic_training_effect": 4.3,
                "anaerobic_training_effect": 2.8,
                "trimp": 135.0,
                "summary": "High intensity interval workout. Rapid post-interval HR recovery.",
            },
            {
                "activity_id": f"sim_fitbit_air_{user_id}_4",
                "activity_name": "Fitbit Air - Sunday Long Aerobic Run",
                "activity_type": "running",
                "start_time": (now - timedelta(days=8)).strftime("%Y-%m-%dT08:30:00Z"),
                "duration_seconds": 5580,
                "distance_meters": 16400.0,
                "avg_heart_rate": 146,
                "max_heart_rate": 162,
                "aerobic_training_effect": 3.9,
                "anaerobic_training_effect": 0.4,
                "trimp": 162.0,
                "summary": "Endurance base building in Zone 2 with minimal cardiac decoupling.",
            },
            {
                "activity_id": f"sim_fitbit_air_{user_id}_5",
                "activity_name": "Fitbit Air - Progression Tempo Session",
                "activity_type": "running",
                "start_time": (now - timedelta(days=11)).strftime("%Y-%m-%dT07:15:00Z"),
                "duration_seconds": 2880,
                "distance_meters": 9500.0,
                "avg_heart_rate": 158,
                "max_heart_rate": 176,
                "aerobic_training_effect": 3.8,
                "anaerobic_training_effect": 1.5,
                "trimp": 112.0,
                "summary": "Progressive build from Z2 to threshold Z4 pace.",
            },
        ]
    engine.insert_activities(user_id, activities)

    # 3. Subjective Health Status & Training Goal
    engine.log_health_status(user_id, {
        "feeling": "Ready & Rested",
        "soreness_level": 2,
        "fatigue_level": 2,
        "sleep_quality": 4,
        "readiness_score": 88,
        "notes": f"Simulated {provider.capitalize()} biometric telemetry active. HRV baseline stable.",
    })
    engine.save_user_goal(user_id, {
        "goal_id": f"goal_{user_id}_1",
        "goal_type": "event",
        "description": "Sub-40min 10K Target",
        "target_metric": "pace_10k",
        "target_value": 240,
        "target_date": "2026-12-01",
        "status": "active",
    })
    log.info(f"✅ Simulated biometric data successfully seeded for '{user_id}'.")


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
    <div class="flex items-center space-x-3 border-b border-slate-800 pb-4">
      <span class="text-3xl">🏃‍♂️</span>
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-white">Biometric AI Platform</h1>
        <p class="text-sm text-slate-400">Local-First & Multi-Cloud Autonomous Coaching Assistant</p>
      </div>
    </div>

    <form id="setup-form" class="space-y-6" onsubmit="saveSetup(event)">
      <!-- Storage Architecture -->
      <div class="space-y-2">
        <label class="block text-sm font-semibold text-slate-300">1. Storage Architecture</label>
        <div class="grid grid-cols-2 gap-4">
          <label class="cursor-pointer border border-slate-700 rounded-xl p-4 flex flex-col items-start bg-slate-800/50 hover:border-blue-500 transition">
            <input type="radio" name="storage_mode" value="local" checked class="text-blue-600 mb-2">
            <span class="font-bold text-white">Local-First (Offline)</span>
            <span class="text-xs text-slate-400 mt-1">100% private. Uses DuckDB + SQLite + Encrypted Vault. Zero GCP costs.</span>
          </label>
          <label class="cursor-pointer border border-slate-700 rounded-xl p-4 flex flex-col items-start bg-slate-800/50 hover:border-blue-500 transition">
            <input type="radio" name="storage_mode" value="gcp" class="text-blue-600 mb-2">
            <span class="font-bold text-white">Google Cloud (GCP)</span>
            <span class="text-xs text-slate-400 mt-1">Cloud-native enterprise lake. Uses BigQuery + Secret Manager.</span>
          </label>
        </div>
      </div>

      <!-- User & Tenancy -->
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-slate-300">2. Tenant / Athlete ID</label>
          <input type="text" id="user_id" value="athlete_1" required
                 class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
        </div>
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-slate-300">3. Biometric Tracker</label>
          <select id="watch_provider" onchange="toggleTrackerOptions(this.value)" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
            <option value="garmin">Garmin Connect (FIT / Telemetry)</option>
            <option value="fitbit">Fitbit (OAuth2 PKCE / Web API)</option>
            <option value="google_health">Google Health API (Fitbit Air 2026)</option>
          </select>
        </div>
      </div>

      <!-- Garmin Connect Configuration Section -->
      <div id="garmin-config-section" class="bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Garmin Connect Integration</span>
            <span class="bg-cyan-500/20 text-cyan-400 text-[10px] px-2 py-0.5 rounded-full font-mono">SSO Token / FIT</span>
          </div>
          <span class="text-xs text-slate-400">connect.garmin.com</span>
        </div>

        <!-- Mode 1: Simulated Garmin Device -->
        <div class="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 space-y-1.5">
          <label class="flex items-center space-x-2.5 cursor-pointer select-none">
            <input type="checkbox" id="use_mock_garmin" checked class="w-4 h-4 text-blue-600 rounded bg-slate-800 border-slate-700 focus:ring-blue-500">
            <span class="text-xs font-semibold text-slate-200">🧪 Enable Simulated Garmin Device (Offline Demo Data)</span>
          </label>
          <p class="text-[11px] text-slate-400 pl-6.5">Zero credentials needed. Automatically seeds 14 days of realistic HRV, sleep stages, Body Battery, and running sessions with Garmin Running Dynamics (cadence, vertical oscillation, GCT balance).</p>
        </div>

        <!-- Mode 2: Paste Garmin SSO Token JSON -->
        <div class="space-y-1.5 pt-1">
          <label class="block text-xs font-medium text-slate-300">Live Device: Garmin SSO Token JSON (di_token)</label>
          <textarea id="garmin_sso_tokens" rows="2" placeholder='{"di_token": "...", "di_refresh_token": "...", "di_client_id": "..."}'
                    class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-[10px] font-mono text-white focus:outline-none focus:border-blue-500"></textarea>
          <p class="text-[10px] text-slate-500">🔒 <strong>Zero password exposure:</strong> Paste your Garmin SSO token JSON. It will be encrypted into your local AES vault immediately.</p>
        </div>
      </div>

      <!-- Fitbit Configuration Section -->
      <div id="fitbit-config-section" class="hidden bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Fitbit Web API</span>
            <span class="bg-teal-500/20 text-teal-400 text-[10px] px-2 py-0.5 rounded-full font-mono">OAuth 2.0 PKCE</span>
          </div>
          <span class="text-xs text-slate-400">api.fitbit.com</span>
        </div>

        <!-- Mode 1: Simulated Fitbit Device -->
        <div class="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 space-y-1.5">
          <label class="flex items-center space-x-2.5 cursor-pointer select-none">
            <input type="checkbox" id="use_mock_fitbit" checked class="w-4 h-4 text-blue-600 rounded bg-slate-800 border-slate-700 focus:ring-blue-500">
            <span class="text-xs font-semibold text-slate-200">🧪 Enable Simulated Fitbit Device (Instant Offline Demo Data)</span>
          </label>
          <p class="text-[11px] text-slate-400 pl-6.5">Zero credentials needed. Seeds realistic daily cardio fitness, sleep stages, and workouts via MockFitbitProvider.</p>
        </div>

        <!-- Mode 2: Live Device Connection -->
        <div class="space-y-2 pt-1">
          <label class="block text-xs font-medium text-slate-300">Live Device: Fitbit OAuth Client ID</label>
          <div class="flex space-x-2">
            <input type="text" id="fitbit_client_id" placeholder="e.g. 23BXYZ"
                   class="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
            <button type="button" onclick="connectFitbitOAuth()"
                    class="bg-teal-500 hover:bg-teal-400 text-slate-950 px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-1.5 transition">
              <span>Connect with Fitbit</span>
            </button>
          </div>
          <p class="text-[10px] text-slate-500">Redirects to <code>fitbit.com/oauth2/authorize</code> for PKCE authorization. Callback: <code>/auth/fitbit/callback</code></p>
        </div>

        <!-- Mode 3: Manual Token JSON Paste -->
        <details class="text-[11px] text-slate-400">
          <summary class="cursor-pointer hover:text-slate-300 select-none">Or paste raw Fitbit token JSON manually</summary>
          <div class="mt-2 space-y-1">
            <textarea id="fitbit_token_json" rows="2" placeholder='{"access_token": "...", "refresh_token": "...", "user_id": "..."}'
                       class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-[10px] font-mono text-white focus:outline-none focus:border-blue-500"></textarea>
          </div>
        </details>
      </div>

      <!-- Google Health / Fitbit Air Configuration Section -->
      <div id="google-health-config-section" class="hidden bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Google Health & Fitbit Air</span>
            <span class="bg-blue-500/20 text-blue-400 text-[10px] px-2 py-0.5 rounded-full font-mono">OAuth 2.0 PKCE</span>
          </div>
          <span class="text-xs text-slate-400">health.googleapis.com</span>
        </div>

        <!-- Mode 1: Simulated / Mock Device -->
        <div class="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 space-y-1.5">
          <label class="flex items-center space-x-2.5 cursor-pointer select-none">
            <input type="checkbox" id="use_mock_google" checked class="w-4 h-4 text-blue-600 rounded bg-slate-800 border-slate-700 focus:ring-blue-500">
            <span class="text-xs font-semibold text-slate-200">🧪 Enable Simulated Fitbit Air (Instant Offline Demo Data)</span>
          </label>
          <p class="text-[11px] text-slate-400 pl-6.5">Zero credentials needed. Seeds 14 days of realistic HRV, sleep stages, Body Battery, and running sessions into DuckDB.</p>
        </div>

        <!-- Mode 2: Live Device Connection -->
        <div class="space-y-2 pt-1">
          <label class="block text-xs font-medium text-slate-300">Live Device: Google Cloud OAuth Client ID</label>
          <div class="flex space-x-2">
            <input type="text" id="google_client_id" placeholder="e.g. 123456-xxx.apps.googleusercontent.com"
                   class="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
            <button type="button" onclick="connectGoogleOAuth()"
                    class="bg-white hover:bg-slate-100 text-slate-900 px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-1.5 transition">
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>
              <span>Connect with Google</span>
            </button>
          </div>
          <p class="text-[10px] text-slate-500">Redirects to Google Accounts for PKCE authorization. Callback: <code>/auth/google/callback</code></p>
        </div>

        <!-- Mode 3: Manual Token JSON Paste -->
        <details class="text-[11px] text-slate-400">
          <summary class="cursor-pointer hover:text-slate-300 select-none">Or paste raw Google token JSON manually</summary>
          <div class="mt-2 space-y-1">
            <textarea id="google_token_json" rows="2" placeholder='{"access_token": "ya29...", "refresh_token": "1//..."}'
                       class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-[10px] font-mono text-white focus:outline-none focus:border-blue-500"></textarea>
          </div>
        </details>
      </div>

      <!-- Embeddings & LLM -->
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-slate-300">4. Local Embeddings</label>
          <select id="embeddings_provider" onchange="toggleEmbeddingOptions(this.value)" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
            <option value="fastembed">FastEmbed (ONNX, CPU/ARM, 0 GPU)</option>
            <option value="ollama">Ollama (nomic-embed-text)</option>
            <option value="google">Google Gemini Embeddings</option>
          </select>
        </div>
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-slate-300">5. Reasoning LLM Engine</label>
          <select id="llm_provider" onchange="toggleLlmOptions(this.value)" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
            <option value="ollama">Ollama (Local or Cloud Hosted)</option>
            <option value="openrouter">OpenRouter (Cloud API)</option>
            <option value="google">Google Gemini</option>
            <option value="openai">OpenAI Compatible</option>
          </select>
        </div>
      </div>

      <!-- Ollama Embedding Settings -->
      <div id="embedding-config-section" class="hidden bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-2">
        <div class="flex items-center justify-between">
          <label class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Ollama Embeddings Service</label>
          <span class="text-xs text-slate-400">nomic-embed-text (768 dims)</span>
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1">Ollama Host URL / IP</label>
          <input type="text" id="embedding_base_url" value="http://192.168.89.32:11434/v1" placeholder="http://192.168.89.32:11434/v1"
                 class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
          <p class="text-[10px] text-slate-500 mt-1">E.g., your ThinkCentre IP: <code>http://192.168.89.32:11434/v1</code> or <code>http://localhost:11434/v1</code></p>
        </div>
      </div>

      <!-- Ollama / LLM Configuration Section -->
      <div id="ollama-config-section" class="bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <label class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Ollama LLM Settings</label>
          <span class="text-xs text-slate-400">Ollama Cloud: <code>https://ollama.com/v1</code></span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label class="block text-xs text-slate-400 mb-1">Base URL (must end in /v1)</label>
            <input type="text" id="llm_base_url" value="https://ollama.com/v1" placeholder="https://ollama.com/v1"
                   class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">API Key (Cloud/Remote)</label>
            <input type="password" id="llm_api_key" placeholder="Bearer API Key from ollama.com"
                   class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
          </div>
        </div>
      </div>

      <div class="pt-4 border-t border-slate-800 flex justify-end">
        <button type="submit" id="submit-btn"
                class="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6 py-2.5 rounded-xl shadow-lg hover:shadow-blue-500/25 transition">
          Save Configuration & Launch
        </button>
      </div>
    </form>

    <div id="status-msg" class="hidden p-4 rounded-xl text-sm"></div>
  </div>

  <script>
    function toggleTrackerOptions(provider) {
      document.getElementById('garmin-config-section').classList.add('hidden');
      document.getElementById('fitbit-config-section').classList.add('hidden');
      document.getElementById('google-health-config-section').classList.add('hidden');

      if (provider === 'garmin') {
        document.getElementById('garmin-config-section').classList.remove('hidden');
      } else if (provider === 'fitbit') {
        document.getElementById('fitbit-config-section').classList.remove('hidden');
      } else if (provider === 'google_health') {
        document.getElementById('google-health-config-section').classList.remove('hidden');
      }
    }

    function toggleEmbeddingOptions(provider) {
      const sec = document.getElementById('embedding-config-section');
      if (provider === 'ollama') {
        sec.classList.remove('hidden');
      } else {
        sec.classList.add('hidden');
      }
    }

    function toggleLlmOptions(provider) {
      const sec = document.getElementById('ollama-config-section');
      if (provider === 'ollama' || provider === 'openai') {
        sec.classList.remove('hidden');
      } else {
        sec.classList.add('hidden');
      }
    }

    function connectGoogleOAuth() {
      const userId = document.getElementById('user_id').value || 'athlete_1';
      const clientId = document.getElementById('google_client_id').value;
      let url = '/auth/google/login?user_id=' + encodeURIComponent(userId);
      if (clientId) {
        url += '&client_id=' + encodeURIComponent(clientId);
      }
      window.location.href = url;
    }

    function connectFitbitOAuth() {
      const userId = document.getElementById('user_id').value || 'athlete_1';
      const clientId = document.getElementById('fitbit_client_id').value;
      let url = '/auth/fitbit/login?user_id=' + encodeURIComponent(userId);
      if (clientId) {
        url += '&client_id=' + encodeURIComponent(clientId);
      }
      window.location.href = url;
    }

    async function saveSetup(e) {
      e.preventDefault();
      const btn = document.getElementById('submit-btn');
      btn.disabled = true;
      btn.innerText = 'Initializing Storage & Keys...';

      const provider = document.getElementById('watch_provider').value;
      let useMock = false;
      if (provider === 'garmin') {
        useMock = document.getElementById('use_mock_garmin')?.checked ?? false;
      } else if (provider === 'fitbit') {
        useMock = document.getElementById('use_mock_fitbit')?.checked ?? false;
      } else if (provider === 'google_health') {
        useMock = document.getElementById('use_mock_google')?.checked ?? false;
      }

      const payload = {
        storage_mode: document.querySelector('input[name="storage_mode"]:checked').value,
        user_id: document.getElementById('user_id').value,
        watch_provider: provider,
        embeddings_provider: document.getElementById('embeddings_provider').value,
        embedding_base_url: document.getElementById('embedding_base_url') ? document.getElementById('embedding_base_url').value : null,
        llm_provider: document.getElementById('llm_provider').value,
        llm_base_url: document.getElementById('llm_base_url').value,
        llm_api_key: document.getElementById('llm_api_key').value || null,
        garmin_sso_tokens: document.getElementById('garmin_sso_tokens') ? document.getElementById('garmin_sso_tokens').value : null,
        fitbit_client_id: document.getElementById('fitbit_client_id') ? document.getElementById('fitbit_client_id').value : null,
        fitbit_token_json: document.getElementById('fitbit_token_json') ? document.getElementById('fitbit_token_json').value : null,
        google_client_id: document.getElementById('google_client_id') ? document.getElementById('google_client_id').value : null,
        google_token_json: document.getElementById('google_token_json') ? document.getElementById('google_token_json').value : null,
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
          msg.innerHTML = '<p class="font-bold">✅ System Initialized Successfully!</p>' +
            '<p class="text-xs text-slate-300">Generated API Key: <code class="font-mono bg-slate-900 px-2 py-0.5 rounded text-white">' + data.api_key + '</code></p>' +
            '<p class="text-xs text-slate-300">Storage Engine: <span class="capitalize text-white font-semibold">' + data.storage_mode + '</span></p>' +
            '<a href="/dashboard?user_id=' + encodeURIComponent(payload.user_id) + '" class="inline-block mt-2 text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-semibold px-3 py-1.5 rounded transition">Go to Dashboard →</a>';
          msg.classList.remove('hidden');
          btn.innerText = '✅ Saved';
        } else {
          throw new Error(data.detail || 'Failed to save setup');
        }
      } catch (err) {
        const msg = document.getElementById('status-msg');
        msg.className = 'p-4 rounded-xl text-sm bg-rose-950/80 border border-rose-800 text-rose-300';
        msg.innerText = '❌ Error: ' + err.message;
        msg.classList.remove('hidden');
        btn.disabled = false;
        btn.innerText = 'Retry Setup';
      }
    }

    // Initialize toggle state
    toggleTrackerOptions(document.getElementById('watch_provider').value);
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
        <!-- Athlete Switcher Dropdown -->
        <div class="flex items-center space-x-2 bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5">
          <label for="user-select" class="text-xs font-semibold text-slate-400">Athlete:</label>
          <select id="user-select" onchange="switchAthlete(this.value)" class="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-white font-medium focus:outline-none focus:border-blue-500">
            <option value="{{ATHLETE_ID}}" selected>{{ATHLETE_ID}}</option>
          </select>
        </div>

        <a href="/setup" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold px-3 py-2 rounded-xl transition border border-slate-700">
          ⚙️ Setup
        </a>
        <a href="/docs" target="_blank" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold px-3 py-2 rounded-xl transition border border-slate-700">
          API Docs
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
      <div id="chat-box" class="h-48 overflow-y-auto bg-slate-950/60 border border-slate-800 rounded-xl p-4 space-y-2 text-sm text-slate-300">
        <div class="text-slate-500 text-xs">Coach: "Hello! I have loaded your biometric trends and recent running sessions. Ask me about your recovery, cardiac drift, or workout prescription."</div>
      </div>
      <form onsubmit="sendChatMessage(event)" class="flex space-x-2">
        <input type="text" id="chat-input" placeholder="e.g. Can I perform a VO2max interval workout today based on my HRV?"
               class="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:border-blue-500">
        <button type="submit" id="chat-send-btn" class="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-5 py-2.5 rounded-xl transition">
          Send
        </button>
      </form>
    </div>
  </div>

  <script>
    let currentUserId = "{{ATHLETE_ID}}";
    let physioChart = null;

    // Check for auth callback status
    const authStatus = new URLSearchParams(window.location.search).get('auth');
    if (authStatus) {
      const banner = document.getElementById('oauth-success-banner');
      const text = document.getElementById('oauth-banner-text');
      if (banner && text) {
        banner.classList.remove('hidden');
        if (authStatus === 'google_success') text.innerText = 'Google Health API (Fitbit Air 2026) connected successfully! Biometric telemetry is live.';
        else if (authStatus === 'fitbit_success') text.innerText = 'Fitbit Web API connected successfully! Biometric telemetry is live.';
        else if (authStatus === 'garmin_success') text.innerText = 'Garmin Connect SSO session initialized! Biometric telemetry is live.';
      }
    }

    async function initAthleteSelector() {
      try {
        const res = await fetch('/dashboard/users');
        if (!res.ok) return;
        const data = await res.json();
        const select = document.getElementById('user-select');
        select.innerHTML = '';
        const users = (data.users && data.users.length > 0) ? data.users : [currentUserId];
        users.forEach(function(u) {
          const opt = document.createElement('option');
          opt.value = u;
          opt.innerText = u;
          if (u === currentUserId) opt.selected = true;
          select.appendChild(opt);
        });
      } catch (err) {
        console.error('Failed to load users list:', err);
      }
    }

    function switchAthlete(newUserId) {
      if (!newUserId || newUserId === currentUserId) return;
      currentUserId = newUserId;
      document.getElementById('athlete-badge').innerText = newUserId;
      window.history.replaceState(null, '', '/dashboard?user_id=' + encodeURIComponent(newUserId));
      loadDashboard();
    }

    async function loadDashboard() {
      try {
        const res = await fetch('/dashboard/data?user_id=' + encodeURIComponent(currentUserId));
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        // Update KPIs
        if (data.health_status) {
          document.getElementById('kpi-feeling').innerText = data.health_status.feeling || 'Normal';
        } else {
          document.getElementById('kpi-feeling').innerText = 'Optimal';
        }

        if (data.daily_physiology && data.daily_physiology.length > 0) {
          const latest = data.daily_physiology[0];
          document.getElementById('kpi-rhr').innerText = (latest.resting_heart_rate != null) ? (latest.resting_heart_rate + ' bpm') : '-- bpm';
          document.getElementById('kpi-hrv').innerText = (latest.hrv_rmssd != null && !isNaN(latest.hrv_rmssd)) ? (Math.round(latest.hrv_rmssd) + ' ms') : '-- ms';
          const bbVal = (latest.body_battery_max != null) ? latest.body_battery_max : (latest.body_battery_end_of_day != null ? latest.body_battery_end_of_day : null);
          document.getElementById('kpi-bb').innerText = (bbVal != null) ? (bbVal + ' / 100') : '-- / 100';

          renderPhysioChart(data.daily_physiology.slice().reverse());
        } else {
          document.getElementById('kpi-rhr').innerText = '-- bpm';
          document.getElementById('kpi-hrv').innerText = '-- ms';
          document.getElementById('kpi-bb').innerText = '-- / 100';
          if (physioChart) { physioChart.destroy(); physioChart = null; }
        }

        // Zones
        renderZones(data.profile?.custom_zones || { z1_max: 135, z2_max: 152, z3_max: 165, z4_max: 178 });

        // Activities
        renderActivities(data.activities || []);
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
      }
    }

    function renderZones(zones) {
      const c = document.getElementById('zones-container');
      c.innerHTML = `
        <div class="space-y-1">
          <div class="flex justify-between text-xs font-semibold"><span>Zone 1: Active Recovery</span><span>< ${zones.z1_max} bpm</span></div>
          <div class="w-full bg-slate-800 rounded-full h-2"><div class="bg-sky-400 h-2 rounded-full" style="width: 20%"></div></div>
        </div>
        <div class="space-y-1">
          <div class="flex justify-between text-xs font-semibold"><span>Zone 2: Aerobic Base (AeT)</span><span>${zones.z1_max} - ${zones.z2_max} bpm</span></div>
          <div class="w-full bg-slate-800 rounded-full h-2"><div class="bg-emerald-400 h-2 rounded-full" style="width: 40%"></div></div>
        </div>
        <div class="space-y-1">
          <div class="flex justify-between text-xs font-semibold"><span>Zone 3: Tempo</span><span>${zones.z2_max} - ${zones.z3_max} bpm</span></div>
          <div class="w-full bg-slate-800 rounded-full h-2"><div class="bg-amber-400 h-2 rounded-full" style="width: 60%"></div></div>
        </div>
        <div class="space-y-1">
          <div class="flex justify-between text-xs font-semibold"><span>Zone 4: Sub-Threshold (AnT)</span><span>${zones.z3_max} - ${zones.z4_max} bpm</span></div>
          <div class="w-full bg-slate-800 rounded-full h-2"><div class="bg-orange-500 h-2 rounded-full" style="width: 80%"></div></div>
        </div>
        <div class="space-y-1">
          <div class="flex justify-between text-xs font-semibold"><span>Zone 5: VO2 Max / Anaerobic</span><span>> ${zones.z4_max} bpm</span></div>
          <div class="w-full bg-slate-800 rounded-full h-2"><div class="bg-rose-500 h-2 rounded-full" style="width: 100%"></div></div>
        </div>
      `;
    }

    function renderPhysioChart(seriesData) {
      const dates = seriesData.map(d => (d.date ? String(d.date).substring(5) : ''));
      const rhr = seriesData.map(d => d.resting_heart_rate);
      const hrv = seriesData.map(d => (d.hrv_rmssd != null ? Math.round(d.hrv_rmssd) : null));

      const options = {
        series: [
          { name: 'RHR (bpm)', data: rhr },
          { name: 'HRV RMSSD (ms)', data: hrv }
        ],
        chart: {
          type: 'line',
          height: 250,
          background: 'transparent',
          toolbar: { show: false }
        },
        colors: ['#38bdf8', '#34d399'],
        stroke: { curve: 'smooth', width: 3 },
        theme: { mode: 'dark' },
        xaxis: { categories: dates, labels: { style: { colors: '#94a3b8' } } },
        yaxis: [
          { title: { text: 'RHR (bpm)', style: { color: '#38bdf8' } }, labels: { style: { colors: '#94a3b8' } } },
          { opposite: true, title: { text: 'HRV (ms)', style: { color: '#34d399' } }, labels: { style: { colors: '#94a3b8' } } }
        ],
        grid: { borderColor: '#334155' }
      };

      if (physioChart) {
        physioChart.destroy();
      }
      physioChart = new ApexCharts(document.getElementById('chart-physio'), options);
      physioChart.render();
    }

    function renderActivities(activities) {
      const tbody = document.getElementById('activities-tbody');
      if (!activities || activities.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-slate-500">No activities recorded yet.</td></tr>';
        return;
      }
      tbody.innerHTML = activities.map(function(a) {
        let dateStr = '--';
        if (a.start_time) {
          try {
            dateStr = new Date(a.start_time).toLocaleDateString();
          } catch (e) {
            dateStr = String(a.start_time).substring(0, 10);
          }
        }
        const distKm = ((a.distance_meters || a.distance_m || 0) / 1000).toFixed(2);
        const durMin = Math.round((a.duration_seconds || a.duration_sec || 0) / 60);
        const hr = (a.avg_heart_rate || a.avg_hr) ? Math.round(a.avg_heart_rate || a.avg_hr) + ' bpm' : '--';
        const pwr = (a.avg_power && !isNaN(a.avg_power)) ? Math.round(a.avg_power) + ' W' : (a.aerobic_training_effect != null ? a.aerobic_training_effect : '--');
        const actName = a.activity_name || a.name || 'Training Session';
        const actType = a.activity_type || a.type || 'running';

        return '<tr class="hover:bg-slate-800/40 transition">' +
          '<td class="py-3 font-medium text-slate-300">' + dateStr + '</td>' +
          '<td class="font-medium text-white">' + actName + '</td>' +
          '<td class="capitalize text-slate-400">' + actType + '</td>' +
          '<td>' + distKm + ' km</td>' +
          '<td>' + durMin + ' min</td>' +
          '<td>' + hr + '</td>' +
          '<td>' + pwr + '</td>' +
        '</tr>';
      }).join('');
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
        chatBox.innerHTML += '<div class="text-emerald-400 font-semibold">Coach: <span class="text-slate-200 font-normal">' + reply + '</span></div>';
      } catch (err) {
        chatBox.innerHTML += '<div class="text-rose-400 text-xs">Error communicating with coach: ' + err.message + '</div>';
      } finally {
        btn.disabled = false;
        btn.innerText = 'Send';
        chatBox.scrollTop = chatBox.scrollHeight;
      }
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
    """Recursively replaces float NaN/Inf with None to allow safe JSON serialization."""
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
    """Initializes the chosen storage engine, creates user profile, securely encrypts tokens, and seeds demo data."""
    engine = get_storage_engine(mode="local" if payload.storage_mode == "local" else "gcp")
    vault = get_vault()

    # 1. Initialize or update user profile
    existing_profile = engine.get_user_profile(payload.user_id)
    updated_profile = {
        **existing_profile,
        "user_id": payload.user_id,
        "watch_provider": payload.watch_provider,
        "storage_mode": payload.storage_mode,
        "llm_provider": payload.llm_provider,
        "llm_base_url": payload.llm_base_url,
        "embeddings_provider": payload.embeddings_provider,
        "embedding_base_url": payload.embedding_base_url,
        "setup_completed_at": datetime.now().isoformat(),
    }
    engine.update_user_profile(payload.user_id, updated_profile)

    # 2. Encrypted Vault token persistence
    has_tokens = False

    # A. Garmin SSO Token Paste
    if payload.garmin_sso_tokens:
        try:
            tok = json.loads(payload.garmin_sso_tokens)
            vault.store_tokens("garmin", payload.user_id, tok)

            has_tokens = True
            log.info(f"🔒 Garmin SSO tokens encrypted into vault for '{payload.user_id}'.")
        except Exception as e:
            log.warning(f"Failed to parse garmin_sso_tokens: {e}")

    # B. Fitbit Token JSON Paste
    if payload.fitbit_token_json:
        try:
            tok = json.loads(payload.fitbit_token_json)
            vault.store_tokens("fitbit", payload.user_id, tok)

            has_tokens = True
            log.info(f"🔒 Fitbit tokens encrypted into vault for '{payload.user_id}'.")
        except Exception as e:
            log.warning(f"Failed to parse fitbit_token_json: {e}")

    # C. Google Health Token JSON Paste
    if payload.google_token_json:
        try:
            tok = json.loads(payload.google_token_json)
            vault.store_tokens("google_health", payload.user_id, tok)

            has_tokens = True
            log.info(f"🔒 Google Health tokens encrypted into vault for '{payload.user_id}'.")
        except Exception as e:
            log.warning(f"Failed to parse google_token_json: {e}")

    # 3. Seed mock biometric data if requested or in local-first mock mode without live tokens
    if payload.use_mock_data or (payload.storage_mode == "local" and not has_tokens):
        seed_mock_biometric_data(engine, payload.user_id, provider=payload.watch_provider)

    # 4. Generate initial API key for external agents / CLI
    api_key = engine.create_api_key(payload.user_id, name="initial_setup_key")

    log.info(f"✅ Setup completed successfully for user '{payload.user_id}' with mode '{payload.storage_mode}'")
    return {
        "status": "success",
        "user_id": payload.user_id,
        "storage_mode": payload.storage_mode,
        "api_key": api_key,
        "watch_provider": payload.watch_provider,
    }


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

    effective_client_id = client_id or os.getenv("GOOGLE_HEALTH_CLIENT_ID", "local-client.apps.googleusercontent.com")
    base_url = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto and base_url.startswith("http://") and forwarded_proto == "https":
        base_url = "https://" + base_url[len("http://"):]
    redirect_uri = f"{base_url}/auth/google/callback"

    oauth_client = GoogleHealthOAuthClient(
        client_id=effective_client_id,
        redirect_uri=redirect_uri,
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
        )
        token_data = oauth_client.exchange_code_for_tokens(code, verifier)

        # Encrypt into secure vault
        get_vault().store_tokens("google_health", user_id, token_data)



        # Update user profile in storage
        engine = get_storage_engine()
        existing = engine.get_user_profile(user_id)
        engine.update_user_profile(user_id, {
            **existing,
            "user_id": user_id,
            "watch_provider": "google_health",
            "google_health_connected": True,
            "google_health_connected_at": datetime.now().isoformat(),
        })

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
        base_url = "https://" + base_url[len("http://"):]
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
        engine.update_user_profile(user_id, {
            **existing,
            "user_id": user_id,
            "watch_provider": "fitbit",
            "fitbit_connected": True,
            "fitbit_connected_at": datetime.now().isoformat(),
        })

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
