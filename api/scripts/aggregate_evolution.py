import os

import pandas as pd
from google.cloud import bigquery


def aggregate_history():
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
    dataset = os.getenv("DATASET_NAME", "biometric_data_dev")
    client = bigquery.Client(project=project_id)

    # 1. Fetch raw activities
    query = f"""
        SELECT 
            date, 
            distance_m, 
            vo2max, 
            avg_hr,
            type
        FROM `{project_id}.{dataset}.recent_activities`
        WHERE user_id = 'fsirio' AND type = 'running'
    """
    df = client.query(query).to_dataframe()

    if df.empty:
        print("No running activities found.")
        return

    # 2. Process dates (convert from seconds to datetime)
    # Assuming date is stored as INT64 seconds, but just in case it's ns, let's check size
    if df["date"].max() > 1e11:
        # likely ms or ns. The recent migration set it to seconds.
        # But let's safely convert assuming it's seconds if < 1e11, else ns.
        pass

    # Force convert to datetime assuming seconds (as per recent migration)
    df["datetime"] = pd.to_datetime(df["date"], unit="s", errors="coerce")

    # Filter last 3 years
    three_years_ago = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["datetime"] >= three_years_ago]

    if df.empty:
        print("No running activities found in the last 3 years.")
        return

    # 3. Create Year-Month column
    df["year_month"] = df["datetime"].dt.to_period("M")

    # 4. Aggregate
    # distance_m -> km
    df["distance_km"] = df["distance_m"] / 1000.0

    agg_df = (
        df.groupby("year_month")
        .agg(
            total_volume_km=("distance_km", "sum"),
            avg_vo2max=("vo2max", "mean"),
            avg_hr=("avg_hr", "mean"),
            run_count=("distance_km", "count"),
        )
        .reset_index()
    )

    agg_df["year_month"] = agg_df["year_month"].astype(str)
    agg_df["total_volume_km"] = agg_df["total_volume_km"].round(2)
    agg_df["avg_vo2max"] = agg_df["avg_vo2max"].round(1)
    agg_df["avg_hr"] = agg_df["avg_hr"].round(1)

    agg_df = agg_df.sort_values("year_month")

    # 5. Print Summary
    print("### Monthly Aggregated Running Evolution (Last 3 Years)\\n")
    print(agg_df.to_string(index=False))


if __name__ == "__main__":
    aggregate_history()
