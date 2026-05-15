import asyncio
import json
import logging
import os
import time
from typing import Any, Dict

import pandas as pd
from google.cloud import bigquery, storage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

log = logging.getLogger(__name__)

# Cache clients per project to reduce initialization overhead
_bq_clients: dict[str, bigquery.Client] = {}
_storage_clients: dict[str, storage.Client] = {}

def get_bq_client(project_id: str) -> bigquery.Client:
    """Gets or creates a BigQuery client for the given project ID."""
    global _bq_clients
    if project_id not in _bq_clients:
        _bq_clients[project_id] = bigquery.Client(project=project_id)
    return _bq_clients[project_id]

def get_storage_client(project_id: str) -> storage.Client:
    """Gets or creates a Storage client for the given project ID."""
    global _storage_clients
    if project_id not in _storage_clients:
        _storage_clients[project_id] = storage.Client(project=project_id)
    return _storage_clients[project_id]

async def save_to_gcs(project_id: str, bucket_name: str, file_name: str, content: str) -> str:
    """Sube el reporte a un bucket de GCS de forma asíncrona y genera una Signed URL."""
    def _upload():
        from datetime import timedelta
        client = get_storage_client(project_id)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        blob.upload_from_string(content, content_type='text/markdown')
        
        # Generar Signed URL válida por 1 hora
        try:
            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(hours=1),
                method="GET"
            )
        except Exception as e:
            log.warning(f"Could not generate Signed URL: {e}. Falling back to Authenticated URL.")
            # Fallback to Authenticated URL (requires browser login)
            url = f"https://storage.cloud.google.com/{bucket_name}/{file_name}"
        return url

    return await asyncio.to_thread(_upload)

class HistoricalBiometricsInput(BaseModel):
    """Input schema for analyzing historical biometric evolution."""
    user_id: str = Field(..., description="El ID interno del usuario (ej., 'fsirio').")
    project_id: str | None = Field(None, description="GCP Project ID.")
    dataset: str | None = Field(None, description="BigQuery Dataset ID.")

def _calculate_physiology_metrics(df: pd.DataFrame, user_id: str) -> tuple[Dict[str, Any], str]:
    """
    Núcleo Fisiológico: Calcula Medias Móviles (Aguda/Crónica) y Z-Scores.
    """
    if df.empty:
        return {"status": "no_data"}, "No data available."

    df['date'] = pd.to_datetime(df['date_str'])
    df = df.sort_values('date').set_index('date')

    if 'avg_power' in df.columns and 'avg_hr' in df.columns:
        df['efficiency_index'] = df['avg_power'] / df['avg_hr'].replace(0, pd.NA)
    else:
        df['efficiency_index'] = 1.0

    # Llenar días vacíos para que las medias móviles de tiempo (7d/28d) sean precisas
    df_daily = df.resample('D').agg({
        'distance_km': 'sum',
        'vo2max': 'mean',
        'avg_hr': 'mean',
        'efficiency_index': 'mean'
    }).fillna(0)

    # 1. Carga Aguda (7 días) y Crónica (28 días)
    df_daily['acute_load_7d_km'] = df_daily['distance_km'].rolling(window=7, min_periods=1).sum()
    df_daily['chronic_load_28d_km'] = df_daily['distance_km'].rolling(window=28, min_periods=1).sum() / 4
    
    # Suavizado de métricas de eficiencia (Ignorando los días sin correr para la base)
    df_valid = df_daily[df_daily['distance_km'] > 0].copy()
    df_valid['eff_baseline_60d'] = df_valid['efficiency_index'].rolling(window=60, min_periods=5).mean()
    df_valid['eff_std_60d'] = df_valid['efficiency_index'].rolling(window=60, min_periods=5).std()

    # 2. Detección de Anomalías (Z-Score de los últimos 7 días contra la base de 60 días)
    last_7_days = df_valid.last('7D')
    if not last_7_days.empty and not pd.isna(last_7_days['eff_std_60d'].iloc[-1]):
        current_eff = last_7_days['efficiency_index'].mean()
        baseline_eff = df_valid['eff_baseline_60d'].iloc[-1]
        std_eff = df_valid['eff_std_60d'].iloc[-1]
        z_score = (current_eff - baseline_eff) / std_eff if std_eff > 0 else 0
    else:
        current_eff = baseline_eff = z_score = 0

    # 3. Construcción del JSON Resumen (< 1KB para el LLM)
    warnings = []
    if z_score < -1.5:
        warnings.append("ALERTA: Caída aguda en la eficiencia aeróbica (Z-Score < -1.5). Riesgo de fatiga sistémica.")
    elif z_score > 1.5:
        warnings.append("NOTA: Salto positivo anómalo en eficiencia (Z-Score > 1.5). Pico de forma detectado.")

    current_acute = round(df_daily['acute_load_7d_km'].iloc[-1], 1)
    current_chronic = round(df_daily['chronic_load_28d_km'].iloc[-1], 1)
    ac_ratio = round(current_acute / current_chronic, 2) if current_chronic > 0 else 0

    if ac_ratio > 1.5:
        warnings.append(f"ALERTA DE LESIÓN: Ratio Agudo/Crónico en {ac_ratio} (Umbral seguro < 1.3). Sobrecarga de volumen.")

    # Generación de metadatos del reporte
    timestamp = int(time.time())
    file_name = f"reports/{user_id}/evolution_{timestamp}.md"

    llm_summary = {
        "status": "success",
        "acute_load_7d_km": current_acute,
        "chronic_load_28d_km": current_chronic,
        "acute_chronic_ratio": ac_ratio,
        "efficiency_z_score": round(z_score, 2),
        "warnings": warnings,
        "artifact_path": file_name
    }

    md_report = f"""# Reporte de Evolución Biométrica e Histórica
*Generado automáticamente por el motor de Fisiología AI*

## 1. Resumen de Carga de Entrenamiento
- **Volumen últimos 7 días (Carga Aguda):** {current_acute} km
- **Promedio semanal último mes (Carga Crónica):** {current_chronic} km/semana
- **Ratio Agudo/Crónico (A:C):** {ac_ratio} *(Seguro: 0.8 - 1.3)*

## 2. Análisis de Eficiencia Aeróbica (Power / HR)
- **Baseline (Últimos 60 días):** {round(baseline_eff, 2)}
- **Actual (Últimos 7 días):** {round(current_eff, 2)}
- **Desviación Estándar (Z-Score):** {round(z_score, 2)}

## 3. Advertencias del Sistema
{chr(10).join(['- ⚠️ ' + w for w in warnings]) if warnings else '- ✅ Todos los parámetros están dentro de rangos normales y seguros.'}
    """

    return llm_summary, md_report

