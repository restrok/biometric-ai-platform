# AGI Health Platform Architecture Plan

## Executive Summary
This document outlines the strategic roadmap to evolve the Biometric AI Platform from a reactive data analyzer into a proactive, multi-agent "General Health AI" (AGI approach). The plan addresses current gaps in training prescription safety, daily life stress monitoring, and structural scalability.

## 1. Holistic Training Prescription (The "Pre-Flight Scan")
**Problem:** The agent currently generates training plans without a mandatory check of the user's global physiological state, leading to potential overtraining.
**Solution:**
*   **System Prompt & Skill Update:** Enforce a strict "Pre-Flight Health Scan" rule in `graph.py` and `SKILL.md`. Before calling `upload_training_plan`, the agent MUST evaluate the Acute:Chronic (A:C) Workload Ratio, recent HRV trend, and the latest subjective health log.
*   **Mandatory Deload:** If A:C Ratio > 1.3 or HRV is "Declining", the system is explicitly forbidden from prescribing high-intensity interval training (HIIT) and must pivot to Zone 1/2 recovery.

## 2. Subjective vs. Objective Correlation
**Problem:** Subjective feelings (fatigue, pain) logged by the user are not mathematically correlated with objective performance metrics in the reports.
**Solution:**
*   **Update `deep_reporting.py`:** Integrate the `df_health` dataframe into the analysis engine.
*   **Correlation Logic:** Cross-reference days with high subjective fatigue (score >= 7) or poor feeling (score <= 4) against spikes in the A:C Ratio or drops in the Efficiency Z-Score.
*   **HTML Dashboard:** Add a dedicated "Subjective Wellness & Fatigue" section to the HTML report to highlight these correlations visually.

## 3. Daily Life Ingestion (24/7 Physiology)
**Problem:** The platform only captures data when the user is running or sleeping. Non-training stress (work, daily movement) is invisible to the Coach, leading to inaccurate recovery models.
**Solution:**
*   **ETL Expansion (`etl_job.py`):** Implement the `get_user_summary` or equivalent Garmin SDK endpoint to fetch "All-Day" metrics.
*   **New BigQuery Table (`daily_physiology`):** Store daily aggregates including:
    *   `resting_heart_rate` (RHR)
    *   `all_day_stress_avg`
    *   `body_battery_end_of_day`
    *   `total_steps`
*   **Integration:** Feed this 24/7 data into the `retrieve_biometric_data` tool so the Coach knows if a "rest day" was actually restful or highly stressful.

## 4. Multi-Agent Specialization (The "Panel of Experts")
**Problem:** A monolithic agent handling SQL, physiological diagnosis, and workout generation is prone to prompt confusion and limits scalability.
**Solution:**
*   **LangGraph Refactor:** Evolve the current workflow into a specialized multi-agent architecture mimicking real-world professionals. We will build the following hyper-specialized sub-agents:

    1.  🛡️ **Injury Prevention Agent**
        *   **Data Sources:** `recent_activities` (A:C ratio, cadence, vertical ratio), `hrv_history`, and `user_health_status` (pain/niggles).
        *   **Mission:** Injury avoidance over performance.
        *   **Superhuman Capability:** Detects microscopic biomechanical asymmetries (e.g., ground contact time drift) and triggers proactive alerts for rest or mobility work before a real injury occurs.
    
    2.  🧬 **Sleep & Circadian Agent**
        *   **Data Sources:** `sleep_history` (REM/Light/Deep phases, duration), `user_health_status`, and activity timestamps.
        *   **Mission:** Optimize rest and circadian rhythm.
        *   **Superhuman Capability:** Cross-references evening workout intensities with sleep latency and REM drops, providing actionable scheduling advice (e.g., "Move high-intensity sessions to the morning").
    
    3.  ⚖️ **Metabolic Nutrition Agent**
        *   **Data Sources:** `latest_activity_telemetry` (HR, Pace), `body_composition`, and `scheduled_workouts` (tomorrow's plan).
        *   **Mission:** Provide dynamic, expenditure-based fueling advice.
        *   **Superhuman Capability:** Calculates exact "Metabolic Cost" of today's session and cross-references it with tomorrow's demand (e.g., "You burned 800kcal today. To fuel tomorrow's 4x800m intervals, consume at least 120g of carbohydrates tonight").
    
    4.  🧠 **Lifestyle Stress Auditor**
        *   **Data Sources:** `hrv_history` (nervous system stress), `daily_physiology` (all-day stress), and subjective logs.
        *   **Mission:** Delineate physical training stress from life stress.
        *   **Superhuman Capability:** Identifies when HRV drops without a corresponding high A:C Ratio, deducing mental/work stress. Intervenes with lifestyle or breathing recommendations rather than altering the running plan.
    
    5.  🔬 **Autonomous Data Scientist (AgentSearch)**
        *   **Data Sources:** The entire BigQuery Data Lake.
        *   **Mission:** Continuous background analysis for hidden correlations (SensorFM AgentSearch concept).
        *   **Superhuman Capability:** Autonomously writes and executes SQL queries to discover novel physiological relationships specific to the user.

*   **Orchestration:** The Telegram orchestrator communicates only with the Head Coach, hiding the complexity of the internal "Classroom" debate.

## 5. Dynamic Calibration & Predictive Modeling
**Problem:** Physiological thresholds (A:C Ratio, HR Zones) are often static or generic, failing to account for individual adaptation and historical failure points.
**Solution:**
*   **Personal Calibration Profile (PCP):** Implement a background task where the `DataScientist` agent audits historical "Failure Events" (e.g., exhaustion, injury) vs. "Adaptation Peaks" (high-volume success). These personal limits (e.g., "Personal Red Line: 1.6 AC Ratio") will be stored in BigQuery metadata.
*   **The "Evidence-Based" Report:** Update the deep reporting engine to include a "Discovery Section" explaining the *why* behind its advice (e.g., "We recommend Zone 2 because your February 2026 data shows that high intensity with an AC ratio > 1.5 leads to systemic collapse").
*   **Predictive Load Modeler:** Create a new tool (`project_training_impact`) that allows the Coach to simulate the impact of a proposed workout.
    *   *User:* "What if I do a 20k trail run tomorrow?"
    *   *Coach:* "If you perform that session, your A:C Ratio will hit **1.62**, entering your personal **Red Zone**. I suggest shortening it to 12k to stay at 1.45."
*   **Dynamic HR Zone Refining:** Use `AgentSearch` to cross-reference HR Zones with Aerobic Decoupling (Drift). If a user maintains 162 bpm with 0% drift over 90 mins, the system autonomously reclassifies that intensity as "Personal Zone 2" even if standard formulas say it's Zone 3.

## Phased Implementation Strategy
*   **Phase 1: (Completed ✅)** Implement Subjective Correlation and the Pre-Flight Scan (Section 1 & 2).
*   **Phase 2: (Completed ✅)** Develop Daily Life Ingestion (Section 3) and the **Personal Calibration Profile** (Section 5).
*   **Phase 3: (Current Focus 🚧)** Implement the **Predictive Modeler** and gradually refactor the LangGraph architecture (Section 4 & 5).