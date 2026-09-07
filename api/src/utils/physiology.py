"""Physiological calculation utilities and calibration schemas for load and recovery analysis."""

from typing import Any

from pydantic import BaseModel, Field

# Centralized physiological default thresholds and fallbacks
DEFAULT_AC_RATIO_RED_LINE = 1.3
DEFAULT_HRV_SENSITIVITY = 1.0
DEFAULT_HRV_UNBALANCED_MULTIPLIER = 1.2
DEFAULT_PACE_FALLBACK = 3.0  # m/s
DEFAULT_Z2_MAX_FALLBACK = 165
DEFAULT_POWER_THRESHOLD = 180

# Load risk thresholds
AC_RATIO_HIGH_RISK_LIMIT = 1.3
AC_RATIO_MODERATE_RISK_LIMIT = 1.1
AC_RATIO_ALERT_LIMIT = 1.2

# Z-Score limits for reports
Z_SCORE_ANOMALY_HIGH = 1.5
Z_SCORE_ANOMALY_LOW = -1.5
Z_SCORE_FATIGUE_LIMIT = -1.0


class UserCalibrationProfile(BaseModel):
    """Pydantic model representing a structured physiological calibration profile.

    Supports custom defaults and optional values to handle cold starts (new users) gracefully.
    """

    ac_ratio_red_line: float = Field(
        DEFAULT_AC_RATIO_RED_LINE,
        description="Personal Acute:Chronic Workload Ratio red line limit.",
    )
    hrv_sensitivity_index: float = Field(
        DEFAULT_HRV_SENSITIVITY,
        description="Sensitivity index for HRV drop risk adjustment.",
    )
    hrv_unbalanced_risk_multiplier: float = Field(
        DEFAULT_HRV_UNBALANCED_MULTIPLIER,
        description="Risk multiplier applied when HRV status is unbalanced.",
    )
    gct_drift_baseline: float = Field(
        30.0,
        description="Average Ground Contact Time (GCT) drift observed in steady Zone 2 runs.",
    )
    aerobic_decoupling_threshold: float = Field(
        0.05,
        description="Aerobic decoupling stability threshold.",
    )

    # Advanced Calibration Markers (Optional or with safe defaults for new users)
    hrv_unbalanced_warning_limit: float | None = Field(
        None,
        description="HRV warning limit in ms below which training must be reduced.",
    )
    rhr_illness_spike_precursor: float = Field(
        5.0,
        description="RHR increase in bpm above 7d average indicating potential illness/infection.",
    )
    vertical_oscillation_fatigue_index: float = Field(
        1.10,
        description="Vertical oscillation drift index under mechanical fatigue.",
    )
    bb_hrv_correlation: float | None = Field(
        None,
        description="Correlation coefficient between Body Battery and HRV metrics.",
    )
    stress_gct_correlation: float | None = Field(
        None,
        description="Correlation coefficient between daily stress and GCT metrics.",
    )
    z2_aerobic_stability: float = Field(
        0.05,
        description="Baseline aerobic stability decoupling metric.",
    )
    nutritional_efficiency_gain: float | None = Field(
        None,
        description="Metric representing metabolic/nutritional fueling efficiency.",
    )
    hrv_gct_fatigue_coupling: float | None = Field(
        None,
        description="Coupling ratio between GCT drift and HRV autonomic drop.",
    )
    ans_resilience_index: float = Field(
        1.0,
        description="Autonomic Nervous System resilience index.",
    )
    acute_work_kj_red_line: float | None = Field(
        None,
        description="Acute workload red line in kJ.",
    )
    acute_trimp_min_red_line: float | None = Field(
        None,
        description="Acute workload red line in TRIMP minutes.",
    )
    acute_km_red_line: float | None = Field(
        None,
        description="Acute workload red line in kilometers.",
    )

    @classmethod
    def from_db_rows(cls, rows: list[Any]) -> "UserCalibrationProfile":
        """Loads and parses a list of calibration rows/dictionaries into a validated profile."""
        data = {}
        for r in rows:
            m_type = getattr(r, "marker_type", None)
            m_val = getattr(r, "marker_value", None)

            if m_type is None and isinstance(r, dict):
                m_type = r.get("marker_type")
                m_val = r.get("marker_value")

            if m_type and m_val is not None:
                if m_type in cls.model_fields:
                    data[m_type] = float(m_val)
                elif m_type == "ac_ratio_red_line":
                    data["ac_ratio_red_line"] = float(m_val)
                elif m_type == "hrv_sensitivity_index":
                    data["hrv_sensitivity_index"] = float(m_val)
                elif m_type == "hrv_unbalanced_risk_multiplier":
                    data["hrv_unbalanced_risk_multiplier"] = float(m_val)
        return cls(**data)


