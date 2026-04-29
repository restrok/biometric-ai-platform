# 💎 Project Instructions

## 🏃 Biometric Platform Context

### Authentication (Garmin)
- The platform uses `garmin-training-toolkit-sdk` for authentication.
- Authentication is browser-based via Playwright to bypass Cloudflare.
- **Dependency Note:** On Linux systems (especially Raspberry Pi/ARM64), Playwright requires manual installation of browsers and system dependencies:
  - `uv run playwright install chromium`
  - `sudo .venv/bin/python3 -m playwright install-deps`
- Tokens are stored at `~/.garminconnect/garmin_tokens.json`.

### Data Retrieval & Analysis
- **Standardized Zones:** Always use the custom zones from `biometric-coach` skill: Z1 (<144), Z2 (144-165), Z3 (166-176), Z4 (177-186), Z5 (>186).
- **Polarized Training:** Strict adherence to 80/20. Avoid Zone 3 (166-176 bpm).
- **Efficiency Analysis:** Use `analyze_activity_efficiency` to calculate Cardiac Drift/Aerobic Decoupling. Decoupling > 5% indicates instability or fatigue.

### Environment & Tools
- Use `.venv/bin/python3` for all tool executions within the `api/` directory.
- BigQuery is the source of truth for all historical biometric context.