@tool(args_schema=HistoricalBiometricsInput)
async def historical_biometrics_tool(
    user_id: str,
    project_id: str | None = None,
    dataset: str | None = None
) -> str:
    """
    MANDATORY for 'Historical Reports', 'Evolution', or 'Monthly Analysis'.
    Analiza la evolución fisiológica histórica del usuario (Carga aguda/crónica y Z-Scores).
    Devuelve un JSON ultra-ligero para no saturar el contexto del agente e indica la URI
    del artefacto detallado en GCS.
    """
    config = get_config()
    pid = project_id or config.get("project_id")
    ds = dataset or config.get("dataset_id")
    bucket_name = os.getenv("DATALAKE_BUCKET") or f"{pid}-biometric-reports"

    if not pid:
        return json.dumps({"error": "GOOGLE_CLOUD_PROJECT not set."})

    def _execute_query():
        client = get_bq_client(pid)
        query = f"""
            SELECT 
                FORMAT_TIMESTAMP('%Y-%m-%d', TIMESTAMP_SECONDS(CAST(date AS INT64))) as date_str,
                SUM(distance_m)/1000 as distance_km,
                AVG(vo2max) as vo2max,
                AVG(avg_hr) as avg_hr,
                AVG(avg_power) as avg_power
            FROM `{pid}.{ds}.recent_activities`
            WHERE user_id = '{user_id}' AND type = 'running'
            GROUP BY 1
            ORDER BY 1 ASC
        """
        return client.query(query).to_dataframe()

    try:
        # LLMOps: Asincronía real delegando al threadpool del event loop (no bloquea FastAPI/LangChain)
        df = await asyncio.to_thread(_execute_query)

        # Procesamiento Fisiológico
        llm_summary, md_report = _calculate_physiology_metrics(df, user_id)

        # Persistir el artefacto detallado en GCS (Asíncrono real)
        file_name = llm_summary.pop("artifact_path")
        gcs_uri = await save_to_gcs(pid, bucket_name, file_name, md_report)
        
        # Actualizar el JSON de retorno para el LLM
        llm_summary["artifact_uri"] = gcs_uri
        log.info(f"✅ Reporte biométrico detallado guardado en: {gcs_uri}")

        return json.dumps(llm_summary)

    except Exception as e:
        log.error(f"❌ Error en historical_biometrics_tool: {e}")
        return json.dumps({"status": "error", "message": str(e)})
