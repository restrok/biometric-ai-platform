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
