#!/usr/bin/env python3
"""
Auto Training Plan Generator
Generates personalized training plans based on Garmin data and user preferences.
Follows 80/20 polarized training principles from exercise science research.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)


def calculate_training_weeks(goal_date: str) -> int:
    """Calculate weeks until race day."""
    goal = datetime.strptime(goal_date, "%Y-%m-%d")
    today = datetime.now()
    return max(1, (goal - today).days // 7)


def goal_time_to_paces(goal_time: str, race_type: str) -> dict:
    """
    Calculate training paces from goal race time.
    
    Returns dict with race_pace, easy_pace, tempo_pace, interval_pace (all in sec/km).
    Based on typical percentage differences from race pace.
    """
    parts = goal_time.split(":")
    goal_seconds = int(parts[0]) * 60 + int(parts[1])
    
    race_distances = {
        "5K": 5,
        "10K": 10,
        "HALF": 21.0975,
        "MARATHON": 42.195
    }
    distance = race_distances.get(race_type, 10)
    
    race_pace_sec = goal_seconds / distance
    
    paces = {
        "race_pace": race_pace_sec,
        "easy_pace": race_pace_sec * 1.20,  # ~20% slower
        "tempo_pace": race_pace_sec * 1.05,  # ~5% slower (threshold)
        "interval_pace": race_pace_sec * 0.92,  # ~8% faster (VO2max)
    }
    
    return paces


def paces_to_strings(paces: dict) -> dict:
    """Convert pace seconds to mm:ss strings."""
    result = {}
    for key, sec in paces.items():
        mins = int(sec) // 60
        secs = int(sec) % 60
        result[key] = f"{mins}:{secs:02d}"
    return result


def get_minimum_training_days(vo2max: float, weekly_volume: float) -> int:
    """
    Determine minimum training days based on fitness level.
    
    Beginner: 3 days/week
    Intermediate: 4 days/week  
    Advanced: 5 days/week
    """
    if vo2max >= 55 or weekly_volume >= 60:
        return 5  # Advanced
    elif vo2max >= 45 or weekly_volume >= 40:
        return 4  # Intermediate
    else:
        return 3  # Beginner


def validate_training_days(training_days: int, vo2max: float, weekly_volume: float) -> tuple[bool, str]:
    """
    Validate training days against recommendations.
    Returns (is_valid, warning_message).
    """
    min_days = get_minimum_training_days(vo2max, weekly_volume)
    
    if training_days < min_days:
        return False, f"⚠️  WARNING: {training_days} days/week is below minimum ({min_days}) for your fitness level. Results may be suboptimal."
    elif training_days > 7:
        return False, f"⚠️  WARNING: {training_days} days/week exceeds recommended maximum (7). Risk of overtraining."
    else:
        return True, ""


def calculate_hr_zones(profile: dict) -> dict:
    """Calculate HR zones based on profile data."""
    if not profile or not profile.get("birth_date"):
        return {}
    
    try:
        birth = datetime.fromisoformat(profile["birth_date"].replace("Z", "+00:00"))
        age = (datetime.now() - birth.replace(tzinfo=None)).days // 365
    except:
        return {}
    
    # Tanaka formula: 208 - 0.7 * age
    max_hr = int(208 - 0.7 * age)
    
    zones = {
        "max_hr": max_hr,
        "z1": (int(max_hr * 0.50), int(max_hr * 0.60)),
        "z2": (int(max_hr * 0.60), int(max_hr * 0.70)),
        "z3": (int(max_hr * 0.70), int(max_hr * 0.80)),
        "z4": (int(max_hr * 0.80), int(max_hr * 0.90)),
        "z5": (int(max_hr * 0.90), int(max_hr * 1.00)),
    }
    log.info(f"Calculated HR zones based on age {age} (max HR: {max_hr})")
    return zones


def create_hr_target(low: int, high: int) -> dict:
    """Create HR target type dict for Garmin workout."""
    return {
        "workoutTargetTypeId": 4,  # HEART_RATE
        "workoutTargetTypeKey": "heart.rate.zone",
        "displayOrder": 4,
        "zone": {"low": low, "high": high},
        "targetValueOne": float(low),
        "targetValueTwo": float(high)
    }


def create_pace_target(pace_sec: float) -> dict:
    """Create pace/speed target type dict for Garmin workout (in m/s)."""
    m_per_sec = 1000 / pace_sec  # Convert sec/km to m/s
    return {
        "workoutTargetTypeId": 5,  # SPEED
        "workoutTargetTypeKey": "speed.zone",
        "displayOrder": 5,
        "zone": {"low": m_per_sec * 0.95, "high": m_per_sec * 1.05},
        "targetValueOne": m_per_sec * 0.95,
        "targetValueTwo": m_per_sec * 1.05
    }


def get_phase(week: int, total_weeks: int) -> str:
    """Determine training phase based on week number."""
    taper_weeks = min(2, total_weeks // 4)
    base_weeks = max(4, (total_weeks - taper_weeks) // 2)
    build_weeks = total_weeks - base_weeks - taper_weeks
    
    if week <= base_weeks:
        return "base"
    elif week <= base_weeks + build_weeks:
        return "build"
    elif week <= total_weeks - taper_weeks:
        return "peak"
    else:
        return "taper"
    taper_weeks = min(2, total_weeks // 4)
    base_weeks = max(4, (total_weeks - taper_weeks) // 2)
    build_weeks = total_weeks - base_weeks - taper_weeks
    
    if week <= base_weeks:
        return "base"
    elif week <= base_weeks + build_weeks:
        return "build"
    elif week <= total_weeks - taper_weeks:
        return "peak"
    else:
        return "taper"


def get_long_run_distance(week: int, phase: str, total_weeks: int, base_long: float = 3000) -> int:
    """Calculate long run distance based on phase and progressive overload."""
    max_long = 6000  # 6km max for 10K training
    
    if phase == "base":
        # Weeks 1-4: Build aerobic base, long runs grow gradually
        factor = 1.0 + (week - 1) * 0.15
    elif phase == "build":
        # Weeks 5+: Add more volume, +10% every 2 weeks
        factor = 1.5 + (week - 4) * 0.15
    else:  # peak/taper
        factor = 2.0 - (week / total_weeks) * 0.5  # Taper down
    
    return int(min(base_long * factor, max_long))


def get_interval_workout(week: int, phase: str, interval_sec: float, hr_zones: dict = None) -> dict:
    """Generate VO2max interval workout."""
    if phase == "build":
        interval_count = 4 + ((week - 4) // 2)
        interval_dur = 180 + week * 30
    else:
        interval_count = 5 + (week // 2)
        interval_dur = 360 + week * 30
    
    interval_count = min(interval_count, 8)
    interval_dur = min(interval_dur, 540)
    
    recovery_dur = interval_dur // 2
    
    # Create pace target for intervals (in m/s)
    m_per_sec = 1000 / interval_sec
    pace_target = {
        "workoutTargetTypeId": 5,  # SPEED
        "workoutTargetTypeKey": "speed.zone",
        "displayOrder": 5,
        "zone": {"low": m_per_sec * 0.95, "high": m_per_sec * 1.05},
        "targetValueOne": m_per_sec * 0.95,
        "targetValueTwo": m_per_sec * 1.05
    }
    
    interval_pace = f"{int(interval_sec // 60)}:{int(interval_sec % 60):02d}"
    
    steps = [["warmup", 600, None]]
    for i in range(interval_count):
        steps.append(["run", interval_dur, pace_target])
        if i < interval_count - 1:
            steps.append(["recovery", recovery_dur, None])
    steps.append(["cooldown", 300, None])
    
    total_duration = 600 + interval_count * interval_dur + (interval_count - 1) * recovery_dur + 300
    
    return {
        "name": f"Intervals {week}",
        "description": f"{interval_count}x{interval_dur//60}min at VO2max pace (~{interval_pace}/km)",
        "duration": total_duration,
        "steps": steps
    }


def get_tempo_workout(week: int, phase: str, tempo_sec: int, hr_zones: dict = None) -> dict:
    """Generate threshold/tempo workout (used sparingly in build phase)."""
    tempo_dur = 900 + (week * 60)  # 15min -> 30min
    tempo_dur = min(tempo_dur, 2400)  # Max 40min
    
    total_duration = 600 + tempo_dur + 300  # warmup + tempo + cooldown
    
    tempo_target = create_pace_target(tempo_sec)
    
    return {
        "name": f"Tempo Run {week}",
        "description": f"{tempo_dur//60}min at threshold pace",
        "duration": total_duration,
        "steps": [
            ["warmup", 600, None],
            ["run", tempo_dur, tempo_target],
            ["cooldown", 300, None],
        ]
    }


def get_easy_run(week: int, phase: str, is_deload: bool = False, hr_zones: dict = None) -> dict:
    """Generate easy Zone 2 run."""
    if is_deload:
        duration = 20 * 60
        run_dur = 600
    else:
        duration = 40 * 60
        run_dur = 1800 if phase == "base" else 2100
    
    # HR target for Zone 2
    hr_target = None
    if hr_zones:
        z2 = hr_zones.get("z2", (0, 0))
        hr_target = create_hr_target(int(z2[0]), int(z2[1]))
    
    return {
        "name": f"Easy Run {week}",
        "description": f"Easy Zone 2 - conversational pace (HR {int(z2[0])}-{int(z2[1])} bpm)",
        "duration": duration,
        "steps": [
            ["warmup", 600, None],
            ["run", run_dur, hr_target],
            ["cooldown", 300, None],
        ]
    }


def get_long_run(week: int, phase: str, total_weeks: int, is_deload: bool = False, hr_zones: dict = None) -> dict:
    """Generate long run at Zone 2."""
    if is_deload:
        long_dist = 1500
    else:
        long_dist = get_long_run_distance(week, phase, total_weeks)
    
    warmup = 900 if long_dist > 3000 else 600
    cooldown = 300
    
    # HR target for Zone 2
    hr_target = None
    if hr_zones:
        z2 = hr_zones.get("z2", (0, 0))
        hr_target = create_hr_target(int(z2[0]), int(z2[1]))
    
    duration = warmup + long_dist + cooldown
    
    return {
        "name": f"Long Run {week}",
        "description": f"Long run {long_dist/1000:.1f}km at Zone 2 pace (HR {int(z2[0])}-{int(z2[1])} bpm)",
        "duration": duration,
        "steps": [
            ["warmup", warmup, None],
            ["run", long_dist, hr_target],
            ["cooldown", cooldown, None],
        ]
    }


def generate_plan(garmin_data: dict, prefs: dict) -> tuple[list[dict], dict]:
    """Generate a training plan based on Garmin data and preferences.
    
    Returns (workouts, paces_used) tuple.
    """
    
    profile = garmin_data.get("profile", {})
    activities = garmin_data.get("activities", [])
    running = [a for a in activities if a.get("type") == "running"]
    
    # Calculate data-driven HR zones from actual activity data
    hr_zones = calculate_hr_zones(profile)  # Fallback to age-based
    
    # Override with data-driven zones if we have enough data
    hr_values = [a.get("avg_hr", 0) for a in running if a.get("avg_hr")]
    max_hr_values = [a.get("max_hr", 0) for a in running if a.get("max_hr")]
    
    if len(hr_values) >= 5 and max_hr_values:
        hr_sorted = sorted(hr_values)
        n = len(hr_sorted)
        p25 = hr_sorted[n // 4]
        p75 = hr_sorted[3 * n // 4]
        max_hr = max(max_hr_values)
        
        # Use percentile-based zones similar to garmin.py
        hr_zones = {
            "max_hr": max_hr,
            "z1": (0, int(p25 - 5)),
            "z2": (int(p25 - 5), int(p25 + 5)),
            "z3": (int(p25 + 6), int(p75)),
            "z4": (int(p75 + 1), int(max_hr - 20)),
            "z5": (int(max_hr - 19), max_hr),
        }
        log.info(f"Using data-driven HR zones: Z1<{hr_zones['z1'][1]}, Z2={hr_zones['z2'][0]}-{hr_zones['z2'][1]}, Z3={hr_zones['z3'][0]}-{hr_zones['z3'][1]}, Z4={hr_zones['z4'][0]}-{hr_zones['z4'][1]}")
    else:
        log.info(f"Using age-based HR zones: {hr_zones}")
        
    # Override with manual configuration from .env if present
    if prefs.get("HR_Z1_MAX"):
        try:
            hr_zones["z1"] = (0, int(prefs["HR_Z1_MAX"]))
            hr_zones["z2"] = (int(prefs["HR_Z1_MAX"]) + 1, int(prefs["HR_Z2_MAX"]))
            hr_zones["z3"] = (int(prefs["HR_Z2_MAX"]) + 1, int(prefs["HR_Z3_MAX"]))
            hr_zones["z4"] = (int(prefs["HR_Z3_MAX"]) + 1, int(prefs["HR_Z4_MAX"]))
            hr_zones["z5"] = (int(prefs["HR_Z4_MAX"]) + 1, hr_zones.get("max_hr", 193))
            log.info(f"Overriding HR zones with manual configuration from .env: Z2={hr_zones['z2']}")
        except (ValueError, KeyError):
            pass
    
    race_type = prefs.get("GOAL_RACE", "10K")
    goal_date = prefs.get("GOAL_DATE", "")
    training_days = int(prefs.get("TRAINING_DAYS", 3))
    goal_time = prefs.get("GOAL_TIME", "")
    
    weeks = calculate_training_weeks(goal_date)
    log.info(f"Generating {weeks}-week {race_type} training plan...")
    log.info(f"Phase structure: Base -> Build -> Peak -> Taper")
    
    vo2max = profile.get("vo2max", 47)
    stats = garmin_data.get("stats", {})
    weekly_volume = stats.get("weekly_distance_km", 22)
    
    is_valid, warning = validate_training_days(training_days, vo2max, weekly_volume)
    if warning:
        log.warning(warning)
    
    if goal_time:
        paces = goal_time_to_paces(goal_time, race_type)
        paces_str = paces_to_strings(paces)
        log.info(f"Calculated paces from goal time {goal_time}: {paces_str}")
    else:
        target_pace = prefs.get("RACE_PACE_TARGET", "5:30")
        easy_pace = prefs.get("EASY_PACE", "6:00")
        tempo_pace = prefs.get("TEMPO_PACE", "5:45")
        interval_pace = prefs.get("INTERVAL_PACE", "5:15")
        
        def pace_to_seconds(pace_str):
            parts = pace_str.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        
        paces = {
            "race_pace": pace_to_seconds(target_pace),
            "easy_pace": pace_to_seconds(easy_pace),
            "tempo_pace": pace_to_seconds(tempo_pace),
            "interval_pace": pace_to_seconds(interval_pace),
        }
        paces_str = {
            "race_pace": target_pace,
            "easy_pace": easy_pace,
            "tempo_pace": tempo_pace,
            "interval_pace": interval_pace,
        }
        log.info("Using manual paces from config")
    
    interval_sec = paces["interval_pace"]
    tempo_sec = paces["tempo_pace"]
    easy_sec = paces["easy_pace"]
    
    start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    workouts = []
    
    for week in range(1, weeks + 1):
        phase = get_phase(week, weeks)
        is_deload = (week % 4 == 0) and week < weeks
        
        log.info(f"Week {week}: {phase} phase" + (" - DELOAD" if is_deload else ""))
        
        # Generate 3 workouts per week following 80/20 rule
        # 2 easy (Zone 2) + 1 hard (intervals)
        # No hard days back-to-back
        
        # Day 1: Easy run (Monday)
        day1 = start_date + timedelta(weeks=week-1, days=0)
        easy1 = get_easy_run(week, phase, is_deload, hr_zones)
        easy1["date"] = day1.strftime("%Y-%m-%d")
        workouts.append(easy1)
        
        # Day 2: Hard workout - intervals start in build phase
        # Base phase: optional easy run or rest
        # Build phase: VO2max intervals
        # Peak phase: intervals at race pace
        day2 = start_date + timedelta(weeks=week-1, days=2)
        
        if phase == "base" or is_deload:
            # Base phase: add 3rd easy workout if training_days >= 3
            if training_days >= 3 and not is_deload and phase == "base":
                day2_easy = get_easy_run(week, phase, is_deload=False, hr_zones=hr_zones)
                day2_easy["date"] = day2.strftime("%Y-%m-%d")
                workouts.append(day2_easy)
            hard_workout = None
        elif phase == "build":
            # Alternate between Tempo and Intervals in build phase
            if week % 2 == 0:
                hard_workout = get_tempo_workout(week, phase, tempo_sec, hr_zones)
            else:
                hard_workout = get_interval_workout(week, phase, interval_sec, hr_zones)
        else:  # peak/taper
            hard_workout = get_interval_workout(week, phase, interval_sec, hr_zones)
        
        if hard_workout and training_days >= 2:
            hard_workout["date"] = day2.strftime("%Y-%m-%d")
            workouts.append(hard_workout)
        
        # Day 3: Long run (Friday for recovery before weekend)
        day3 = start_date + timedelta(weeks=week-1, days=4)
        long_run = get_long_run(week, phase, weeks, is_deload, hr_zones)
        long_run["date"] = day3.strftime("%Y-%m-%d")
        workouts.append(long_run)
        
        # Optional 4th day: Easy run (Sunday) - if 4+ days requested
        if training_days >= 4 and not is_deload:
            day4 = start_date + timedelta(weeks=week-1, days=6)
            easy4 = get_easy_run(week, phase, is_deload=False, hr_zones=hr_zones)
            easy4["date"] = day4.strftime("%Y-%m-%d")
            workouts.append(easy4)
    
    log.info(f"Generated {len(workouts)} workouts")
    
    return workouts, paces_str


def save_plan(workouts: list, output_path: Path):
    """Save generated plan to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(workouts, f, indent=2)
    log.info(f"Plan saved to {output_path}")


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    from garmin_utils import load_env_file, find_token_file, get_authenticated_client
    from collector import collect_all_data
    
    log.info("Auto Training Plan Generator")
    log.info("=" * 40)
    
    # Load preferences
    prefs = load_env_file()
    
    if not prefs.get("GOAL_DATE"):
        log.error("GOAL_DATE not set in .env")
        sys.exit(1)
    
    # Collect fresh data if needed
    report_file = Path(__file__).parent / "data" / "garmin_report.json"
    if report_file.exists():
        with open(report_file) as f:
            garmin_data = json.load(f)
        log.info("Using cached data from report")
    else:
        log.info("Collecting fresh data...")
        token_file = find_token_file()
        if not token_file:
            log.error("Not authenticated. Run garmin_auth_browser.py first.")
            sys.exit(1)
        client = get_authenticated_client(token_file)
        garmin_data = collect_all_data(client, days=90)
    
    # Generate plan
    workouts, paces = generate_plan(garmin_data, prefs)
    
    # Show calculated paces
    log.info("=" * 40)
    log.info("Training Paces:")
    for key, value in paces.items():
        log.info(f"  {key}: {value}/km")
    
    # Save
    output = Path(__file__).parent.parent / "garmin-workout-uploader" / "workouts.json"
    save_plan(workouts, output)
    
    log.info(f"Generated {len(workouts)} workouts")
    log.info("Run garmin_workout_uploader.py to upload to Garmin Connect")


if __name__ == "__main__":
    main()
