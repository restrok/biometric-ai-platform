import asyncio
import os
import sys

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import HumanMessage

from src.agent.graph import node_injury_prevention, node_metabolic_nutrition, node_sleep_recovery


async def test_agent():
    # Mock state with a mix of poor sleep, high load, and ectomorph profile
    state = {
        "messages": [
            HumanMessage(
                content="Ayer corrí 10k fuerte. ¿Qué debería comer hoy para recuperar bien y cómo estoy para entrenar?"
            )
        ],
        "biometric_context": {
            "recent_activities": [
                {
                    "id": "12345",
                    "date": "2026-05-23",
                    "distance_m": 10000,
                    "avg_hr": 170,  # High intensity
                    "duration_sec": 3000,
                    "hr_per_step": 1.05,  # High metabolic cost
                }
            ],
            "hrv": [{"date": "2026-05-24", "avg_hrv": 34.0, "baseline_low": 38.0, "status": "UNBALANCED"}],
            "sleep": {
                "date": "2026-05-24",
                "duration_sec": 23400,  # 6.5 hours
                "quality": 60,
                "deep_sec": 2800,
                "rem_sec": 3200,
                "light_sec": 17400,
            },
            "daily_physiology_7d": [
                {"date": "2026-05-24", "resting_heart_rate": 64},
                {"date": "2026-05-23", "resting_heart_rate": 59},
            ],
            "personal_calibration_profile": [{"marker_type": "ac_ratio_red_line", "marker_value": 1.45}],
            "training_status": {"acute_load": "42.0", "chronic_load": "25.0", "status": "Overreaching"},
            "latest_health_status": {
                "feeling": "Tired",
                "notes": "Physiological Profile: Ectomorph. Needs high calorie/carb intake.",
            },
        },
        "user_id": "fsirio",
        "intent": "full",
        "loop_count": 0,
        "usage_stats": {},
    }

    print("🧪 Running Injury Prevention Agent Node...")
    injury_result = node_injury_prevention(state)
    state["messages"] = list(state["messages"]) + list(injury_result["messages"])
    print(injury_result["messages"][0].content)

    print("\n🧬 Running Sleep & Circadian Agent Node...")
    sleep_result = node_sleep_recovery(state)
    state["messages"] = list(state["messages"]) + list(sleep_result["messages"])
    print(sleep_result["messages"][0].content)

    print("\n⚖️ Running Metabolic Nutrition Agent Node...")
    nutrition_result = node_metabolic_nutrition(state)
    print(nutrition_result["messages"][0].content)


if __name__ == "__main__":
    asyncio.run(test_agent())
