# Swimming Support Plan ??? Full Garmin Coverage

> **Origin:** Live API exploration session (2026-07-26) using `mercedes` user data (activity `23469665349`, `lap_swimming`, 750m in 25m pool).
> All gaps identified by calling every available `garminconnect` method and comparing against what the SDK models and the ETL currently persist.

---

## 1. SDK Improvements (`garmin_training_toolkit_sdk`)

### 1.1 `protocol/activities.py` ??? Model gaps

#### `Activity` model
The following fields exist in Garmin's `get_activity()` response but are **not modeled** in `Activity`:

| Field to add | Garmin key | Type | Source |
|---|---|---|---|
| `moving_duration_sec` | `movingDuration` | `Optional[float]` | `summaryDTO` |
| `elapsed_duration_sec` | `elapsedDuration` | `Optional[float]` | `summaryDTO` |
| `min_hr` | `minHR` | `Optional[float]` | `summaryDTO` |
| `avg_swim_cadence` | `averageSwimCadence` | `Optional[float]` | `summaryDTO` ??? brazadas/min |
| `active_lengths` | `numberOfActiveLengths` | `Optional[int]` | `summaryDTO` ??? largos nadados (excl. descansos) |
| `avg_strokes_per_length` | `averageStrokes` | `Optional[float]` | `summaryDTO` |
| `avg_stroke_distance_m` | `averageStrokeDistance` | `Optional[float]` | `summaryDTO` |
| `max_speed_mps` | `maxSpeed` | `Optional[float]` | `summaryDTO` |
| `moderate_intensity_min` | `moderateIntensityMinutes` | `Optional[int]` | `summaryDTO` ??? OMS metric |
| `vigorous_intensity_min` | `vigorousIntensityMinutes` | `Optional[int]` | `summaryDTO` ??? OMS metric |
| `is_personal_record` | `personalRecord` | `Optional[bool]` | `metadataDTO` |
| `lap_count` | `lapCount` | `Optional[int]` | `metadataDTO` |
| `swim_stroke` | `swimStroke` | `Optional[str]` | `summaryDTO` via laps |

> **Bug fix:** `pool_length_m`, `total_strokes`, and `avg_swolf` are defined as `Optional[float]` in the model but stored as `STRING` in the BigQuery `recent_activities` table. The ETL must cast these to numeric types before upload.

#### `ActivitySplit` model
The `ActivitySplit` model maps Garmin **laps** (groups of lengths). It is missing:

| Field to add | Garmin key | Type | Notes |
|---|---|---|---|
| `swim_stroke` | `swimStroke` | `Optional[str]` | e.g. `"FREESTYLE"`, `"BACKSTROKE"`, `"BREASTSTROKE"`, `"BUTTERFLY"`, `"MIXED"` |
| `avg_swim_cadence` | `averageSwimCadence` | `Optional[float]` | Brazadas/min per lap |
| `active_lengths` | `numberOfActiveLengths` | `Optional[int]` | Active lengths in this lap |
| `avg_strokes_per_length` | `averageStrokes` | `Optional[float]` | Stroke count per length |
| `elapsed_duration_sec` | `elapsedDuration` | `Optional[float]` | Includes rest |
| `lengths` | `lengthDTOs` | `Optional[List[SwimLength]]` | **New nested model** ??? see below |

#### New model: `SwimLength` (granularity: each individual pool length)
This is the finest granularity Garmin provides for swimming ??? one entry per **25m (or pool_length_m) length**:

```python
class SwimLength(BaseModel):
    """One individual pool length within a lap."""
    length_index: int                        # Position in session (1-based)
    start_time_gmt: Optional[datetime]
    distance_m: Optional[float]              # Always pool_length_m (e.g. 25.0)
    duration_sec: Optional[float]            # Time to complete this length
    avg_speed_mps: Optional[float]           # = distance / duration
    max_speed_mps: Optional[float]
    avg_hr: Optional[float]
    max_hr: Optional[float]
    total_strokes: Optional[int]             # Strokes in this length
    avg_swolf: Optional[float]               # SWOLF = strokes + seconds (efficiency)
    swim_stroke: Optional[str]               # "FREESTYLE", "BACKSTROKE", etc.
    calories: Optional[float]
```

This level of granularity enables per-length SWOLF tracking, pace progression charts, and stroke efficiency analysis ??? none of which are currently possible.

---

### 1.2 `extractors/activities.py` ??? New extractor functions

#### `get_activity_hr_zones(client, activity_id)` ??? New
Wraps `client.get_activity_hr_in_timezones()`. Returns time-in-zone breakdown per activity. Currently called nowhere in the SDK.

