"""Model Context Protocol (MCP) Server for Biometric AI Platform.

Exposes coaching and analytics tools via standardized SSE endpoint.
"""

import logging

from mcp.server.mcpserver import MCPServer

from src.tools.analytics import analyze_activity_efficiency, analyze_activity_stages
from src.tools.etl_tool import sync_biometric_data
from src.tools.historical_biometrics import (
    compare_shoe_biomechanics,
    query_macro_load_history,
)
from src.tools.memory_manager import (
    save_semantic_memory,
)
from src.tools.nutrition_modeler import assess_glycogen_readiness
from src.tools.predictive_modeler import (
    calculate_critical_power_and_w_prime,
    project_training_impact,
)
from src.tools.profile_manager import (
    get_sport_zones,
    log_health_status,
    update_user_zones,
)
from src.tools.research_assistant import search_exercise_science
from src.tools.retriever import retrieve_biometric_data

log = logging.getLogger(__name__)

mcp_server = MCPServer("Biometric AI Coach")


@mcp_server.tool()
def mcp_retrieve_biometric_data(
    user_id: str | None = None,
    limit: int = 5,
    activity_type: str | None = None,
    include_telemetry: bool = False,
) -> str:
    """Retrieves biometric data, current fitness baseline, recent activities, and health status."""
    return str(
        retrieve_biometric_data.invoke(
            {
                "user_id": user_id,
                "limit": limit,
                "activity_type": activity_type,
                "include_telemetry": include_telemetry,
            }
        )
    )


@mcp_server.tool()
def mcp_analyze_activity_efficiency(activity_id: str, user_id: str | None = None) -> str:
    """Calculates advanced running/swimming efficiency metrics, cardiac drift, and biomechanics."""
    return str(analyze_activity_efficiency.invoke({"activity_id": activity_id, "user_id": user_id}))


@mcp_server.tool()
def mcp_analyze_activity_stages(activity_id: str) -> str:
    """Analyzes lap or interval splits for an activity."""
    return str(analyze_activity_stages.invoke({"activity_id": activity_id}))


@mcp_server.tool()
def mcp_query_macro_load_history(user_id: str | None = None, group_by: str = "weekly", limit_months: int = 6) -> str:
    """Aggregates training volume, distance, TRIMP, and session counts."""
    return str(
        query_macro_load_history.invoke(
            {
                "user_id": user_id,
                "group_by": group_by,
                "limit_months": limit_months,
            }
        )
    )


@mcp_server.tool()
def mcp_calculate_critical_power(user_id: str | None = None, days_back: int = 90) -> str:
    """Calculates Critical Power (CP) and W' (anaerobic work capacity) from historical efforts."""
    return str(
        calculate_critical_power_and_w_prime.invoke(
            {
                "user_id": user_id,
                "days_back": days_back,
            }
        )
    )


@mcp_server.tool()
def mcp_project_training_impact(planned_tss: float, user_id: str | None = None) -> str:
    """Simulates acute and chronic training load (CTL/ATL/TSB) for planned workouts."""
    return str(project_training_impact.invoke({"planned_tss": planned_tss, "user_id": user_id}))


@mcp_server.tool()
def mcp_assess_glycogen_readiness(user_id: str | None = None) -> str:
    """Estimates muscle glycogen depletion and carbohydrate replenishment requirements."""
    return str(assess_glycogen_readiness.invoke({"user_id": user_id}))


@mcp_server.tool()
def mcp_compare_shoe_biomechanics(shoe_1: str, shoe_2: str, user_id: str | None = None) -> str:
    """Compares cadence, ground contact time, and efficiency between shoe models."""
    return str(
        compare_shoe_biomechanics.invoke(
            {
                "shoe_1": shoe_1,
                "shoe_2": shoe_2,
                "user_id": user_id,
            }
        )
    )


@mcp_server.tool()
def mcp_search_exercise_science(query: str) -> str:
    """Searches exercise physiology knowledge base using semantic vector search."""
    return str(search_exercise_science.invoke({"query": query}))


@mcp_server.tool()
def mcp_log_health_status(
    feeling: str,
    notes: str | None = None,
    fatigue_level: int | None = None,
    injury_notes: str | None = None,
    status_date: str | None = None,
    user_id: str | None = None,
) -> str:
    """Logs daily subjective health status, fatigue, soreness, and injury status."""
    return str(
        log_health_status.invoke(
            {
                "feeling": feeling,
                "notes": notes,
                "fatigue_level": fatigue_level,
                "injury_notes": injury_notes,
                "status_date": status_date,
                "user_id": user_id,
            }
        )
    )


@mcp_server.tool()
def mcp_update_user_zones(z1_max: int, z2_max: int, z3_max: int, z4_max: int, user_id: str | None = None) -> str:
    """Updates heart rate training zones (Z1 - Z5)."""
    return str(
        update_user_zones.invoke(
            {
                "z1_max": z1_max,
                "z2_max": z2_max,
                "z3_max": z3_max,
                "z4_max": z4_max,
                "user_id": user_id,
            }
        )
    )


@mcp_server.tool()
def mcp_get_sport_zones(sport: str = "running", user_id: str | None = None) -> str:
    """Retrieves sport-specific zones for running, cycling, or swimming."""
    return str(get_sport_zones.invoke({"sport": sport, "user_id": user_id}))


@mcp_server.tool()
def mcp_save_semantic_memory(
    user_id: str,
    memory_type: str,
    memory_text: str,
    source_session_id: str | None = None,
    confidence_score: float = 1.0,
) -> str:
    """Saves user preference, constraint, or coaching memory nugget."""
    return str(
        save_semantic_memory.invoke(
            {
                "user_id": user_id,
                "memory_type": memory_type,
                "memory_text": memory_text,
                "source_session_id": source_session_id,
                "confidence_score": confidence_score,
            }
        )
    )


@mcp_server.tool()
def mcp_sync_biometric_data(user_id: str | None = None, days_back: int = 3) -> str:
    """Triggers biometric sync from configured watch provider (Garmin/Fitbit)."""
    return str(sync_biometric_data.invoke({"user_id": user_id, "days_back": days_back}))
