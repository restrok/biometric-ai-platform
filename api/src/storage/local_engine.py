"""Local-First Storage Engine implementing SQLite (OLTP) and DuckDB (OLAP + Vector)."""

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import uuid
from datetime import UTC, date, datetime
from typing import Any

import duckdb

from src.storage.base import StorageEngine

log = logging.getLogger(__name__)


class LocalStorageEngine(StorageEngine):
    """Storage engine using SQLite for transactional entities and DuckDB for analytics/vectors."""

    def __init__(self, data_dir: str | None = None):
        if not data_dir:
            data_dir = os.getenv("BIOMETRIC_DATA_DIR")
        if not data_dir:
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            data_dir = os.path.join(base_path, "data")

        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)

        self.sqlite_path = os.path.join(self.data_dir, "biometric.sqlite")
        self.duckdb_path = os.path.join(self.data_dir, "biometric.duckdb")

        self._init_sqlite()
        self._init_duckdb()
        log.info(f"💾 LocalStorageEngine initialized at: {self.data_dir}")

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _get_duckdb_conn(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.duckdb_path)

    def _init_sqlite(self) -> None:
        with self._get_sqlite_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_goals (
                    goal_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    goal_type TEXT NOT NULL,
                    description TEXT,
                    target_date TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS semantic_memories (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    memory_text TEXT NOT NULL,
                    source_session_id TEXT,
                    confidence_score REAL DEFAULT 1.0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS calibration_markers (
                    marker_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    marker_type TEXT NOT NULL,
                    marker_value REAL NOT NULL,
                    context TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS health_status (
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    feeling TEXT NOT NULL,
                    notes TEXT,
                    fatigue_level INTEGER,
                    injury_notes TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, date)
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                );
            """)

    def _init_duckdb(self) -> None:
        conn = self._get_duckdb_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activities (
                    activity_id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL,
                    activity_name VARCHAR,
                    activity_type VARCHAR,
                    start_time TIMESTAMP,
                    duration_seconds DOUBLE,
                    distance_meters DOUBLE,
                    avg_heart_rate DOUBLE,
                    max_heart_rate DOUBLE,
                    aerobic_training_effect DOUBLE,
                    anaerobic_training_effect DOUBLE,
                    trimp DOUBLE,
                    summary VARCHAR
                );

                CREATE TABLE IF NOT EXISTS activity_telemetry (
                    activity_id VARCHAR,
                    timestamp TIMESTAMP,
                    heart_rate INTEGER,
                    cadence INTEGER,
                    speed DOUBLE,
                    power DOUBLE,
                    vertical_oscillation DOUBLE,
                    ground_contact_time DOUBLE,
                    elevation DOUBLE,
                    PRIMARY KEY (activity_id, timestamp)
                );

                CREATE TABLE IF NOT EXISTS daily_physiology (
                    user_id VARCHAR,
                    date DATE,
                    resting_heart_rate INTEGER,
                    hrv_sdnn DOUBLE,
                    hrv_rmssd DOUBLE,
                    body_battery_max INTEGER,
                    body_battery_min INTEGER,
                    stress_avg INTEGER,
                    sleep_duration_seconds DOUBLE,
                    sleep_score INTEGER,
                    PRIMARY KEY (user_id, date)
                );

                CREATE TABLE IF NOT EXISTS knowledge_vectors (
                    doc_id VARCHAR PRIMARY KEY,
                    content VARCHAR NOT NULL,
                    embedding FLOAT[],
                    metadata VARCHAR
                );
            """)
        finally:
            conn.close()

    # --- Profile & User Management ---
    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        with self._get_sqlite_conn() as conn:
            cursor = conn.execute("SELECT profile_data FROM user_profiles WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["profile_data"])
            return {}

    def update_user_profile(self, user_id: str, data: dict[str, Any]) -> None:
        current = self.get_user_profile(user_id)
        current.update(data)
        now_str = datetime.now(UTC).isoformat()
        with self._get_sqlite_conn() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles (user_id, profile_data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_data = excluded.profile_data,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(current), now_str),
            )
            conn.commit()

    # --- Goals ---
    def get_user_goals(self, user_id: str) -> list[dict[str, Any]]:
        with self._get_sqlite_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM user_goals WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC",
                (user_id,),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def save_user_goal(self, user_id: str, goal: dict[str, Any]) -> str:
        goal_id = str(goal.get("goal_id") or uuid.uuid4())
        now_str = datetime.now(UTC).isoformat()
        with self._get_sqlite_conn() as conn:
            conn.execute(
                """
                INSERT INTO user_goals (goal_id, user_id, goal_type, description, target_date, status, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(goal_id) DO UPDATE SET
                    goal_type = excluded.goal_type,
                    description = excluded.description,
                    target_date = excluded.target_date,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    metadata = excluded.metadata
                """,
                (
                    goal_id,
                    user_id,
                    goal.get("goal_type", "general"),
                    goal.get("description", ""),
                    goal.get("target_date"),
                    goal.get("status", "active"),
                    goal.get("created_at", now_str),
                    now_str,
                    json.dumps(goal.get("metadata", {})),
                ),
            )
            conn.commit()
        return goal_id

    # --- Semantic Memories ---
    def get_semantic_memories(self, user_id: str) -> list[dict[str, Any]]:
        with self._get_sqlite_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM semantic_memories WHERE user_id = ? AND is_active = 1 ORDER BY updated_at DESC",
                (user_id,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def save_semantic_memory(
        self,
        user_id: str,
        memory_text: str,
        memory_type: str = "fact",
        source_session_id: str | None = None,
        confidence_score: float = 1.0,
    ) -> str:
        memory_id = str(uuid.uuid4())
        now_str = datetime.now(UTC).isoformat()
        with self._get_sqlite_conn() as conn:
            conn.execute(
                """
                INSERT INTO semantic_memories (memory_id, user_id, memory_type, memory_text, source_session_id, confidence_score, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    memory_id,
                    user_id,
                    memory_type,
                    memory_text,
                    source_session_id,
                    confidence_score,
                    now_str,
                    now_str,
                ),
            )
            conn.commit()
        return memory_id

    def update_semantic_memory(self, memory_id: str, new_text: str) -> str:
        now_str = datetime.now(UTC).isoformat()
        with self._get_sqlite_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE semantic_memories
                SET memory_text = ?, updated_at = ?, is_active = 1
                WHERE memory_id = ?
                """,
                (new_text, now_str, memory_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return f"Error: Memory {memory_id} not found."
        return f"Successfully updated memory {memory_id}."

    def retire_semantic_memory(self, memory_id: str) -> str:
        now_str = datetime.now(UTC).isoformat()
        with self._get_sqlite_conn() as conn:
            cursor = conn.execute(
                "UPDATE semantic_memories SET is_active = 0, updated_at = ? WHERE memory_id = ?",
                (now_str, memory_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return f"Error: Memory {memory_id} not found."
        return f"Successfully retired memory {memory_id}."

    # --- Calibration Profile Markers ---
    def get_calibration_markers(self, user_id: str) -> list[dict[str, Any]]:
        with self._get_sqlite_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM calibration_markers WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def save_calibration_marker(
        self, user_id: str, marker_type: str, marker_value: float, context: str | None = None
    ) -> str:
        marker_id = str(uuid.uuid4())
        now_str = datetime.now(UTC).isoformat()
        with self._get_sqlite_conn() as conn:
            conn.execute(
                """
                INSERT INTO calibration_markers (marker_id, user_id, marker_type, marker_value, context, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (marker_id, user_id, marker_type, marker_value, context, now_str, now_str),
            )
            conn.commit()
        return marker_id

    # --- Health Status ---
    def get_health_status(self, user_id: str) -> dict[str, Any] | None:
        with self._get_sqlite_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM health_status WHERE user_id = ? ORDER BY date DESC LIMIT 1",
                (user_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def log_health_status(self, user_id: str, health_data: dict[str, Any]) -> str:
        target_date = str(health_data.get("date") or date.today().isoformat())
        now_str = datetime.now(UTC).isoformat()
        with self._get_sqlite_conn() as conn:
            conn.execute(
                """
                INSERT INTO health_status (user_id, date, feeling, notes, fatigue_level, injury_notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, date) DO UPDATE SET
                    feeling = excluded.feeling,
                    notes = excluded.notes,
                    fatigue_level = excluded.fatigue_level,
                    injury_notes = excluded.injury_notes,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    target_date,
                    health_data.get("feeling", "Normal"),
                    health_data.get("notes"),
                    health_data.get("fatigue_level"),
                    health_data.get("injury_notes"),
                    now_str,
                ),
            )
            conn.commit()
        return target_date

    # --- Analytical Series & Telemetry ---
    def insert_activities(self, user_id: str, activities: list[dict[str, Any]]) -> None:
        if not activities:
            return
        conn = self._get_duckdb_conn()
        try:
            for act in activities:
                act_id = str(act.get("activity_id") or uuid.uuid4())
                conn.execute(
                    """
                    INSERT OR REPLACE INTO activities (
                        activity_id, user_id, activity_name, activity_type, start_time,
                        duration_seconds, distance_meters, avg_heart_rate, max_heart_rate,
                        aerobic_training_effect, anaerobic_training_effect, trimp, summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        act_id,
                        user_id,
                        act.get("activity_name"),
                        act.get("activity_type", "running"),
                        act.get("start_time"),
                        act.get("duration_seconds"),
                        act.get("distance_meters"),
                        act.get("avg_heart_rate"),
                        act.get("max_heart_rate"),
                        act.get("aerobic_training_effect"),
                        act.get("anaerobic_training_effect"),
                        act.get("trimp"),
                        json.dumps(act.get("summary", {})),
                    ],
                )
        finally:
            conn.close()

    def insert_daily_physiology(self, user_id: str, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        conn = self._get_duckdb_conn()
        try:
            for rec in records:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO daily_physiology (
                        user_id, date, resting_heart_rate, hrv_sdnn, hrv_rmssd,
                        body_battery_max, body_battery_min, stress_avg,
                        sleep_duration_seconds, sleep_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        user_id,
                        rec.get("date"),
                        rec.get("resting_heart_rate"),
                        rec.get("hrv_sdnn"),
                        rec.get("hrv_rmssd"),
                        rec.get("body_battery_max"),
                        rec.get("body_battery_min"),
                        rec.get("stress_avg"),
                        rec.get("sleep_duration_seconds"),
                        rec.get("sleep_score"),
                    ],
                )
        finally:
            conn.close()

    def get_recent_activities(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
        activity_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._get_duckdb_conn()
        try:
            query = "SELECT * FROM activities WHERE user_id = ?"
            params: list[Any] = [user_id]

            if activity_type:
                query += " AND LOWER(activity_type) = LOWER(?)"
                params.append(activity_type)
            if start_date:
                query += " AND start_time >= ?"
                params.append(start_date)
            if end_date:
                query += " AND start_time <= ?"
                params.append(end_date)

            query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            df = conn.execute(query, params).df()
            return df.to_dict(orient="records")
        finally:
            conn.close()

    def get_activity_telemetry(self, activity_id: str, _user_id: str | None = None) -> list[dict[str, Any]]:
        conn = self._get_duckdb_conn()
        try:
            df = conn.execute(
                "SELECT * FROM activity_telemetry WHERE activity_id = ? ORDER BY timestamp ASC",
                [activity_id],
            ).df()
            return df.to_dict(orient="records")
        finally:
            conn.close()

    def get_daily_physiology(self, user_id: str, days: int = 14) -> list[dict[str, Any]]:
        conn = self._get_duckdb_conn()
        try:
            df = conn.execute(
                """
                SELECT * FROM daily_physiology
                WHERE user_id = ?
                ORDER BY date DESC
                LIMIT ?
                """,
                [user_id, days],
            ).df()
            return df.to_dict(orient="records")
        finally:
            conn.close()

    def query_macro_load_history(
        self, user_id: str, group_by: str = "weekly", limit_months: int = 6
    ) -> list[dict[str, Any]]:
        conn = self._get_duckdb_conn()
        try:
            time_col = "date_trunc('week', start_time)" if group_by == "weekly" else "date_trunc('month', start_time)"
            query = f"""
                SELECT
                    {time_col} AS period,
                    count(activity_id) AS total_sessions,
                    coalesce(sum(distance_meters), 0) / 1000.0 AS total_distance_km,
                    coalesce(sum(duration_seconds), 0) / 3600.0 AS total_hours,
                    coalesce(sum(trimp), 0) AS total_trimp,
                    coalesce(avg(avg_heart_rate), 0) AS avg_hr
                FROM activities
                WHERE user_id = ? AND start_time >= CURRENT_DATE - INTERVAL '{limit_months} MONTH'
                GROUP BY period
                ORDER BY period ASC
            """
            df = conn.execute(query, [user_id]).df()
            return df.to_dict(orient="records")
        finally:
            conn.close()

    # --- Vector Search / RAG ---
    def search_knowledge_vectors(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        conn = self._get_duckdb_conn()
        try:
            # Check if knowledge_vectors has rows
            row = conn.execute("SELECT count(*) FROM knowledge_vectors").fetchone()
            if not row or row[0] == 0:
                return []

            query = """
                SELECT content, metadata, list_cosine_similarity(embedding, ?) AS score
                FROM knowledge_vectors
                ORDER BY score DESC
                LIMIT ?
            """
            df = conn.execute(query, [query_vector, top_k]).df()
            return df.to_dict(orient="records")
        finally:
            conn.close()

    def list_users(self) -> list[str]:
        """Retrieves list of active athlete/user IDs."""
        users = set()
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.execute("SELECT DISTINCT user_id FROM user_profiles")
                for row in cursor.fetchall():
                    if row[0]:
                        users.add(str(row[0]))
        except Exception:
            pass

        try:
            duck_conn = self._get_duckdb_conn()
            try:
                df = duck_conn.execute("SELECT DISTINCT user_id FROM activities").df()
                for u in df["user_id"].dropna():
                    users.add(str(u))
            finally:
                duck_conn.close()
        except Exception:
            pass

        if not users:
            users.add(os.getenv("DEFAULT_USER_ID", "default_user"))
        return sorted(users)

    # --- API Keys & Multi-Tenant Auth ---
    def _hash_key(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def create_api_key(self, user_id: str, name: str = "default") -> str:
        raw_key = f"bio_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_key(raw_key)
        key_id = str(uuid.uuid4())
        now_str = datetime.now(UTC).isoformat()

        with self._get_sqlite_conn() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (key_id, user_id, key_hash, name, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (key_id, user_id, key_hash, name, now_str),
            )
            conn.commit()
        log.info(f"🔑 Generated API Key '{name}' for user '{user_id}'")
        return raw_key

    def validate_api_key(self, api_key: str, user_id: str) -> bool:
        key_hash = self._hash_key(api_key)
        with self._get_sqlite_conn() as conn:
            cursor = conn.execute(
                """
                SELECT key_id FROM api_keys
                WHERE user_id = ? AND key_hash = ? AND is_active = 1
                """,
                (user_id, key_hash),
            )
            row = cursor.fetchone()
            return row is not None

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        """Deletes an athlete and all associated data from SQLite, DuckDB, and Vault."""
        from src.utils.vault import get_vault

        counts: dict[str, Any] = {}

        # 1. SQLite Deletions
        with self._get_sqlite_conn() as conn:
            for table in [
                "user_profiles",
                "user_goals",
                "semantic_memories",
                "calibration_markers",
                "health_status",
                "api_keys",
            ]:
                cursor = conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
                counts[table] = cursor.rowcount
            conn.commit()

        # 2. DuckDB Deletions
        conn_d = self._get_duckdb_conn()
        try:
            conn_d.execute(
                """
                DELETE FROM activity_telemetry 
                WHERE activity_id IN (SELECT activity_id FROM activities WHERE user_id = ?)
                """,
                [user_id],
            )
            conn_d.execute("DELETE FROM activities WHERE user_id = ?", [user_id])
            conn_d.execute("DELETE FROM daily_physiology WHERE user_id = ?", [user_id])
            counts["duckdb_cleaned"] = True
        finally:
            conn_d.close()

        # 3. Vault Deletions
        deleted_tokens = get_vault().delete_user_tokens(user_id)
        counts["vault_tokens"] = deleted_tokens

        log.info(f"🗑️ Completely deleted athlete '{user_id}': {counts}")
        return counts
