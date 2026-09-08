import os
import time

"""GCP Cloud-Native Storage Engine implementing Firestore (OLTP) and BigQuery (OLAP + Vector)."""

import hashlib
import json
import logging
import secrets
import uuid
from datetime import UTC, date, datetime
from typing import Any

import google.cloud.firestore as firestore  # type: ignore[attr-defined]
from google.cloud import bigquery

from src.storage.base import StorageEngine
from src.utils.config import get_config

log = logging.getLogger(__name__)


class GCPStorageEngine(StorageEngine):
    """Storage engine using Firestore for OLTP and BigQuery for analytical data and vector search."""

    def __init__(self, project_id: str | None = None, dataset_id: str | None = None):
        config = get_config()
        self.project_id = project_id or config.get("project_id")
        self.dataset_id = dataset_id or config.get("dataset_id")
        self.knowledge_table = config.get("knowledge_base_table", "exercise_science_knowledge")

        self._db: firestore.Client | None = None
        self._bq: bigquery.Client | None = None
        self._users_cache: tuple[float, list[str]] | None = None
        log.info(f"☁️ GCPStorageEngine initialized for project: {self.project_id}, dataset: {self.dataset_id}")

    @property
    def db(self) -> firestore.Client:
        if self._db is None:
            self._db = firestore.Client(project=self.project_id)
        return self._db

    @property
    def bq(self) -> bigquery.Client:
        if self._bq is None:
            self._bq = bigquery.Client(project=self.project_id)
        return self._bq

    # --- Profile & User Management ---
    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        doc_ref = self.db.collection("user_profiles").document(user_id)
        doc = doc_ref.get()  # type: ignore[union-attr]
        if getattr(doc, "exists", False):
            return dict(getattr(doc, "to_dict", lambda: {})() or {})
        return {}

    def update_user_profile(self, user_id: str, data: dict[str, Any]) -> None:
        self._users_cache = None
        doc_ref = self.db.collection("user_profiles").document(user_id)
        doc_ref.set(data, merge=True)
        log.info(f"✅ GCPStorageEngine: Updated Firestore profile for {user_id}")

    # --- Goals ---
    def get_user_goals(self, user_id: str) -> list[dict[str, Any]]:
        docs = self.db.collection("user_goals").where("user_id", "==", user_id).where("status", "==", "active").stream()
        return [{"goal_id": d.id, **dict(d.to_dict() or {})} for d in docs]

    def save_user_goal(self, user_id: str, goal: dict[str, Any]) -> str:
        goal_id = str(goal.get("goal_id") or uuid.uuid4())
        now = datetime.now(UTC)
        goal_data = {
            **goal,
            "goal_id": goal_id,
            "user_id": user_id,
            "updated_at": now,
        }
        if "created_at" not in goal_data:
            goal_data["created_at"] = now
        self.db.collection("user_goals").document(goal_id).set(goal_data, merge=True)
        return goal_id

    # --- Semantic Memories ---
    def get_semantic_memories(self, user_id: str) -> list[dict[str, Any]]:
        docs = (
            self.db.collection("user_memories").where("user_id", "==", user_id).where("is_active", "==", True).stream()
        )
        return [{"memory_id": d.id, **dict(d.to_dict() or {})} for d in docs]

    def save_semantic_memory(
        self,
        user_id: str,
        memory_text: str,
        memory_type: str = "fact",
        source_session_id: str | None = None,
        confidence_score: float = 1.0,
    ) -> str:
        doc_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        memory_data = {
            "user_id": user_id,
            "memory_type": memory_type,
            "memory_text": memory_text,
            "source_session_id": source_session_id,
            "confidence_score": confidence_score,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        self.db.collection("user_memories").document(doc_id).set(memory_data)
        return doc_id

    def update_semantic_memory(self, memory_id: str, new_text: str) -> str:
        doc_ref = self.db.collection("user_memories").document(memory_id)
        doc = doc_ref.get()  # type: ignore[union-attr]
        if not getattr(doc, "exists", False):
            return f"Error: Memory {memory_id} not found."
        now = datetime.now(UTC)
        doc_ref.update({"memory_text": new_text, "updated_at": now, "is_active": True})
        return f"Successfully updated memory {memory_id}."

    def retire_semantic_memory(self, memory_id: str) -> str:
        doc_ref = self.db.collection("user_memories").document(memory_id)
        doc = doc_ref.get()  # type: ignore[union-attr]
        if not getattr(doc, "exists", False):
            return f"Error: Memory {memory_id} not found."
        now = datetime.now(UTC)
        doc_ref.update({"is_active": False, "updated_at": now})
        return f"Successfully retired memory {memory_id}."

    # --- Calibration Profile Markers ---
    def get_calibration_markers(self, user_id: str) -> list[dict[str, Any]]:
        docs = self.db.collection("calibration_markers").where("user_id", "==", user_id).stream()
        return [{"marker_id": d.id, **dict(d.to_dict() or {})} for d in docs]

    def save_calibration_marker(
        self, user_id: str, marker_type: str, marker_value: float, context: str | None = None
    ) -> str:
        marker_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        data = {
            "marker_id": marker_id,
            "user_id": user_id,
            "marker_type": marker_type,
            "marker_value": marker_value,
            "context": context,
            "created_at": now,
            "updated_at": now,
        }
        self.db.collection("calibration_markers").document(marker_id).set(data)
        return marker_id

    # --- Health Status ---
    def get_health_status(self, user_id: str) -> dict[str, Any] | None:
        profile = self.get_user_profile(user_id)
        return profile.get("latest_health_status")

    def log_health_status(self, user_id: str, health_data: dict[str, Any]) -> str:
        target_date = str(health_data.get("date") or date.today().isoformat())
        # 1. Update Firestore state
        self.update_user_profile(user_id, {"latest_health_status": health_data})

        # 2. Update BigQuery historical table
        table_id = f"{self.project_id}.{self.dataset_id}.user_health_status"
        safe_feeling = str(health_data.get("feeling", "")).replace("'", "''")
        safe_notes = str(health_data.get("notes", "")).replace("'", "''") if health_data.get("notes") else None
        safe_injury = (
            str(health_data.get("injury_notes", "")).replace("'", "''") if health_data.get("injury_notes") else None
        )
        fatigue = health_data.get("fatigue_level")

        query = f"""
            MERGE `{table_id}` T
            USING (SELECT DATE '{target_date}' as date) S
            ON T.date = S.date AND T.user_id = '{user_id}'
            WHEN MATCHED THEN
                UPDATE SET 
                    feeling = '{safe_feeling}',
                    notes = {f"'{safe_notes}'" if safe_notes else "NULL"},
                    fatigue_level = {fatigue if fatigue is not None else "NULL"},
                    injury_notes = {f"'{safe_injury}'" if safe_injury else "NULL"},
                    updated_at = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN
                INSERT (date, feeling, notes, fatigue_level, injury_notes, updated_at, user_id)
                VALUES ('{target_date}', '{safe_feeling}', {f"'{safe_notes}'" if safe_notes else "NULL"}, {fatigue if fatigue is not None else "NULL"}, {f"'{safe_injury}'" if safe_injury else "NULL"}, CURRENT_TIMESTAMP(), '{user_id}')
        """
        try:
            self.bq.query(query).result()
        except Exception as e:
            log.warning(f"⚠️ BigQuery health log failed (non-critical): {e}")

        return target_date

    # --- Analytical Series & Telemetry ---
    def insert_activities(self, user_id: str, activities: list[dict[str, Any]]) -> None:
        table_id = f"{self.project_id}.{self.dataset_id}.activities"
        rows = []
        for act in activities:
            rows.append(
                {
                    "activity_id": str(act.get("activity_id") or uuid.uuid4()),
                    "user_id": user_id,
                    "activity_name": act.get("activity_name"),
                    "activity_type": act.get("activity_type", "running"),
                    "start_time": act.get("start_time"),
                    "duration_seconds": act.get("duration_seconds"),
                    "distance_meters": act.get("distance_meters"),
                    "avg_heart_rate": act.get("avg_heart_rate"),
                    "max_heart_rate": act.get("max_heart_rate"),
                    "aerobic_training_effect": act.get("aerobic_training_effect"),
                    "anaerobic_training_effect": act.get("anaerobic_training_effect"),
                    "trimp": act.get("trimp"),
                    "summary": json.dumps(act.get("summary", {})),
                }
            )
        errors = self.bq.insert_rows_json(table_id, rows)
        if errors:
            log.error(f"❌ BigQuery insert_rows errors: {errors}")

    def insert_daily_physiology(self, user_id: str, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        table_id = f"{self.project_id}.{self.dataset_id}.daily_physiology"
        rows = [{**r, "user_id": user_id} for r in records]
        try:
            errors = self.bq.insert_rows_json(table_id, rows)
            if errors:
                log.error(f"❌ Error inserting daily physiology to BigQuery: {errors}")
        except Exception as e:
            log.warning(f"⚠️ BigQuery daily physiology insert failed: {e}")

    def get_recent_activities(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
        activity_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        table_id = f"{self.project_id}.{self.dataset_id}.recent_activities"
        where_clauses = [f"user_id = '{user_id}'"]

        if activity_type:
            where_clauses.append(f"LOWER(type) = '{activity_type.lower()}'")
        if start_date:
            where_clauses.append(f"date >= UNIX_SECONDS(TIMESTAMP('{start_date}'))")
        if end_date:
            where_clauses.append(f"date <= UNIX_SECONDS(TIMESTAMP('{end_date}'))")

        query = f"""
            SELECT
                CAST(id AS STRING) AS activity_id,
                user_id,
                name AS activity_name,
                type AS activity_type,
                TIMESTAMP_SECONDS(date) AS start_time,
                duration_sec AS duration_seconds,
                distance_m AS distance_meters,
                avg_hr AS avg_heart_rate,
                max_hr AS max_heart_rate,
                avg_pace,
                calories,
                elevation_gain,
                vo2max,
                avg_power
            FROM `{table_id}`
            WHERE {" AND ".join(where_clauses)}
            ORDER BY date DESC
            LIMIT {limit} OFFSET {offset}
        """
        df = self.bq.query(query).to_dataframe()
        records = df.to_dict(orient="records")
        for r in records:
            if "start_time" in r and r["start_time"] is not None:
                r["start_time"] = r["start_time"].isoformat()
        return records

    def get_activity_telemetry(self, activity_id: str, _user_id: str | None = None) -> list[dict[str, Any]]:
        table_id = f"{self.project_id}.{self.dataset_id}.latest_activity_telemetry"
        query = f"""
            SELECT * FROM `{table_id}`
            WHERE activity_id = '{activity_id}'
            ORDER BY timestamp_ms ASC
        """
        df = self.bq.query(query).to_dataframe()
        return df.to_dict(orient="records")

    def get_daily_physiology(self, user_id: str, days: int = 14) -> list[dict[str, Any]]:
        physio_table = f"{self.project_id}.{self.dataset_id}.daily_physiology"
        hrv_table = f"{self.project_id}.{self.dataset_id}.hrv_history"
        query = f"""
            SELECT
                p.user_id,
                CAST(p.date AS STRING) AS date,
                p.resting_heart_rate,
                p.max_heart_rate,
                p.all_day_stress_avg,
                p.body_battery_end_of_day,
                COALESCE(p.body_battery_end_of_day, 0) AS body_battery_max,
                p.total_steps,
                h.avg_hrv AS hrv_rmssd
            FROM `{physio_table}` p
            LEFT JOIN `{hrv_table}` h
                ON p.user_id = h.user_id AND CAST(p.date AS STRING) = h.date
            WHERE p.user_id = '{user_id}'
            ORDER BY p.date DESC
            LIMIT {days}
        """
        try:
            df = self.bq.query(query).to_dataframe()
            records = df.to_dict(orient="records")
            for r in records:
                if "date" in r and r["date"] is not None:
                    r["date"] = str(r["date"])
            return records
        except Exception as e:
            log.warning(f"⚠️ Error querying daily physiology with HRV join: {e}")
            fallback_q = f"SELECT * FROM `{physio_table}` WHERE user_id = '{user_id}' ORDER BY date DESC LIMIT {days}"
            df = self.bq.query(fallback_q).to_dataframe()
            records = df.to_dict(orient="records")
            for r in records:
                if "date" in r and r["date"] is not None:
                    r["date"] = str(r["date"])
            return records

    def query_macro_load_history(
        self, user_id: str, group_by: str = "weekly", limit_months: int = 6
    ) -> list[dict[str, Any]]:
        table_id = f"{self.project_id}.{self.dataset_id}.recent_activities"
        time_trunc = (
            "DATE_TRUNC(DATE(TIMESTAMP_SECONDS(date)), WEEK)"
            if group_by == "weekly"
            else "DATE_TRUNC(DATE(TIMESTAMP_SECONDS(date)), MONTH)"
        )
        query = f"""
            SELECT
                {time_trunc} AS period,
                COUNT(id) AS total_sessions,
                COALESCE(SUM(distance_m), 0) / 1000.0 AS total_distance_km,
                COALESCE(SUM(duration_sec), 0) / 3600.0 AS total_hours,
                0 AS total_trimp,
                COALESCE(AVG(avg_hr), 0) AS avg_hr
            FROM `{table_id}`
            WHERE user_id = '{user_id}' AND DATE(TIMESTAMP_SECONDS(date)) >= DATE_SUB(CURRENT_DATE(), INTERVAL {limit_months} MONTH)
            GROUP BY period
            ORDER BY period ASC
        """
        df = self.bq.query(query).to_dataframe()
        return df.to_dict(orient="records")

    # --- Vector Search / RAG ---
    def search_knowledge_vectors(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        table_id = f"{self.project_id}.{self.dataset_id}.{self.knowledge_table}"
        sql = f"""
        SELECT base.content, base.metadata, distance
        FROM VECTOR_SEARCH(
          TABLE `{table_id}`,
          'embedding',
          (SELECT @embedding AS embedding),
          top_k => {top_k},
          distance_type => 'COSINE'
        )
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("embedding", "FLOAT64", query_vector)]
        )
        results = self.bq.query(sql, job_config=job_config).result()
        output = []
        for row in results:
            output.append({"content": row.content, "score": 1.0 - getattr(row, "distance", 0.0)})
        return output

    # --- API Keys & Multi-Tenant Auth ---
    def _hash_key(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def create_api_key(self, user_id: str, name: str = "default") -> str:
        raw_key = f"bio_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_key(raw_key)
        key_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        self.db.collection("api_keys").document(key_id).set(
            {
                "key_id": key_id,
                "user_id": user_id,
                "key_hash": key_hash,
                "name": name,
                "is_active": True,
                "created_at": now,
            }
        )
        return raw_key

    def validate_api_key(self, api_key: str, user_id: str) -> bool:
        key_hash = self._hash_key(api_key)
        docs = (
            self.db.collection("api_keys")
            .where("user_id", "==", user_id)
            .where("key_hash", "==", key_hash)
            .where("is_active", "==", True)
            .limit(1)
            .stream()
        )
        return len(list(docs)) > 0

    def list_users(self, force_refresh: bool = False) -> list[str]:
        """Retrieves list of active athlete/user IDs from Firestore, caching results for 5 mins."""
        now = time.time()
        if not force_refresh and self._users_cache:
            cache_time, cached_users = self._users_cache
            if now - cache_time < 300:
                return cached_users

        users = set()
        try:
            for doc in self.db.collection("user_profiles").stream():
                if doc.id:
                    users.add(doc.id)
        except Exception as e:
            log.warning(f"Could not list users from Firestore: {e}")

        # Only query BigQuery as a fallback if Firestore returned nothing
        if not users:
            try:
                table_id = f"{self.project_id}.{self.dataset_id}.recent_activities"
                query = f"SELECT DISTINCT user_id FROM `{table_id}`"
                df = self.bq.query(query).to_dataframe()
                for u in df["user_id"].dropna():
                    users.add(str(u))
            except Exception as e:
                log.warning(f"Could not list users from recent_activities: {e}")

            try:
                table_id = f"{self.project_id}.{self.dataset_id}.daily_physiology"
                query = f"SELECT DISTINCT user_id FROM `{table_id}`"
                df = self.bq.query(query).to_dataframe()
                for u in df["user_id"].dropna():
                    users.add(str(u))
            except Exception as e:
                log.warning(f"Could not list users from daily_physiology: {e}")

        if not users:
            users.add(os.getenv("DEFAULT_USER_ID", "default_user"))
        result = sorted(users)
        self._users_cache = (now, result)
        return result

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        """Stubs delete_user_data for GCPStorageEngine."""
        log.warning(f"delete_user_data called on GCP engine for {user_id}")
        return {"status": "gcp_deletion_not_implemented", "user_id": user_id}
