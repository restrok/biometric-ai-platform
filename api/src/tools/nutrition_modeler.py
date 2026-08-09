import json
import logging
import re

from google.cloud import bigquery
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.tools.retriever import retrieve_biometric_data
from src.utils.config import get_config

log = logging.getLogger(__name__)


# Standard Reference Heuristic Dictionary for Meal Macro Estimates
# Format: item_pattern: (est_carbs_g, est_protein_g)
MEAL_MACRO_HEURISTICS = {
    r"pizza": (70.0, 20.0),
    r"tarta": (50.0, 15.0),
    r"empanada": (35.0, 12.0),
    r"spaghetti|fideos|pasta|tallarin": (75.0, 14.0),
    r"arroz|rice": (60.0, 6.0),
    r"papa|patata|potato": (45.0, 4.0),
    r"pan|bread|sandwich": (40.0, 10.0),
    r"asado|carne|steak|vacío|tira": (5.0, 50.0),
    r"pollo|chicken": (0.0, 40.0),
    r"pescado|fish": (0.0, 35.0),
    r"ensalada|salad|verdura": (10.0, 3.0),
    r"guiso|stew": (80.0, 25.0),
    r"calzone": (80.0, 25.0),
    r"fruta|banana|manzana": (30.0, 1.0),
    r"vino|wine|cerveza|alcohol": (10.0, 0.0),
    r"avena|oats": (55.0, 12.0),
    r"huevo|egg": (1.0, 13.0),
}


class GlycogenReadinessInput(BaseModel):
    """Input schema for assessing athlete glycogen readiness."""

    user_id: str = Field(..., description="The internal user ID (mandatory for multi-tenant isolation).")
    target_power_watts: float = Field(300.0, description="Target workout power output in Watts (default 300W).")
    duration_mins: float = Field(20.0, description="Target workout duration in minutes (default 20 mins).")


