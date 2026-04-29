# Plan: High-Fidelity Telemetry Optimization

*Note: This plan is saved in the root repository for tomorrow's implementation.*

## Goal
Reduce the token consumption of the `retrieve_biometric_data` tool (specifically the `fetch_telemetry` function) without losing the high-resolution data necessary for the Biometric Coach to identify physiological trends like cardiac drift or form breakdown.

## Problem Analysis
Currently, `fetch_telemetry` samples data every minute (`MOD(timestamp_ms, 60000) < 2000`), resulting in up to 120 data points for a 2-hour run. While replacing this with simple quartiles (Q1, Q2, Q3, Q4) reduces token usage by ~75%, it completely masks acute physiological events (e.g., a sudden 5-minute spike in heart rate on a hill, or progressive mechanical fatigue). The LLM loses the "texture" of the workout.

## Proposed Solution: "Dynamic Effort Segmentation" + "Pre-Calculated Precision"
To address the concern about losing precision (like Aerobic Decoupling), we will split the problem into two parts:

1. **Pre-Calculated Precision:** The LLM is bad at doing math on raw text arrays anyway. BigQuery is perfect at it. We will have BigQuery calculate the exact Aerobic Decoupling, Efficiency Factor, and average stats for the entire run, and return them as top-level numbers in the activity summary. The Coach will have the *exact* mathematical decoupling without needing to guess.
2. **Dynamic Segmentation (The 'Story' of the run):** Instead of static slicing, we will use BigQuery's advanced Window Functions (`LAG` and `LEAD`) to detect statistically significant shifts in effort. If you run steady for 40 minutes, it's one row. If you do intervals, it breaks them out. This gives the Coach the "story" or structure of the workout with extreme token efficiency.

**Why this is brilliant:**
- **Zero Loss of Precision:** The Coach still gets the exact Decoupling (-2.14%) and Efficiency scores calculated directly on the raw, second-by-second data in BigQuery.
- **Extreme Token Efficiency:** A 2-hour steady run becomes 3 or 4 textual segments (Warmup, Steady State, Cooldown). A complex interval workout becomes exactly as many segments as there are intervals.

## Implementation Steps

### Phase 0: Baseline Generation (Quality Assurance)
1. **Establish Baseline:** Before modifying any code, run a complex query through the current agent (e.g., "Analyze my longest run in April. Break down my form and decoupling in detail.") using the CLI or the `/chat` endpoint.
2. **Record Output:** Save the agent's exact text response and the `total_tokens` consumed to a temporary file (e.g., `docs/benchmarks/baseline-telemetry.md`). This guarantees we have a ground-truth sample of the coach's current high-quality analysis.

### Phase 1: Database & Logic Updates
3. **Enhance Activity Summary:** Modify `api/src/tools/retriever.py` -> `fetch_activities` to explicitly suggest using `analyze_activity_efficiency` for precise math like Decoupling.
4. **Implement CTEs for Segmentation:** In `fetch_telemetry`, use a CTE (Common Table Expression) that calculates minute-by-minute averages.
5. Add a second CTE using `LAG()` to calculate the delta (change) in HR or Power from the previous minute.
6. Add a third CTE that assigns a `segment_id` which increments only when the delta exceeds a threshold (e.g., HR changes by >7 bpm or Power by >20W).
7. The final `SELECT` groups by `segment_id`, calculating the total duration (start to end time), average HR, Power, and Oscillation for each dynamic phase of the run.
8. Format the output for the LLM as a concise list of distinct effort phases (e.g., `Segment 1 (15m): 140bpm, 190W`).

### Phase 2: Evaluation
9. **Run Comparison:** Execute the exact same prompt from Phase 0 against the updated agent.
10. **Validate Quality:** Compare the new response against `baseline-telemetry.md`. Confirm that the physiological insights (Decoupling, Fatigue) are identical or better, while verifying the input token usage dropped by at least 60%.

## Alternatives Considered
- **Python Pandas Aggregation:** Fetch raw data and use `pandas.resample('5T')`. *Rejected:* Doing this in BigQuery via SQL is significantly faster, reduces network payload size from GCP, and avoids unnecessary pandas dependencies in the retriever.
- **Quartile Averages:** *Rejected by user:* Loses too much granularity.

## Verification & Testing
- Run `api/scripts/manage_tools.py call retrieve_biometric_data` and inspect the output size and format of the `last_3_runs_timeseries_summary`.
- Confirm the arrays are significantly shorter but still accurately represent the flow of the activity.
