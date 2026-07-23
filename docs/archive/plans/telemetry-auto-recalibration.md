# Autonomous Telemetry Recalibration Plan

> **Status:** 🚧 TO DO

## Context
Telemetry signal quality depends on hardware (sensor age/model) and individual physiology. A static window size (e.g., 11s) may become sub-optimal over time.

## Objective
Implement a weekly "Auto-Tune" cycle that ensures the system always operates at the peak signal-to-noise ratio.

## Architecture: The Recalibration Loop
1. **Trigger:** Every Sunday during the Proactive Cycle, or upon detecting a new `hardware_model` in the activities table.
2. **Experiment:** The Data Scientist agent executes the 1s-increment Parameter Sweep (5s to 20s) on the most recent activity.
3. **Selection:** The algorithm identifies the shortest window where `STD < 3.0 bpm`.
4. **Persistence:** The new optimal window size (e.g., `optimal_hr_window_sec: 12`) is saved to the user's Firestore profile.
5. **Dynamic Retrieval:** The `retriever.py` is updated to read this `optimal_hr_window_sec` from the context and inject it into the BigQuery SQL query dynamically.

## Success Metric
- System-wide average Standard Deviation in WORK blocks remains below 3.0 bpm without human intervention.
