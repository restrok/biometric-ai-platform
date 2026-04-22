# Plan de Arquitectura V1: Transición a AI Infrastructure Platform

Este documento consolida la estrategia técnica y arquitectónica para evolucionar el `garmin-training-toolkit` actual hacia una Plataforma de IA de nivel de producción, alineada con el objetivo de demostrar capacidades de Ingeniería de Infraestructura y FinOps.

## 1. Estrategia de Repositorios (The Split)

Hemos decidido adoptar un enfoque de **Repositorios Separados** para garantizar una separación de responsabilidades clara y profesional:

*   **Repo 1: El Extractor de Datos (Actual `garmin-training-toolkit`)**
    *   **Rol:** Funcionar exclusivamente como un SDK/Librería de Ingesta (Data Connector).
    *   **Responsabilidad:** Autenticarse contra Garmin, manejar rate limits, extraer datos crudos (.FIT, JSON) y validarlos contra esquemas estrictos.
    *   **No incluye:** Lógica de IA, modelos LLM, bases de datos vectoriales, ni infraestructura de nube.
*   **Repo 2: La Plataforma IA (Futuro, ej. `biometric-ai-platform`)**
    *   **Rol:** El sistema Core de Agentic RAG y la Infraestructura SRE.
    *   **Responsabilidad:** Orquestar Agentes (LangGraph), exponer la API (FastAPI), manejar Terraform/GCP, y evaluar calidad (Ragas).
    *   **Interacción:** Consumirá los datos estructurados generados por el Repo 1.

## 2. Refactorización del Repositorio Actual (The Toolkit SDK)

Para que este repositorio actual sea útil para los futuros Data Pipelines del Repo 2, debemos transformarlo de "scripts sueltos" a una librería Python formal y fuertemente tipada.

### A. Estructura de Paquete Python
Consolidaremos el código existente (`garmin_utils.py`, `garmin-analyzer/collector.py`) en un paquete estructurado:

```text
garmin-training-toolkit/
├── garmin_toolkit/               # El paquete core
│   ├── __init__.py
│   ├── auth.py                   # Gestión de login y tokens
│   ├── client.py                 # Wrapper de la API de Garmin
│   ├── extractors/               # Módulos específicos por dominio
│   │   ├── activities.py         # Descarga de entrenamientos (.fit / json)
│   │   ├── biometrics.py         # Sueño, HRV, Peso
│   │   └── metrics.py            # Readiness, VO2Max
│   └── models/                   # Pydantic models (Data Contracts)
├── data-pipeline/                # (Opcional, para pruebas locales de ingesta)
└── pyproject.toml                # Gestión con uv o poetry
```

### B. Contratos de Datos (Data Contracts)
El problema principal de la implementación actual es el uso de diccionarios sin esquema. 
*   **Acción:** Se implementarán modelos de **Pydantic** para validar estrictamente cada payload que devuelve Garmin antes de entregarlo al Data Pipeline.
*   **Beneficio:** Evita que esquemas corruptos o cambios silenciosos en la API de Garmin rompan las Vector Databases o los prompts del LLM.

### C. Desacoplamiento de Lógica
*   **Acción:** Separar la lógica de *Extracción* de la lógica de *Formateo/Presentación*.
*   **Beneficio:** El SDK debe devolver únicamente objetos Python limpios. La generación de reportes Markdown actuales se moverá a un módulo aislado de "Visualización Local" que el pipeline de IA no necesitará importar.

## 3. Estrategia de Desarrollo Cost-Zero (FinOps)

Para mantener los costos controlados durante la fase de desarrollo, la arquitectura se diseñará bajo la premisa **"Local First, Cloud for Production"**:

*   **Vector DB:** Uso de `LanceDB` o `ChromaDB` en modo embebido/local.
*   **LLM:** Uso de APIs con Tiers Gratuitos (Gemini, Groq) o modelos locales (Ollama) para el desarrollo del "Reasoning Loop".
*   **Infraestructura (GCP):** Escribiremos la IaC (Terraform) en el Repo 2 para demostrar capacidades de SRE, pero la ejecución (`terraform apply`) se postergará hasta la fase final de validación.

## 4. Próximos Pasos de Ejecución (Action Items)

1.  Inicializar la gestión de dependencias moderna (ej. con `uv`).
2.  Crear el directorio `garmin_toolkit` y reubicar `auth.py` y utilidades comunes.
3.  Definir los primeros modelos Pydantic en `garmin_toolkit/models/` basados en las respuestas de la API observadas en `collector.py`.
4.  Refactorizar la lógica de `collector.py` separándola por dominios dentro de la carpeta `extractors/`.
## 5. Implementación del Monorepo (Actualización)