```python
def get_activity_hr_zones(
    garmin_client: Garmin,
    activity_id: int,
) -> List[HRZoneTime]: ...

class HRZoneTime(BaseModel):
    zone_number: int
    secs_in_zone: float
    zone_low_boundary_bpm: int
```

#### `get_activity_intensity_minutes(client, activity_id)` ??? New
Extracts `moderateIntensityMinutes` and `vigorousIntensityMinutes` from `get_activity()`. Needed for OMS/WHO weekly intensity tracking.

---

### 1.3 `protocol/telemetry.py` ??? Swimming metrics

`ActivityTelemetryPoint` only captures `hr_bpm` for swimming (all other fields are `null`). No swimming-specific telemetry fields exist (Garmin does not expose per-second stroke or speed data in the telemetry stream for pool swimming ??? this is a **hardware/API limitation**, not an SDK gap).

**No changes needed here.** The telemetry model is correct as-is; the `null` fields for swimming are expected.

---

### 1.4 `extractors/biometrics.py` ??? New extractor: `get_respiration_data()`

`get_respiration_data()` is available in `garminconnect` and returns **rich real data** (confirmed: 2-minute resolution time series, avg/high/low waking and sleep respiration values). It is **not wrapped by the SDK** at all.

```python
def get_respiration_data(
    garmin_client: Garmin,
    date: str,
) -> Optional[RespirationData]: ...

class RespirationData(BaseModel):
    calendar_date: date
    lowest_respiration: Optional[float]       # breaths/min ??? daily minimum
    highest_respiration: Optional[float]      # breaths/min ??? daily maximum
    avg_waking_respiration: Optional[float]   # breaths/min ??? waking average
    avg_sleep_respiration: Optional[float]    # breaths/min ??? sleep average
    timeseries: List[Tuple[int, float]]       # [(timestamp_ms, breaths/min), ...]
    hourly_averages: List[Tuple[int, float, float, float]]  # [(ts, avg, high, low), ...]
```

> **Clinical value:** Elevated respiration rate (> 16 breaths/min during sleep) is an early biomarker of respiratory illness ??? could have flagged mercedes' bronchitis 24-48h before symptoms.

---

## 2. ETL / BigQuery Improvements (`api/src/tools/etl_job.py`)

### 2.1 Bug fixes (type casting)

In the current ETL, `pool_length_m`, `total_strokes`, and `avg_swolf` land as `STRING` in BigQuery despite being `float` in the SDK model. Fix: explicit cast in the DataFrame assembly step before BQ upload.

```python
# In etl_job.py ??? activity DataFrame assembly
float_cols = ["pool_length_m", "total_strokes", "avg_swolf"]
for col in float_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
```

### 2.2 New BigQuery tables

#### `swim_length_telemetry` ??? Per-length granularity

```sql
CREATE TABLE biometric_data_dev.swim_length_telemetry (
  activity_id       STRING NOT NULL,
  user_id           STRING NOT NULL,
  length_index      INTEGER NOT NULL,
  start_time_gmt    TIMESTAMP,
  distance_m        FLOAT64,
  duration_sec      FLOAT64,
  avg_speed_mps     FLOAT64,
  avg_hr            FLOAT64,
  max_hr            FLOAT64,
  total_strokes     INTEGER,
  avg_swolf         FLOAT64,
  swim_stroke       STRING,
  calories          FLOAT64,
  -- Derived fields
  pace_per_100m_sec FLOAT64,  -- = (duration_sec / distance_m) * 100
  stroke_rate       FLOAT64   -- = total_strokes / (duration_sec / 60)
);
```

#### `respiration_history` ??? Daily respiration data

```sql
CREATE TABLE biometric_data_dev.respiration_history (
  user_id                   STRING NOT NULL,
  date                      DATE NOT NULL,
  lowest_respiration        FLOAT64,
  highest_respiration       FLOAT64,
  avg_waking_respiration    FLOAT64,
  avg_sleep_respiration     FLOAT64,
  updated_at                TIMESTAMP
);
```

#### `activity_hr_zones` ??? Time-in-zone per activity

```sql
CREATE TABLE biometric_data_dev.activity_hr_zones (
  activity_id               STRING NOT NULL,
  user_id                   STRING NOT NULL,
  zone_number               INTEGER NOT NULL,
  secs_in_zone              FLOAT64,
  zone_low_boundary_bpm     INTEGER
);
```

### 2.3 New fields to add to `recent_activities` table