class SportHeartRateZones(BaseModel):
    """Heart rate zone thresholds for a specific sport discipline."""

    sport: str = Field("running", description="Sport discipline: 'running', 'swimming', 'cycling'")
    z1_max: int = Field(..., description="Max HR for Zone 1 (Active Recovery)")
    z2_max: int = Field(..., description="Max HR for Zone 2 (Aerobic Threshold / AeT)")
    z3_max: int = Field(..., description="Max HR for Zone 3 (Tempo / Aerobic Power)")
    z4_max: int = Field(..., description="Max HR for Zone 4 (Anaerobic / Lactate Threshold / AnT)")
    z5_max: int | None = Field(None, description="Max HR for Zone 5 (VO2 Max / Neuromuscular Peak)")
    aet_hr: int | None = Field(None, description="Aerobic Threshold (AeT) in bpm")
    ant_hr: int | None = Field(None, description="Anaerobic Threshold (AnT) in bpm")
    hr_offset_from_running_bpm: int = Field(
        0, description="Offset in bpm relative to running baseline (e.g. -13 bpm for swimming)"
    )


def calculate_sport_hr_zones(
    running_zones: dict[str, Any] | None = None,
    max_hr: float | None = None,
    resting_hr: float | None = None,
    sport: str = "running",
) -> SportHeartRateZones:
    """
    Computes sport-specific heart rate zones (running, swimming, cycling).

    Physiological Rationale:
    - Running: Vertical posture with full gravitational load on the cardiovascular system.
    - Swimming: Horizontal body position increases venous return and stroke volume (Frank-Starling law),
      while water immersion provides convective cooling. As a result, swimming AeT, AnT, and Max HR
      are typically 10 to 15 bpm lower (average ~13 bpm) than running.
    - Cycling: Seated posture without upper body vertical impact reduces HR by 5 to 8 bpm relative to running.
    """
    sport_lower = sport.lower()

    # 1. Base Running Zones Resolution
    if running_zones and all(k in running_zones for k in ["z1_max", "z2_max", "z3_max", "z4_max"]):
        r_z1 = int(running_zones["z1_max"])
        r_z2 = int(running_zones["z2_max"])
        r_z3 = int(running_zones["z3_max"])
        r_z4 = int(running_zones["z4_max"])
        r_z5 = int(running_zones.get("z5_max", max_hr or (r_z4 + 15)))
    else:
        # Fallback to Karvonen calculation from Max HR / Resting HR
        m_hr = float(max_hr or 180.0)
        r_hr = float(resting_hr or 60.0)
        hrr = m_hr - r_hr
        r_z1 = int(round(r_hr + 0.50 * hrr))
        r_z2 = int(round(r_hr + 0.60 * hrr))
        r_z3 = int(round(r_hr + 0.70 * hrr))
        r_z4 = int(round(r_hr + 0.80 * hrr))
        r_z5 = int(round(m_hr))

    if sport_lower in ("swimming", "lap_swimming", "pool_swimming", "open_water_swimming"):
        # Swimming offset: ~12-14 bpm lower
        offset = -13
        z1 = max(r_z1 + offset, 80)
        z2 = max(r_z2 + offset, 105)
        z3 = max(r_z3 + offset, 120)
        z4 = max(r_z4 + offset, 135)
        z5 = max(r_z5 + offset, 150) if r_z5 else None
        return SportHeartRateZones(
            sport="swimming",
            z1_max=z1,
            z2_max=z2,
            z3_max=z3,
            z4_max=z4,
            z5_max=z5,
            aet_hr=z2,
            ant_hr=z4,
            hr_offset_from_running_bpm=offset,
        )
    if sport_lower in ("cycling", "biking", "indoor_cycling"):
        # Cycling offset: ~6 bpm lower
        offset = -6
        return SportHeartRateZones(
            sport="cycling",
            z1_max=r_z1 + offset,
            z2_max=r_z2 + offset,
            z3_max=r_z3 + offset,
            z4_max=r_z4 + offset,
            z5_max=r_z5 + offset if r_z5 else None,
            aet_hr=r_z2 + offset,
            ant_hr=r_z4 + offset,
            hr_offset_from_running_bpm=offset,
        )
    # Default: Running
    return SportHeartRateZones(
        sport="running",
        z1_max=r_z1,
        z2_max=r_z2,
        z3_max=r_z3,
        z4_max=r_z4,
        z5_max=r_z5,
        aet_hr=r_z2,
        ant_hr=r_z4,
        hr_offset_from_running_bpm=0,
    )