@tool(args_schema=GlycogenReadinessInput)
def assess_glycogen_readiness(
    user_id: str,
    target_power_watts: float = 300.0,
    duration_mins: float = 20.0,
) -> str:
    """
    Translates recent qualitative natural language nutritional logs from Semantic Memory (last 24-36h)
    into a 3-band stochastic glycogen availability classification (LOW, MODERATE, HIGH).
    Evaluates fueling readiness against target mechanical work (kJ) and predicts efficiency (W/HR).
    """
    config = get_config()
    pid = config["project_id"]
    ds = config["dataset_id"]
    client = bigquery.Client(project=pid)

    try:
        # 1. Retrieve Semantic Memories to find Nutritional Logs
        retriever_data = retrieve_biometric_data.invoke({"user_id": user_id})
        memories: list[str] = retriever_data.get("semantic_memories", [])

        nutritional_logs = []
        for mem in memories:
            mem_lower = mem.lower()
            if any(
                k in mem_lower
                for k in ["nutritional log", "dinner", "lunch", "breakfast", "supper", "comida", "cena", "almuerzo"]
            ):
                nutritional_logs.append(mem)

        # 2. Parse Meals & Estimate Carbs and Protein
        total_carbs_g = 0.0
        total_protein_g = 0.0
        parsed_items = []
        alcohol_flag = False

        for log_text in nutritional_logs:
            log_lower = log_text.lower()
            if "wine" in log_lower or "vino" in log_lower or "alcohol" in log_lower:
                alcohol_flag = True

            for pattern, (carbs, protein) in MEAL_MACRO_HEURISTICS.items():
                if re.search(pattern, log_lower):
                    total_carbs_g += carbs
                    total_protein_g += protein
                    parsed_items.append({"matched_item": pattern, "carbs_g": carbs, "protein_g": protein})

        # Apply stochastic bounds (±15% error margin)
        min_carbs = round(total_carbs_g * 0.85, 1)
        max_carbs = round(total_carbs_g * 1.15, 1)
        est_carbs = round(total_carbs_g, 1)

        # 3. Glycogen Band Classification
        # LOW (< 100g), MODERATE (100g - 250g), HIGH (> 250g)
        if total_carbs_g < 100.0:
            glycogen_band = "LOW"
        elif total_carbs_g <= 250.0:
            glycogen_band = "MODERATE"
        else:
            glycogen_band = "HIGH"

        # 4. Target Mechanical Work & Carbohydrate Burn Calculation
        # Work (kJ) = Power (W) * Duration (sec) / 1000
        target_work_kj = round((target_power_watts * (duration_mins * 60.0)) / 1000.0, 1)
        # Carbohydrate burn proxy: ~0.25g carbs per kJ at threshold/high intensity
        est_carbs_burned_g = round(target_work_kj * 0.25, 1)

        # 5. Query Historical W/HR Efficiency from BigQuery
        query_efficiency = f"""
            SELECT 
                ROUND(AVG(SAFE_DIVIDE(avg_power, NULLIF(avg_hr, 0))), 3) as avg_efficiency_w_hr
            FROM `{pid}.{ds}.recent_activities`
            WHERE user_id = '{user_id}' AND avg_power IS NOT NULL AND avg_hr IS NOT NULL
        """
        eff_rows = list(client.query(query_efficiency).result())
        historical_w_hr = (
            float(eff_rows[0].avg_efficiency_w_hr) if eff_rows and eff_rows[0].avg_efficiency_w_hr else 1.50
        )

        # Efficiency Impact Prediction
        if glycogen_band == "LOW" and target_power_watts >= 250.0:
            predicted_w_hr = round(historical_w_hr * 0.92, 3)
            readiness_status = "UNFAVORABLE"
            fueling_recommendation = (
                f"CRITICAL FUELING DEFICIT: Estimated glycogen availability is LOW ({est_carbs}g carbs). "
                f"Target workout ({target_power_watts}W for {duration_mins}m = {target_work_kj} kJ) requires ~{est_carbs_burned_g}g carbs. "
                f"Predicted W/HR efficiency drop to {predicted_w_hr} W/bpm due to premature cardiac drift. "
                f"RECOMMENDATION: Consume 60-90g fast-acting carbs (gel/banana/sports drink) 45m prior to session or reduce intensity to Zone 2."
            )
        elif glycogen_band == "MODERATE":
            predicted_w_hr = historical_w_hr
            readiness_status = "ACCEPTABLE"
            fueling_recommendation = (
                f"MODERATE FUELING: Glycogen stores are adequate ({est_carbs}g carbs) for base/moderate work. "
                f"For high-intensity {target_power_watts}W work, consider a 30g pre-workout carbohydrate snack."
            )
        else:
            predicted_w_hr = round(historical_w_hr * 1.03, 3)
            readiness_status = "OPTIMAL"
            fueling_recommendation = (
                f"OPTIMAL FUELING: Glycogen stores are HIGH ({est_carbs}g carbs). "
                f"Carbohydrate availability is optimal for high-power ({target_power_watts}W) work. "
                f"Predicted W/HR efficiency at peak ({predicted_w_hr} W/bpm). Maintain hydration."
            )

        if alcohol_flag:
            fueling_recommendation += (
                " WARNING: Recent alcohol consumption detected in log; monitor hydration and autonomic recovery."
            )

        result = {
            "user_id": user_id,
            "target_workout": {
                "power_watts": target_power_watts,
                "duration_mins": duration_mins,
                "work_kj": target_work_kj,
                "est_carbs_needed_g": est_carbs_burned_g,
            },
            "glycogen_readiness": {
                "band": glycogen_band,
                "readiness_status": readiness_status,
                "est_carbs_available_g": est_carbs,
                "stochastic_carb_range_g": [min_carbs, max_carbs],
                "est_protein_available_g": round(total_protein_g, 1),
                "parsed_nutritional_logs_count": len(nutritional_logs),
            },
            "efficiency_projection": {
                "historical_w_hr": historical_w_hr,
                "projected_w_hr": predicted_w_hr,
            },
            "fueling_recommendation": fueling_recommendation,
        }

        log.info(f"✅ Glycogen readiness assessed for {user_id}: Band {glycogen_band}")
        return json.dumps(result, indent=2)

    except Exception as e:
        log.error(f"❌ Failed assessing glycogen readiness: {e}")
        return json.dumps({"error": str(e)})