```sql
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS moving_duration_sec    FLOAT64;
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS min_hr                 FLOAT64;
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS avg_swim_cadence       FLOAT64;
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS active_lengths         INTEGER;
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS avg_strokes_per_length FLOAT64;
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS moderate_intensity_min INTEGER;
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS vigorous_intensity_min INTEGER;
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS is_personal_record     BOOL;
ALTER TABLE biometric_data_dev.recent_activities ADD COLUMN IF NOT EXISTS swim_stroke            STRING;
-- Fix type bugs (requires table recreation in BQ standard, or use CREATE OR REPLACE)
-- pool_length_m -> FLOAT64 (was STRING)
-- total_strokes -> INTEGER (was STRING)
-- avg_swolf     -> FLOAT64 (was STRING)
```

---

## 3. Biometric Coach (`biometric-coach` skill) Improvements

### 3.1 SKILL.md ??? New swim-specific physiological rules

#### Swimming zones are NOT the same as running zones

> **Critical rule:** Heart rate zones calibrated for running **cannot be applied directly to swimming**.
> Due to the horizontal position, water cooling, and different muscle recruitment, swimming HR at the
> same perceived effort is typically **10-15 bpm lower** than running HR.
>
> Mercedes' Z2 ceiling for running is 142 bpm. For swimming, the equivalent aerobic ceiling is
> approximately **127-132 bpm**.
>
> Until swim-specific zones are calibrated via a Swim Calibration Block, use `avg_hr < 125 bpm`
> as a proxy for "Zone 2 equivalent" in pool sessions.

#### SWOLF as the primary swimming efficiency metric

