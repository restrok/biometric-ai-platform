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
    └── environments/
        └── dev/                  # Entorno de desarrollo local/cloud
            ├── main.tf
            ├── terraform.tfvars
            └── variables.tf
```

Esta estructura permite a los equipos de SRE trabajar independientemente en `infrastructure/` (utilizando local state inicialmente, con miras a migrar a remote state) mientras que los AI Engineers desarrollan el servidor FastAPI y los agentes en `api/`.
