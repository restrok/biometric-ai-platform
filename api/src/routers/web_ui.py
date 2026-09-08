"""Web UI router providing zero-configuration Setup wizard and dark-mode Dashboard."""

import logging
import math
import os
from datetime import datetime
from typing import Any

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
    watch_provider: str = "garmin"  # "garmin", "fitbit", "google_health"
    fitbit_client_id: str | None = None
    generate_key: bool = True


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
            <option value="fitbit">Fitbit (OAuth2 PKCE / Web API)</option>
            <option value="google_health">Google Health API (Fitbit Air 2026)</option>
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
          <select id="llm_provider" onchange="toggleLlmOptions(this.value)" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500">
            <option value="ollama">Ollama (Local or Cloud Hosted)</option>
            <option value="openrouter">OpenRouter (Cloud API)</option>
            <option value="google">Google Gemini</option>
            <option value="openai">OpenAI Compatible</option>
          </select>
        </div>
      </div>

      <!-- Ollama Configuration Section -->
      <div id="ollama-config-section" class="bg-slate-800/40 border border-slate-700/60 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <label class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Ollama Endpoint Settings</label>
          <span class="text-xs text-slate-400">Local or Cloud Hosted</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label class="block text-xs text-slate-400 mb-1">Base URL</label>
            <input type="text" id="llm_base_url" value="http://localhost:11434/v1" placeholder="https://ollama.com/v1"
                   class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">API Key (Cloud/Remote)</label>
            <input type="password" id="llm_api_key" placeholder="Optional for local, required for cloud"
                   class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
          </div>
        </div>
      </div>

      <div id="status-msg" class="hidden p-4 rounded-xl text-sm"></div>

      <button type="submit" id="submit-btn"
              class="w-full py-3 px-4 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-xl transition duration-150 shadow-lg shadow-blue-600/30">
        Save & Initialize System
      </button>
    </form>
  </div>

  <script>
    function toggleLlmOptions(provider) {
      const sec = document.getElementById('ollama-config-section');
      if (provider === 'ollama' || provider === 'openai') {
        sec.classList.remove('hidden');
      } else {
        sec.classList.add('hidden');
      }
    }

    async function saveSetup(e) {
      e.preventDefault();
      const btn = document.getElementById('submit-btn');
      btn.disabled = true;
      btn.innerText = 'Initializing Storage & Keys...';

      const payload = {
        storage_mode: document.querySelector('input[name="storage_mode"]:checked').value,
        user_id: document.getElementById('user_id').value,
        watch_provider: document.getElementById('watch_provider').value,
        embeddings_provider: document.getElementById('embeddings_provider').value,
        llm_provider: document.getElementById('llm_provider').value,
        llm_base_url: document.getElementById('llm_base_url').value,
        llm_api_key: document.getElementById('llm_api_key').value || null,
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
        <div class="flex items-center space-x-2 bg-slate-900 border border-slate-700/80 rounded-lg px-3 py-1.5">
          <span class="text-xs text-slate-400">Athlete:</span>
          <select id="user-select" class="bg-transparent text-xs font-bold text-white focus:outline-none cursor-pointer" onchange="switchAthlete(this.value)">
            <!-- Options populated dynamically -->
          </select>
        </div>
        <button onclick="refreshData()" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded-lg border border-slate-700 transition flex items-center gap-1">
          <span>🔄</span> Refresh
        </button>
        <a href="/setup" class="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-2 rounded-lg transition flex items-center gap-1">
          <span>⚙️</span> Setup
        </a>
      </div>
    </header>

    <!-- Top KPI Row -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">Subjective Feeling</div>
        <div id="kpi-feeling" class="text-2xl font-bold text-white mt-1 capitalize">--</div>
        <div class="text-xs text-slate-500 mt-1">Self-reported recovery state</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">Resting Heart Rate</div>
        <div id="kpi-rhr" class="text-2xl font-bold text-rose-400 mt-1">-- bpm</div>
        <div class="text-xs text-slate-500 mt-1">Basal morning resting rate</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">HRV RMSSD</div>
        <div id="kpi-hrv" class="text-2xl font-bold text-blue-400 mt-1">-- ms</div>
        <div class="text-xs text-slate-500 mt-1">Autonomic nervous balance</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 p-4 rounded-xl">
        <div class="text-slate-400 text-xs font-medium">Body Battery</div>
        <div id="kpi-bb" class="text-2xl font-bold text-emerald-400 mt-1">-- / 100</div>
        <div class="text-xs text-slate-500 mt-1">End of day energy reserve</div>
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
              <th class="py-2">Session Name</th>
              <th class="py-2">Type</th>
              <th class="py-2">Distance</th>
              <th class="py-2">Duration</th>
              <th class="py-2">Avg HR</th>
              <th class="py-2">Avg Power</th>
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
    let currentUserId = "{{ATHLETE_ID}}";
    let physioChart = null;

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
      const hrv = series.map(function(s) { return (s.hrv_rmssd != null && !isNaN(s.hrv_rmssd)) ? Math.round(s.hrv_rmssd) : null; });

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
        const res = await fetch('/v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-User-ID': currentUserId },
          body: JSON.stringify({
            messages: [{ role: 'user', content: msg }]
          })
        });
        const data = await res.json();
        const reply = data.choices?.[0]?.message?.content || 'No response received.';
        chatBox.innerHTML += '<div class="text-emerald-400 font-semibold">Coach: <span class="text-slate-200 font-normal">' + reply + '</span></div>';
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

    window.onload = async function() {
      const urlParams = new URLSearchParams(window.location.search);
      const urlUser = urlParams.get('user_id');
      if (urlUser) {
        currentUserId = urlUser;
        document.getElementById('athlete-badge').innerText = urlUser;
      }
      await initAthleteSelector();
      await loadDashboard();
    };
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
        "llm_base_url": payload.llm_base_url,
        "embeddings_provider": payload.embeddings_provider,
        "setup_completed_at": datetime.now().isoformat(),
    }
    engine.update_user_profile(payload.user_id, updated_profile)

    # 2. Generate initial API key for external agents / CLI
    api_key = engine.create_api_key(payload.user_id, name="initial_setup_key")

    log.info(f"✅ Setup completed successfully for user '{payload.user_id}' with mode '{payload.storage_mode}'")
    return {
        "status": "success",
        "user_id": payload.user_id,
        "storage_mode": payload.storage_mode,
        "api_key": api_key,
        "watch_provider": payload.watch_provider,
    }


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