Tras la inicialización del repositorio `biometric-ai-platform`, se ha implementado la siguiente estructura de directorios, consolidando la separación entre Infraestructura (Terraform) y Backend (API):

```text
biometric-ai-platform/
├── README.md                     # Documentación principal del repositorio
├── ai-infra/                     # Documentación arquitectónica (este directorio)
├── api/                          # AI Engineering & Backend (Python con uv)
│   ├── pyproject.toml            # Gestión de dependencias
│   ├── src/
│   │   ├── agent/                # Nodos y routers de LangGraph
│   │   └── tools/                # Herramientas de interacción para el LLM
│   └── tests/                    # Pipelines de evaluación con Ragas
└── infrastructure/               # SRE / Infraestructura como Código (Terraform)
    ├── modules/                  # Módulos reutilizables
    │   ├── iam/                  # Configuración de Identidad y Accesos
    │   ├── network/              # VPC y Endpoints Privados
    │   └── storage/              # GCS, Artifact Registry, BigQuery
    ├── envs/                     # Variables específicas por entorno
    │   └── dev.tfvars            # Variables para desarrollo
    ├── main.tf                   # Workspace único principal
    └── variables.tf              # Definición de variables globales
```

Esta estructura permite a los equipos de SRE trabajar centralizadamente en `infrastructure/` (utilizando local state inicialmente, inyectando variables por entorno con `-var-file`) mientras que los AI Engineers desarrollan el servidor FastAPI y los agentes en `api/`.

## 5. Storage Architecture (Data Lakehouse) - V2 (Optimized)

To ensure high performance for AI workloads while strictly adhering to Google Cloud's Free Tier limits, the Data Pipeline has evolved from External Tables to a **Native BigQuery Lakehouse** with Incremental Sync:

*   **Extraction:** The `garmin_toolkit` SDK retrieves data as typed Pydantic objects.
*   **Incremental Sync Logic:** The ETL pipeline now queries BigQuery for the `MAX(date)` of existing records and only fetches new data (deltas) from the Garmin API. This prevents rate limiting and redundant data transfer.
*   **Native BigQuery Tables:** We have moved from External GCS tables to Native BigQuery tables. This allows for:
    *   **Append Support:** Efficiently adding new activities and telemetry without rewriting the entire dataset.
    *   **High-Speed Retrieval:** Native tables provide faster response times for the LangGraph agent's retrieval tool.
*   **Archival & Audit:** Every sync continues to archive a timestamped Parquet file to **GCS** before loading into BigQuery, serving as an immutable audit log and backup.

## 6. AI Reasoning & Personalization (Advanced Agentic RAG)

The platform now implements a sophisticated reasoning layer in LangGraph that bridges the gap between generic scientific formulas and individual athlete reality:

*   **Data-Driven Customization:** The agent is instructed to prioritize observed data (e.g., a real Max HR of 196 bpm found in telemetry) over standard formulas (like 220-age).
*   **Subjective Integration (The Talk Test):** The agent integrates user feedback (e.g., "I can talk at 160 bpm") to propose **Custom HR Zones**, recognizing that individual Aerobic Thresholds (AeT) can vary significantly.
*   **Detailed Telemetry Analysis:** The retriever now provides second-by-second summaries of the last 3 activities, allowing the AI to analyze heart rate stability and drift to validate the user's fitness state.

## 7. Current Project State & Accomplishments

*   **SDK Integrated:** `garmin-toolkit` linked via `uv` as a local project dependency.
*   **Fail-Safe Pipeline:** ETL handles missing data (e.g., days without watch wear) gracefully.
*   **Zero-Cost Production Ready:** The entire stack runs within GCP Free Tier and Google AI Studio Free Tier (Gemini 1.5/2.5 Flash).
*   **Infrastructure as Code:** Terraform modules ready for Storage, IAM, and Service Accounts.

## 6. Migration of Legacy Logic (Plan Generation)

The legacy plan generation logic (previously `garmin-analyzer`) has been moved to the `legacy_logic/` folder in this repository. 

**Instructions for the AI Agent:**
When building the AI/Reasoning layer (LangGraph):
*   Do NOT use the old `plan_generator.py` script as a direct dependency.
*   Instead, read the logic inside `legacy_logic/` (especially `RESEARCH_TRAINING_PRINCIPLES.md` and `TRAINING_GUIDELINES.md`) to understand the domain rules (80/20 polarized training, recovery metrics).
*   Re-implement this logic as Tool Functions or System Prompts within the new LangGraph Router Agent. The Agent must consume the Pydantic data contracts (like `TrainingStatusData` and `ActivityTelemetry`) exported by the `garmin_toolkit` SDK to generate personalized training plans dynamically.
