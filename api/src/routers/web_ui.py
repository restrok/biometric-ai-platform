"""Web UI Router providing /setup (Onboarding Wizard) and /dashboard (Visual Biometric Analytics)."""

import logging
import os
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.storage.factory import get_storage_engine

log = logging.getLogger(__name__)

router = APIRouter(tags=["Web UI"])


class SetupConfigPayload(BaseModel):
    storage_mode: str = "local"  # "local" or "gcp"
    user_id: str = "athlete_1"
    llm_provider: str = "ollama"  # "ollama", "openrouter", "google", "openai"
    llm_model: str = "gemma-4-31b-it"
    llm_base_url: str | None = "http://localhost:11434/v1"
    llm_api_key: str | None = None
    embeddings_provider: str = "fastembed"  # "fastembed", "ollama", "google"
    watch_provider: str = "garmin"  # "garmin", "fitbit"
    fitbit_client_id: str | None = None
    generate_key: bool = True


SETUP_HTML = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Biometric AI Platform - Setup Wizard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: { 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8' }
          }
        }
      }
    }
  </script>
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
            <span class="text-xs text-slate-400 mt-1">100% private. Uses DuckDB + SQLite. Zero GCP costs or cloud accounts.</span>
          </label>
          <label class="cursor-pointer border border-slate-700 rounded-xl p-4 flex flex-col items-start bg-slate-800/50 hover:border-blue-500 transition">
            <input type="radio" name="storage_mode" value="gcp" class="text-blue-600 mb-2">
            <span class="font-bold text-white">Google Cloud (GCP)</span>
            <span class="text-xs text-slate-400 mt-1">Cloud-native enterprise lake. Uses BigQuery + Firestore.</span>
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
          <select id="watch_provider" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
            <option value="garmin">Garmin Connect (FIT / Telemetry)</option>
            <option value="fitbit">Fitbit (OAuth2 PKCE / Intraday)</option>
          </select>
        </div>
      </div>

      <!-- Embeddings & LLM -->
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-slate-300">4. Local Embeddings</label>
          <select id="embeddings_provider" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
            <option value="fastembed">FastEmbed (ONNX, CPU/ARM, 0 GPU)</option>
            <option value="ollama">Ollama (nomic-embed-text)</option>
            <option value="google">Google Gemini Embeddings</option>
          </select>
        </div>
        <div class="space-y-2">
          <label class="block text-sm font-semibold text-slate-300">5. Reasoning LLM Engine</label>
          <select id="llm_provider" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
            <option value="ollama">Ollama (Local inference)</option>
            <option value="openrouter">OpenRouter (Cloud API)</option>
            <option value="google">Google Gemini</option>
          </select>
        </div>
      </div>

      <!-- API Key Generation & Protection -->
      <div class="bg-slate-800/60 border border-slate-700/80 rounded-xl p-4 space-y-2">
        <div class="flex justify-between items-center">
          <span class="text-sm font-semibold text-slate-200">Security & Access Key</span>
          <span class="text-xs bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded">Multi-Tenant Secured</span>
        </div>
        <p class="text-xs text-slate-400">A high-entropy API key will be generated for your athlete profile to authenticate REST & MCP connections.</p>
        <div id="key-display" class="hidden font-mono text-xs bg-slate-950 p-2.5 rounded border border-emerald-600/50 text-emerald-400 break-all select-all"></div>
      </div>

      <button type="submit" id="submit-btn"
              class="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold py-3 px-4 rounded-xl transition duration-200 shadow-lg shadow-blue-600/30 flex items-center justify-center space-x-2">
        <span>🚀 Complete Setup & Launch Platform</span>
      </button>
    </form>

    <div id="status-msg" class="hidden p-4 rounded-xl text-sm"></div>
    <div class="text-center pt-2">
      <a href="/dashboard" class="text-xs text-slate-400 hover:text-blue-400 underline">Skip to Live Dashboard →</a>
    </div>
  </div>

  <script>
    async function saveSetup(e) {
      e.preventDefault();
      const btn = document.getElementById('submit-btn');
      btn.disabled = true;
      btn.innerText = 'Saving configuration...';

      const storageMode = document.querySelector('input[name="storage_mode"]:checked').value;
      const payload = {
        storage_mode: storageMode,
        user_id: document.getElementById('user_id').value,
        watch_provider: document.getElementById('watch_provider').value,
        embeddings_provider: document.getElementById('embeddings_provider').value,
        llm_provider: document.getElementById('llm_provider').value,
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
          const keyBox = document.getElementById('key-display');
          keyBox.innerText = 'API Key: ' + data.api_key + '\\n(Keep this safe! Pass in X-API-Key header)';
          keyBox.classList.remove('hidden');

          const msg = document.getElementById('status-msg');
          msg.className = 'p-4 rounded-xl text-sm bg-emerald-950/80 border border-emerald-800 text-emerald-300';
          msg.innerHTML = '✅ Setup successful! Environment initialized in <b>' + storageMode.toUpperCase() + '</b> mode.<br><a href="/dashboard?user_id=' + payload.user_id + '" class="underline font-bold text-white mt-2 inline-block">Go to Dashboard →</a>';
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
    <header class="flex justify-between items-center border-b border-slate-800 pb-4">
      <div class="flex items-center space-x-3">
        <span class="text-3xl">🏃‍♂️</span>
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white">Biometric AI Coach</h1>
          <p class="text-xs text-slate-400">Athlete: <span id="athlete-badge" class="font-mono text-blue-400">{{ATHLETE_ID}}</span></p>
        </div>
      </div>
      <div class="flex items-center space-x-3">
        <button onclick="refreshData()" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded-lg border border-slate-700 transition">
          🔄 Refresh
        </button>
        <a href="/setup" class="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-2 rounded-lg transition">
          ⚙️ Setup
        </a>
      </div>
    </header>

    <!-- Top KPI Row -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-xl">
        <div class="text-xs text-slate-400">Resting Heart Rate</div>
        <div id="kpi-rhr" class="text-2xl font-bold text-white mt-1">-- bpm</div>
        <div class="text-xs text-emerald-400 mt-1">Daily average</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-xl">
        <div class="text-xs text-slate-400">HRV (RMSSD)</div>
        <div id="kpi-hrv" class="text-2xl font-bold text-white mt-1">-- ms</div>
        <div class="text-xs text-blue-400 mt-1">Overnight baseline</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-xl">
        <div class="text-xs text-slate-400">Body Battery</div>
        <div id="kpi-bb" class="text-2xl font-bold text-white mt-1">-- / 100</div>
        <div class="text-xs text-emerald-400 mt-1">Current readiness</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-xl">
        <div class="text-xs text-slate-400">Subjective Feeling</div>
        <div id="kpi-feeling" class="text-2xl font-bold text-white mt-1">Normal</div>
        <div id="kpi-fatigue" class="text-xs text-amber-400 mt-1">Fatigue: -- / 10</div>
      </div>
    </div>

    <!-- Charts Row -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Physiological Trends -->
      <div class="bg-slate-900 border border-slate-800 p-5 rounded-xl">
        <h2 class="text-sm font-semibold text-slate-300 mb-4">Physiological Trends (RHR & HRV)</h2>
        <div id="chart-physio" class="h-64"></div>
      </div>
      <!-- Heart Rate Zones -->
      <div class="bg-slate-900 border border-slate-800 p-5 rounded-xl">
        <h2 class="text-sm font-semibold text-slate-300 mb-4">Heart Rate Zones (BPM)</h2>
        <div id="zones-container" class="space-y-3 pt-2">
          <!-- Populated dynamically -->
        </div>
      </div>
    </div>

    <!-- Recent Activities Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
      <div class="flex justify-between items-center">
        <h2 class="text-sm font-semibold text-slate-300">Recent Sessions & Telemetry</h2>
        <span class="text-xs text-slate-500">Last 10 activities</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead class="text-slate-400 border-b border-slate-800 uppercase tracking-wider">
            <tr>
              <th class="py-2">Date / Time</th>
              <th class="py-2">Type</th>
              <th class="py-2">Distance</th>
              <th class="py-2">Duration</th>
              <th class="py-2">Avg HR</th>
              <th class="py-2">Training Effect</th>
              <th class="py-2">TRIMP</th>
            </tr>
          </thead>
          <tbody id="activities-tbody" class="divide-y divide-slate-800/60 text-slate-200">
            <tr><td colspan="7" class="py-4 text-center text-slate-500">Loading activities...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Interactive AI Coach Chat -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
      <div class="flex items-center space-x-2">
        <span class="text-xl">🤖</span>
        <h2 class="text-sm font-semibold text-slate-300">Ask Your Biometric AI Coach</h2>
      </div>
      <div id="chat-box" class="h-48 overflow-y-auto bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3 text-xs">
        <div class="text-slate-400">Coach: Hello! I have analyzed your recent biometric data. How can I help with your training today?</div>
      </div>
      <form class="flex space-x-2" onsubmit="sendChatMessage(event)">
        <input type="text" id="chat-input" placeholder="e.g. Can I do tempo intervals today given my HRV?"
               class="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500">
        <button type="submit" id="chat-send-btn" class="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-xs font-semibold transition">
          Send
        </button>
      </form>
    </div>
  </div>

  <script>
    const USER_ID = "{{ATHLETE_ID}}";
    let physioChart = null;

    async function loadDashboard() {
      try {
        const res = await fetch('/dashboard/data?user_id=' + USER_ID);
        const data = await res.json();

        // Update KPIs
        if (data.health_status) {
          document.getElementById('kpi-feeling').innerText = data.health_status.feeling || 'Normal';
          document.getElementById('kpi-fatigue').innerText = 'Fatigue: ' + (data.health_status.fatigue_level ?? '--') + ' / 10';
        }

        if (data.daily_physiology && data.daily_physiology.length > 0) {
          const latest = data.daily_physiology[0];
          document.getElementById('kpi-rhr').innerText = latest.resting_heart_rate ? (latest.resting_heart_rate + ' bpm') : '-- bpm';
          document.getElementById('kpi-hrv').innerText = latest.hrv_rmssd ? (Math.round(latest.hrv_rmssd) + ' ms') : '-- ms';
          document.getElementById('kpi-bb').innerText = latest.body_battery_max ? (latest.body_battery_max + ' / 100') : '-- / 100';

          renderPhysioChart(data.daily_physiology.slice().reverse());
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
      const zContainer = document.getElementById('zones-container');
      const zoneDefs = [
        { name: 'Zone 1 - Recovery', max: zones.z1_max || 135, color: 'bg-blue-500' },
        { name: 'Zone 2 - Aerobic Base', max: zones.z2_max || 152, color: 'bg-emerald-500' },
        { name: 'Zone 3 - Tempo', max: zones.z3_max || 165, color: 'bg-amber-500' },
        { name: 'Zone 4 - Threshold', max: zones.z4_max || 178, color: 'bg-orange-500' },
        { name: 'Zone 5 - Anaerobic', max: 'Max', color: 'bg-rose-500' }
      ];
      zContainer.innerHTML = zoneDefs.map(function(z) {
        return '<div>' +
          '<div class="flex justify-between text-xs mb-1">' +
            '<span class="text-slate-300 font-medium">' + z.name + '</span>' +
            '<span class="font-mono text-slate-400">< ' + z.max + ' bpm</span>' +
          '</div>' +
          '<div class="w-full bg-slate-800 rounded-full h-2">' +
            '<div class="' + z.color + ' h-2 rounded-full" style="width: 100%"></div>' +
          '</div>' +
        '</div>';
      }).join('');
    }

    function renderPhysioChart(series) {
      const dates = series.map(function(s) { return s.date; });
      const rhr = series.map(function(s) { return s.resting_heart_rate; });
      const hrv = series.map(function(s) { return s.hrv_rmssd; });

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
      tbody.innerHTML = activities.map(function(a) {
        return '<tr class="hover:bg-slate-800/40 transition">' +
          '<td class="py-3 font-medium">' + new Date(a.start_time).toLocaleDateString() + '</td>' +
          '<td class="capitalize">' + (a.activity_type || 'Run') + '</td>' +
          '<td>' + (((a.distance_meters || 0) / 1000).toFixed(2)) + ' km</td>' +
          '<td>' + Math.round((a.duration_seconds || 0) / 60) + ' min</td>' +
          '<td>' + Math.round(a.avg_heart_rate || 0) + ' bpm</td>' +
          '<td>' + (a.aerobic_training_effect || '--') + '</td>' +
          '<td>' + Math.round(a.trimp || 0) + '</td>' +
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
        const res = await fetch('/v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-User-ID': USER_ID },
          body: JSON.stringify({
            messages: [{ role: 'user', content: msg }]
          })
        });
        const data = await res.json();
        const reply = data.choices?.[0]?.message?.content || 'No response';
        chatBox.innerHTML += '<div class="text-emerald-400 font-semibold">Coach: <span class="text-slate-200 font-normal">' + reply.replace(/\\n/g, '<br>') + '</span></div>';
      } catch (err) {
        chatBox.innerHTML += '<div class="text-rose-400">Error: Could not reach coach API.</div>';
      } finally {
        btn.disabled = false;
        btn.innerText = 'Send';
        chatBox.scrollTop = chatBox.scrollHeight;
      }
    }

    function refreshData() {
      loadDashboard();
    }

    window.onload = loadDashboard;
  </script>
</body>
</html>
"""


@router.get("/setup", response_class=HTMLResponse)
async def setup_page():
    """Renders the single-port onboarding setup wizard."""
    return HTMLResponse(content=SETUP_HTML)


@router.post("/setup/save")
async def save_setup(payload: SetupConfigPayload):
    """Initializes the chosen storage engine and creates the user profile and API key."""
    engine = get_storage_engine(mode="local" if payload.storage_mode == "local" else "gcp")

    # 1. Initialize or update user profile
    existing_profile = engine.get_user_profile(payload.user_id)
    updated_profile = {
        **existing_profile,
        "user_id": payload.user_id,
        "watch_provider": payload.watch_provider,
        "storage_mode": payload.storage_mode,
        "llm_provider": payload.llm_provider,
        "embeddings_provider": payload.embeddings_provider,
        "setup_completed_at": datetime.now().isoformat(),
    }
    engine.update_user_profile(payload.user_id, updated_profile)

    # 2. Generate API Key
    api_key = engine.create_api_key(payload.user_id, name="initial_setup")

    return {
        "status": "success",
        "user_id": payload.user_id,
        "storage_mode": payload.storage_mode,
        "api_key": api_key,
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(user_id: str | None = None):
    """Renders the visual biometric dashboard with ApexCharts and Tailwind CSS."""
    default_user = str(user_id or os.getenv("DEFAULT_USER_ID", "default_user"))
    content = DASHBOARD_HTML_TEMPLATE.replace("{{ATHLETE_ID}}", default_user)
    return HTMLResponse(content=content)


@router.get("/dashboard/data")
async def dashboard_data(user_id: str | None = None):
    """Returns biometric summary JSON payload for the dashboard."""
    target_user = str(user_id or os.getenv("DEFAULT_USER_ID", "default_user"))
    engine = get_storage_engine()

    profile = engine.get_user_profile(target_user)
    health_status = engine.get_health_status(target_user)
    goals = engine.get_user_goals(target_user)
    daily_physio = engine.get_daily_physiology(target_user, days=14)
    recent_acts = engine.get_recent_activities(target_user, limit=10)

    return {
        "user_id": target_user,
        "profile": profile,
        "health_status": health_status,
        "goals": goals,
        "daily_physiology": daily_physio,
        "activities": recent_acts,
    }
