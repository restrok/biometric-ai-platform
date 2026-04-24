#!/usr/bin/env python3
"""
Recovery Analysis
Analyzes recovery status from garmin_report.json
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
        log.error("Run collector.py first")
        return {}
    with open(REPORT_FILE) as f:
        return json.load(f)


def analyze_recovery() -> dict:
    """Analyze recovery data."""
    data = load_data()
    if not data:
        return {"error": "No data"}
    
    result = {"days": [], "overall": {}}
    
    hrv = data.get("hrv", [])
    if hrv:
        hrv_vals = [h.get("avg_hrv", 0) for h in hrv if h.get("avg_hrv")]
        if hrv_vals:
            result["days"] = [{"date": h.get("calendarDate"), "hrv": h.get("avg_hrv")} for h in hrv[-7:]]
            avg_hrv = sum(hrv_vals) / len(hrv_vals)
            result["overall"]["avg_hrv"] = round(avg_hrv, 1)
            result["overall"]["hrv_status"] = "low" if hrv_vals[-1] < avg_hrv * 0.8 else "normal"
    
    readiness = data.get("training_readiness", [])
    if readiness:
        vals = [r.get("value", 0) for r in readiness if r.get("value")]
        if vals:
            result["overall"]["avg_readiness"] = round(sum(vals) / len(vals), 0)
    
    return result


def print_recovery_report():
    """Print recovery report."""
    recovery = analyze_recovery()
    
    if "error" in recovery:
        log.error(recovery["error"])
        return
    
    print("\n" + "=" * 50)
    print("RECOVERY ANALYSIS")
    print("=" * 50)
    
    overall = recovery.get("overall", {})
    
    if overall.get("avg_hrv"):
        print(f"\n💓 HRV: {overall.get('avg_hrv')} ms ({overall.get('hrv_status', 'N/A')})")
    else:
        print("\n💓 No HRV data")
    
    if overall.get("avg_readiness"):
        print(f"📈 Training Readiness: {overall.get('avg_readiness')}/100")
    else:
        print("📈 No readiness data")
    
    if recovery.get("days"):
        print("\n📅 Recent:")
        for d in recovery["days"][:5]:
            print(f"  {d.get('date')}: HRV {d.get('hrv')} ms")
    
    print("\n" + "=" * 50)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Recovery Analysis")
    parser.add_argument("--days", type=int, default=7, help="Days to analyze")
    parser.parse_args()
    
    print_recovery_report()


if __name__ == "__main__":
    main()
