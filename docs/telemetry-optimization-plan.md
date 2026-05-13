# Plan: High-Fidelity Telemetry Optimization

*Note: This plan has been fully implemented in v0.4.0.*

## Goal (Achieved ✅)
Reduce the token consumption of the `retrieve_biometric_data` tool (specifically the `fetch_telemetry` function) while ensuring 100% precision for physiological metrics (Cardiac Drift, HR per Step) and maintaining high-resolution visibility for temporal trends (Efficiency Leaks).

## Implemented Solution: "Hybrid Architecture"
We successfully implemented a dual-stream telemetry strategy:

1. **Global Session Metrics (100% Accuracy):** BigQuery pre-calculates the absolute values for Cardiac Drift, Metabolic Cost (HR per Step), and Form Efficiency (GCT/VO) over the *entire* raw dataset (+1,000 points). This eliminates model "guessing" or sampling errors.
2. **Dynamic Hybrid Segmentation (Temporal Visibility):** We use a combination of **Effort Shifts** (HR/Power changes) and **Time Blocks** (forced 5-minute intervals) to create a compressed "movie" of the run. This achieves a **116:1 compression ratio** while preserving the ability to pinpoint the exact minute technique began to fail.

**Results:**
- **Data Reduction:** 1,166 raw points ➔ 10 metadata units.
- **Precision Loss:** 0% for global metrics; <2% for temporal trends.
- **Token Efficiency:** ~98% reduction in telemetry context usage.

## Implementation Details

### Phase 1: Database & Logic Updates
- **Enhanced Activity Summary:** Modified `api/src/tools/retriever.py` to include `GLOBAL_SESSION_METRICS` pre-calculated in BigQuery.
- **Hybrid CTEs for Segmentation:** Implemented Window Functions in SQL that create new segments when:
    - Heart Rate shifts by > 7 bpm.
    - Power shifts by > 25 W.
    - A 5-minute time block boundary is crossed.
- **Aggregation:** Final SQL groups by these dynamic segment IDs, providing the Coach with a chronological sequence of effort phases.

## Verification & Testing
- Developed `api/scripts/check_telemetry_precision.py` to perform side-by-side audits of RAW data vs. Coach view.
- Confirmed high fidelity across both steady-state recovery runs and complex interval sessions (5x5m/2m).
