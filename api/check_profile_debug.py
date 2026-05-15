from google.cloud import bigquery

from src.utils.config import get_config, setup_environment


def check_profile():
    setup_environment()
    config = get_config()
    client = bigquery.Client(project=config["project_id"])
    table_id = f"{config['project_id']}.{config['dataset_id']}.user_profile"
    query = f"""
        SELECT 
            display_name, gender, age, height_cm, weight_kg, 
            max_hr, resting_hr, custom_z1_max, custom_z2_max, 
            custom_z3_max, custom_z4_max, updated_at 
        FROM `{table_id}`
    """
    results = list(client.query(query).result())
    print(f"Found {len(results)} rows in user_profile.")
    if results:
        print(dict(results[0]))


if __name__ == "__main__":
    check_profile()
