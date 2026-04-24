#!/usr/bin/env python3
"""
Progress Tracker
Tracks training progress from garmin_report.json
"""

import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)

REPORT_FILE = Path(__file__).parent / "data" / "garmin_report.json"


def load_data() -> dict:
    """Load Garmin report data."""
    if not REPORT_FILE.exists():
        log.error(f"Run collector.py first: {REPORT_FILE} not found")
        return {}
    
    with open(REPORT_FILE) as f:
        return json.load(f)


def analyze_activities(activities: list[dict], days: int = 90) -> dict:
    """Analyze running activities."""
    running = [a for a in activities if a.get("type") == "running"]
    
    total_runs = len(running)
    total_distance = sum(a.get("distance_m", 0) for a in running) / 1000
    total_time = sum(a.get("duration_sec", 0) for a in running) / 3600
    
    hr_values = [a.get("avg_hr", 0) for a in running if a.get("avg_hr")]
    avg_hr = sum(hr_values) / len(hr_values) if hr_values else 0
    
    pace_values = [a.get("avg_pace", 0) for a in running if a.get("avg_pace") and a.get("avg_pace") > 0]
    if pace_values:
        avg_pace_sec_km = sum(1000 / p for p in pace_values) / len(pace_values)
    else:
        avg_pace_sec_km = None
    
    vo2max_values = [a.get("vo2max", 0) for a in running if a.get("vo2max")]
    latest_vo2max = vo2max_values[0] if vo2max_values else None
    
    return {
        "total_runs": total_runs,
        "total_distance_km": round(total_distance, 1),
        "total_hours": round(total_time, 1),
        "avg_hr": round(avg_hr, 0),
        "avg_pace": f"{int(avg_pace_sec_km//60)}:{int(avg_pace_sec_km%60):02d}/km" if avg_pace_sec_km else "N/A",
        "vo2max": latest_vo2max,
        "weekly_runs": round(total_runs / (days / 7), 1),
        "weekly_km": round(total_distance / (days / 7), 1),
    }


def analyze_hr_zones(activities: list[dict]) -> dict:
    """Analyze HR zone distribution."""
    running = [a for a in activities if a.get("type") == "running"]
    max_hr = max(a.get("max_hr", 0) for a in running if a.get("max_hr")) or 193
    
    zones = {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0, "Z5": 0}
    
    for a in running:
        hr = a.get("avg_hr")
        if not hr:
            continue
        pct = hr / max_hr * 100
        if pct < 60:
            zones["Z1"] += 1
        elif pct < 70:
            zones["Z2"] += 1
        elif pct < 80:
            zones["Z3"] += 1
        elif pct < 90:
            zones["Z4"] += 1
        else:
            zones["Z5"] += 1
    
    total = len(running)
    if total > 0:
        for z in zones:
            zones[z] = round(zones[z] / total * 100, 1)
    
    return zones, max_hr


def print_progress_report(days: int = 90):
    """Print progress report."""
    data = load_data()
    if not data:
        return
    
    activities = data.get("activities", [])
    
    stats = analyze_activities(activities, days)
    zones, max_hr = analyze_hr_zones(activities)
    
    print("\n" + "=" * 50)
    print(f"PROGRESS REPORT - Last {days} days")
    print("=" * 50)
    
    print("\n📊 Running Activity")
    print(f"  Total runs: {stats['total_runs']}")
    print(f"  Total distance: {stats['total_distance_km']} km")
    print(f"  Total time: {stats['total_hours']} hours")
    print(f"  Weekly: {stats['weekly_runs']} runs, {stats['weekly_km']} km")
    
    if stats['avg_hr']:
        print(f"  Average HR: {stats['avg_hr']:.0f} bpm")
    
    if stats['avg_pace']:
        print(f"  Average pace: {stats['avg_pace']}")
    
    if stats['vo2max']:
        print(f"  VO2max: {stats['vo2max']}")
    
    print("\n❤️ HR Zone Distribution (max HR: ~" + str(int(max_hr)) + ")")
    print(f"  Z1 (Recovery): {zones['Z1']}%")
    print(f"  Z2 (Easy):     {zones['Z2']}%")
    print(f"  Z3 (Tempo):    {zones['Z3']}%")
    print(f"  Z4 (Hard):     {zones['Z4']}%")
    print(f"  Z5 (Max):      {zones['Z5']}%")
    
    if zones['Z4'] > 50:
        print("\n⚠️  WARNING: Zone 4 is too high! Target: 80% Z1-2, 20% Z4-5")
    
    print("\n" + "=" * 50)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Progress Tracker")
    parser.add_argument("--days", type=int, default=90, help="Days to analyze")
    args = parser.parse_args()
    
    print_progress_report(args.days)


if __name__ == "__main__":
    main()