> **Rule:** For swimming coaching, `avg_swolf` is the primary performance metric ??? equivalent to
> pace in running. **Lower SWOLF = more efficient.**
>
> Reference scale:
> - SWOLF < 35: Elite
> - SWOLF 35-45: Competitive recreational
> - **SWOLF 46-56: Recreational (mercedes' current range)**
> - SWOLF > 60: Beginner / fatigued
>
> Track SWOLF trend across sessions as the primary swimming KPI. A SWOLF decrease of 3+ points
> between sessions indicates real technique improvement. SWOLF increase while volume stays the
> same signals fatigue or technique breakdown.

#### Rest intervals are training data

> **Rule:** In `get_activity_splits()` for swimming, laps with `distance_m = 0.0` are **rest
> intervals** (the swimmer stopped at the wall). Their `duration_sec` and `avg_hr` during rest
> are valid recovery metrics.
>
> Recovery HR drop rate between active lengths is a proxy for aerobic fitness:
> - Fast drop (135 ??? 100 bpm in < 20s): good cardiovascular recovery
> - Slow drop (135 ??? 120 bpm after 30s): indicates accumulated fatigue or low aerobic base

#### Personal Record detection

> **Rule:** If `is_personal_record = true` in the activity metadata, always flag this in the
> coaching response with positive reinforcement. For mercedes, the 2026-07-03 session was a
> confirmed personal record in pool swimming.

#### Stroke type matters

> **Rule:** `swimStroke` identifies the stroke type per length/lap (`FREESTYLE`, `BACKSTROKE`,
> `BREASTSTROKE`, `BUTTERFLY`, `MIXED`). Breaststroke and butterfly have inherently higher SWOLF
> than freestyle ??? never compare SWOLF across stroke types.

---

### 3.2 `retrieve_biometric_data` tool ??? Swim context additions

When the most recent activity is `lap_swimming`, the tool response should include a `last_swim_summary` block:

```json
"last_swim_summary": {
  "activity_id": "23469665349",
  "date": "2026-07-03",
  "distance_m": 750,
  "active_lengths": 30,
  "pool_length_m": 25,
  "avg_swolf": 48.0,
  "avg_hr": 119,
  "max_hr": 147,
  "swim_stroke": "FREESTYLE",
  "is_personal_record": true,
  "avg_swim_cadence": 22
}
```

---

### 3.3 `analyze_activity_efficiency` tool ??? Swimming crash fix + swim analysis

**Current bug:** crashes with `cannot convert float NaN to integer` on any swimming activity because the stage analysis attempts to use `avg_cadence`, `stride_length_mm`, and `ground_contact_time_ms` (running-specific fields that are null for swimming).

**Fix ??? sport-type guard:**

```python
# In analytics.py / analyze_activity_efficiency
activity_type = activity_row.get("type", "")
if activity_type in ("lap_swimming", "open_water_swimming"):
    return _analyze_swim_efficiency(activity_id, user_id)
return _analyze_running_efficiency(activity_row)  # existing logic
```

**`_analyze_swim_efficiency()` should return:**

```python
{
  "avg_swolf": float,             # Session average SWOLF
  "swolf_by_lap": List[float],    # SWOLF per active lap ??? trend analysis
  "pace_per_100m_sec": float,     # Session average pace
  "pace_by_lap_100m": List[float],# Pace per active lap
  "avg_swim_cadence": float,      # Brazadas/min
  "hr_recovery_delta_bpm": float, # avg(active_hr) - avg(rest_hr) across rest intervals
  "active_lengths": int,
  "total_rest_sec": float,
  "zone_distribution": {          # Using swim-adjusted zones
    "z1_sec": float,
    "z2_sec": float,
    "z3_sec": float,
  }
}
```

---

### 3.4 `analyze_activity_stages` tool ??? Swimming crash fix

Same NaN crash. Apply the same sport-type guard. For swimming, "stages" = laps (groups of active lengths separated by rest intervals). Each stage should report: `distance_m`, `duration_sec`, `avg_hr`, `avg_swolf`, `rest_after_sec`.

---

### 3.5 New coaching protocol: Swim Calibration Block

Since swim-specific zones are not established for mercedes (or any new swimmer), a **Swim Calibration Block** must be completed **before** any structured swim training can be prescribed:

> **Swim Calibration Block (2 sessions, 1 week apart):**
>
> **Session 1 ??? Aerobic baseline:**
> 1. 10 min warm-up (very easy, HR < 115 bpm)
> 2. 20 min continuous swimming, keeping HR below 125 bpm (Z1 equivalent)
> 3. 5 min cool-down
> Record: avg SWOLF, avg HR, consistency of pace across lengths.
>
> **Session 2 ??? Threshold probe:**
> 1. 10 min warm-up
> 2. 6 ?? 50m at moderate-hard effort (RPE 7/10), 45s rest between
> 3. 5 min cool-down
> Record: HR peak per 50m interval, SWOLF per 50m, HR recovery in 45s.
>
> **Output calibration markers:**
> - `swim_aet_hr`: HR value where SWOLF starts degrading across intervals (= swim AeT)
> - `swim_swolf_baseline`: avg SWOLF from Session 1 (= aerobic efficiency baseline)
> - `swim_z2_hr_ceiling`: = swim_aet_hr (replaces the running-derived 125 bpm proxy)

---

## 4. Priority Matrix

| Priority | Item | Effort | Impact |
|---|---|---|---|
| ???? **P0** | Fix type bug: `pool_length_m`, `total_strokes`, `avg_swolf` to numeric in BQ ETL | XS | Unblocks all swim analysis |
| ???? **P0** | Fix `analyze_activity_efficiency` + `analyze_activity_stages` crash on swimming (NaN guard) | XS | Unblocks tool usage today |
| ???? **P1** | Add `SwimLength` model + ingest `lengthDTOs` ??? `swim_length_telemetry` BQ table | M | Per-length SWOLF tracking |
| ???? **P1** | Add `get_respiration_data()` SDK extractor + `respiration_history` BQ table + ETL hook | M | Early illness detection signal |
| ???? **P1** | Add swim-specific rules to `SKILL.md` (zones, SWOLF scale, rest intervals, PR) | XS | Correct coaching output immediately |
| ???? **P2** | Add missing `Activity` fields to SDK model + BQ `ALTER TABLE` migrations | M | Richer activity summaries |
| ???? **P2** | Add `ActivitySplit` swim fields + `swim_stroke` per lap | S | Stroke type tracking |
| ???? **P2** | Add `get_activity_hr_zones()` SDK extractor + `activity_hr_zones` BQ table | M | Zone distribution per session |
| ???? **P2** | Implement `_analyze_swim_efficiency()` in analytics tool | L | First-class swim analysis |
| ???? **P2** | Add Swim Calibration Block to coaching protocol in SKILL.md | S | Enables swim zone calibration |
| ???? **P3** | Add `upload_swimming_workout()` support to workout push pipeline | L | Prescribe swim workouts to Garmin watch |
| ???? **P3** | `retrieve_biometric_data` ??? add `last_swim_summary` block | S | Swim context in every coaching response |

---

## 5. What Garmin Does NOT Expose (Hardware Limits)

These metrics are **not available** regardless of SDK or ETL improvements. They require hardware
sensors the device does not have or endpoints Garmin intentionally withholds:

| Metric | Why unavailable |
|---|---|
| Per-length stroke count (granular) | `total_strokes` in `lengthDTOs` = `null` for mercedes' device model |
| Underwater push-off / turn time | Not captured by wrist accelerometer |
| Stroke power / efficiency index | No power meter exists for swimming |
| GPS track / pool lane assignment | Indoor pool = no GPS signal |
| SpO2 during swimming | Optical sensor blocked by water submersion |
| Left/right stroke symmetry | Requires dedicated HRM-Swim chest pod or MARQ-class watch |
| Water temperature | No water thermometer in consumer Garmin wrist devices |

